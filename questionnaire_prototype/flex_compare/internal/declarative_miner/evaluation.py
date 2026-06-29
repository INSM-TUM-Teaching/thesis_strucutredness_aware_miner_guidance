from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from flex_compare.internal.declarative_evaluation.minerful_fitness import run_minerful_fitness_check
from flex_compare.internal.shared.formatting import fmt_bool_ja_nein, fmt_bool_yes_no, na_if_none, round_if_number
from flex_compare.internal.shared.params_base import BaseMinerParams


T_LANG_VALUES: Tuple[str, ...] = (
    "Absence",
    "AlternatePrecedence",
    "AlternateResponse",
    "AlternateSuccession",
    "AtLeast1",
    "AtLeast2",
    "AtLeast3",
    "AtMost1",
    "AtMost2",
    "AtMost3",
    "ChainPrecedence",
    "ChainResponse",
    "ChainSuccession",
    "CoExistence",
    "End",
    "Init",
    "NotChainPrecedence",
    "NotChainResponse",
    "NotChainSuccession",
    "NotCoExistence",
    "NotPrecedence",
    "NotRespondedExistence",
    "NotResponse",
    "NotSuccession",
    "Precedence",
    "RespondedExistence",
    "Response",
    "Succession",
)

_T_LANG_HASH = hashlib.sha256(",".join(sorted(T_LANG_VALUES)).encode("utf-8")).hexdigest()[:12]
T_LANG_VERSION = f"minerful-tlang-v1-{_T_LANG_HASH}"


REPORT_COLUMNS = [
    "Log",
    "Miner",
    "Model generated",
    "Validation status",
    "Discovery (s)",
    "#Activities",
    "#Constraints",
    "#Constraint types",
    "#Constraints per type",
    "Negative constraints",
    "Size",
    "Density",
    "Separability",
    "Constraint Variability",
    "Fitness",
    "Precision",
    "Generalisation",
    "T_lang_version",
    "Minerful version",
    "Notes",
    # MINERful FitnessChecker headline (tool-emitted)
    "fitness_check_executed",
    "n_constraints_evaluated",
    "n_traces_evaluated",
    "avg_fitness",
    "trace_fit_ratio",
    # MINERful FitnessChecker per-CSV-column sums (tool-emitted summands)
    "sum_full_satisfactions",
    "sum_vacuous_satisfactions",
    "sum_violations",
    # MINERful FitnessChecker derived (pure arithmetic over tool-emitted values)
    "mean_trace_full_satisfaction_rate",
    "mean_trace_non_violation_rate",
    "mean_trace_violation_rate",
    "share_constraints_with_zero_violations",
    "fitness_check_notes",
]


@dataclass(frozen=True)
class DiscoveryParams(BaseMinerParams):
    support: float = 0.05
    confidence: float = 0.95
    coverage: float = 0.05
    trace_support: float = 0.0
    trace_confidence: float = 0.0
    trace_coverage: float = 0.0
    prune: str = "hierarchyconflictredundancydouble"
    prune_ranking_by: str | None = None
    prune_hierarchy_by: str | None = None
    keep_constraints: bool = False
    kb_ll_threads: int | None = None
    q_ll_threads: int | None = None
    foresee_distances: bool = False
    show_mem_peak: bool = False
    exclude_results_in: str | None = None
    stats_xml_out: str | None = None


DEFAULT_DISCOVERY_PARAMS = DiscoveryParams()


_format_bool_ja_nein = fmt_bool_ja_nein
_round_if_number = round_if_number
_format_yes_no = fmt_bool_yes_no
_na_if_none = na_if_none


def _sanitize_label(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_task_labels(raw_tasks: Any) -> Tuple[List[str], bool, List[str]]:
    notes: List[str] = []
    fallback_used = False

    if not isinstance(raw_tasks, list):
        return [], True, ["tasks is not a list"]

    normalized: List[str] = []
    for idx, value in enumerate(raw_tasks):
        if not isinstance(value, str):
            fallback_used = True
            value = str(value)
            notes.append(f"task[{idx}] converted to string via fallback normalization")
        clean = value.strip()
        if clean != value:
            fallback_used = True
            notes.append(f"task[{idx}] trimmed during normalization")
        if not clean:
            fallback_used = True
            notes.append(f"task[{idx}] empty after normalization and was dropped")
            continue
        normalized.append(clean)

    deduped = sorted(set(normalized))
    if len(deduped) < len(normalized):
        fallback_used = True
        notes.append("duplicate task labels detected and deduplicated")

    return deduped, fallback_used, notes


def _collect_parameter_activities(parameters: Any) -> Tuple[List[str], bool, List[str]]:
    notes: List[str] = []
    fallback_used = False
    collected: List[str] = []

    if not isinstance(parameters, list):
        fallback_used = True
        parameters = [parameters]
        notes.append("parameters normalized via fallback flattening")

    stack = list(parameters)
    while stack:
        current = stack.pop()
        if isinstance(current, (list, tuple, set)):
            stack.extend(list(current))
            continue
        if current is None:
            fallback_used = True
            notes.append("None value in parameters ignored during normalization")
            continue

        if not isinstance(current, str):
            fallback_used = True
            notes.append(f"non-string parameter value '{current}' converted to string")
            current = str(current)

        clean = current.strip()
        if clean != current:
            fallback_used = True
            notes.append("parameter value trimmed during normalization")
        if not clean:
            fallback_used = True
            notes.append("empty parameter value dropped during normalization")
            continue
        collected.append(clean)

    return sorted(set(collected)), fallback_used, notes


def _extract_template(constraint_obj: Mapping[str, Any], idx: int) -> Tuple[str, bool, List[str]]:
    notes: List[str] = []
    fallback_used = False
    template_raw = constraint_obj.get("template")
    if template_raw is None:
        fallback_used = True
        notes.append(f"constraint[{idx}] missing template")
        return "", fallback_used, notes

    if not isinstance(template_raw, str):
        fallback_used = True
        notes.append(f"constraint[{idx}] template converted to string")
        template_raw = str(template_raw)
    template = template_raw.strip()
    if template != template_raw:
        fallback_used = True
        notes.append(f"constraint[{idx}] template trimmed")
    return template, fallback_used, notes


def parse_and_validate_specification(
    specification_path: Path,
    *,
    t_lang_values: Sequence[str] = T_LANG_VALUES,
) -> Dict[str, Any]:
    notes: List[str] = []
    t_lang_sorted = sorted(set(str(v).strip() for v in t_lang_values if str(v).strip()))

    try:
        raw = json.loads(specification_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "json_parseable": False,
            "model_generated": False,
            "model_validation_status": "invalid",
            "model_validation_notes": [f"JSON parsing failed: {exc}"],
            "activities": [],
            "constraints": [],
            "constraint_type_counts": {},
            "negative_constraints_present": None,
            "graph_metrics": {
                "size": None,
                "density": None,
                "separability": None,
                "constraint_variability": None,
            },
            "raw_specification": None,
            "t_lang_values": t_lang_sorted,
        }

    fallback_used = False

    activities, task_fallback, task_notes = _normalize_task_labels(raw.get("tasks"))
    fallback_used = fallback_used or task_fallback
    notes.extend(task_notes)
    activity_set = set(activities)

    raw_constraints = raw.get("constraints")
    constraints_parseable = isinstance(raw_constraints, list)
    if not constraints_parseable:
        notes.append("constraints is missing or not a list")
        raw_constraints = []

    normalized_constraints: List[Dict[str, Any]] = []
    constraint_type_counts: Dict[str, int] = {}
    unknown_references: List[str] = []
    missing_references: List[str] = []

    for idx, item in enumerate(raw_constraints):
        if not isinstance(item, dict):
            fallback_used = True
            notes.append(f"constraint[{idx}] is not an object and was skipped")
            continue

        template, template_fallback, template_notes = _extract_template(item, idx)
        fallback_used = fallback_used or template_fallback
        notes.extend(template_notes)

        refs, refs_fallback, refs_notes = _collect_parameter_activities(item.get("parameters", []))
        fallback_used = fallback_used or refs_fallback
        notes.extend(f"constraint[{idx}]: {note}" for note in refs_notes)

        if not refs:
            missing_references.append(f"constraint[{idx}] has no resolvable activity references")

        unknown = sorted(set(refs) - activity_set)
        if unknown:
            unknown_references.append(
                f"constraint[{idx}] references unknown activities: {', '.join(unknown)}"
            )

        if template:
            constraint_type_counts[template] = constraint_type_counts.get(template, 0) + 1

        normalized_constraints.append(
            {
                "idx": idx,
                "template": template,
                "activities": refs,
            }
        )

    notes.extend(missing_references)
    notes.extend(unknown_references)

    json_parseable = True
    tasks_present = len(activities) > 0
    constraints_present = len(normalized_constraints) > 0
    unresolved_references = bool(unknown_references or missing_references)

    if not tasks_present:
        notes.append("tasks missing after normalization")
    if not constraints_present:
        notes.append("constraints missing after normalization")

    if json_parseable and tasks_present and constraints_present and not unresolved_references:
        model_generated = True
        model_validation_status = "valid_with_fallback" if fallback_used else "valid"
    else:
        model_generated = False
        model_validation_status = "invalid"

    graph_metrics = {
        "size": None,
        "density": None,
        "separability": None,
        "constraint_variability": None,
    }
    if model_generated:
        graph_metrics = compute_graph_metrics(
            activities=activities,
            constraints=normalized_constraints,
            t_lang_values=t_lang_sorted,
        )

    negative_constraints_present = (
        any(name.startswith("Not") for name in constraint_type_counts) if constraints_present else None
    )

    return {
        "json_parseable": json_parseable,
        "model_generated": model_generated,
        "model_validation_status": model_validation_status,
        "model_validation_notes": notes,
        "activities": activities,
        "constraints": normalized_constraints,
        "constraint_type_counts": dict(sorted(constraint_type_counts.items())),
        "negative_constraints_present": negative_constraints_present,
        "graph_metrics": graph_metrics,
        "raw_specification": raw,
        "t_lang_values": t_lang_sorted,
    }


def _connected_components(
    activities: Sequence[str],
    constraints: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    adjacency: Dict[Tuple[str, Any], set] = {}

    for activity in activities:
        adjacency[("A", activity)] = set()
    for constraint in constraints:
        cnode = ("C", int(constraint["idx"]))
        adjacency.setdefault(cnode, set())
        for activity in constraint.get("activities", []):
            anode = ("A", activity)
            adjacency.setdefault(anode, set())
            adjacency[cnode].add(anode)
            adjacency[anode].add(cnode)

    components: List[Dict[str, Any]] = []
    visited: set = set()

    for node in adjacency:
        if node in visited:
            continue
        stack = [node]
        visited.add(node)
        comp_nodes: List[Tuple[str, Any]] = []
        while stack:
            current = stack.pop()
            comp_nodes.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)

        component_activities = [n[1] for n in comp_nodes if n[0] == "A"]
        component_constraint_idx = [n[1] for n in comp_nodes if n[0] == "C"]
        components.append(
            {
                "activity_labels": component_activities,
                "constraint_indices": component_constraint_idx,
            }
        )
    return components


def _component_entropy_base(
    *,
    templates_in_component: Sequence[str],
    t_lang_values: Sequence[str],
) -> float | None:
    base = len(t_lang_values)
    if base <= 1:
        return None
    if not templates_in_component:
        return None

    total = len(templates_in_component)
    counts: Dict[str, int] = {}
    for tpl in templates_in_component:
        counts[tpl] = counts.get(tpl, 0) + 1

    denom = math.log(base)
    entropy = 0.0
    for tpl in t_lang_values:
        cnt = counts.get(tpl, 0)
        if cnt == 0:
            continue
        p = cnt / total
        entropy -= p * (math.log(p) / denom)
    return entropy


def compute_graph_metrics(
    *,
    activities: Sequence[str],
    constraints: Sequence[Mapping[str, Any]],
    t_lang_values: Sequence[str],
) -> Dict[str, Any]:
    n_activities = len(activities)
    n_constraints = len(constraints)
    size = n_activities + n_constraints

    if size == 0:
        return {
            "size": 0,
            "density": None,
            "separability": None,
            "constraint_variability": 0,
            "component_count": 0,
            "variability_note": "no activities and no constraints",
        }

    components = _connected_components(activities=activities, constraints=constraints)
    component_count = len(components)
    separability = component_count / size

    density_candidates: List[float] = []
    variability_candidates: List[float] = []
    variability_note = None

    constraints_by_idx = {int(c["idx"]): c for c in constraints}

    for comp in components:
        a_k = len(comp["activity_labels"])
        c_k = len(comp["constraint_indices"])
        if a_k > 0:
            density_candidates.append(c_k / a_k)

        if c_k > 0:
            templates = [
                str(constraints_by_idx[idx].get("template", ""))
                for idx in comp["constraint_indices"]
                if idx in constraints_by_idx
            ]
            entropy = _component_entropy_base(
                templates_in_component=templates,
                t_lang_values=t_lang_values,
            )
            if entropy is None:
                variability_note = "|T_lang| <= 1, variability not computable"
            else:
                variability_candidates.append(entropy)

    density = max(density_candidates) if density_candidates else 0

    if n_constraints == 0:
        variability = 0
    elif len(t_lang_values) <= 1:
        variability = None
    else:
        variability = max(variability_candidates) if variability_candidates else 0

    return {
        "size": size,
        "density": density,
        "separability": separability,
        "constraint_variability": variability,
        "component_count": component_count,
        "variability_note": variability_note,
    }


def detect_minerful_version(minerful_dir: Path) -> str:
    version_candidates = [
        minerful_dir / "VERSION",
        minerful_dir / "version.txt",
        minerful_dir / "version",
    ]
    for candidate in version_candidates:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return text

    readme = minerful_dir / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"Version[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return "unknown"


def _build_cli_parameter_map(params: DiscoveryParams) -> Dict[str, Any]:
    return {
        "support": params.support,
        "confidence": params.confidence,
        "coverage": params.coverage,
        "trace_support": params.trace_support,
        "trace_confidence": params.trace_confidence,
        "trace_coverage": params.trace_coverage,
        "prune": params.prune,
        "prune_ranking_by": params.prune_ranking_by,
        "prune_hierarchy_by": params.prune_hierarchy_by,
        "keep_constraints": params.keep_constraints,
        "kb_ll_threads": params.kb_ll_threads,
        "q_ll_threads": params.q_ll_threads,
        "foresee_distances": params.foresee_distances,
        "show_mem_peak": params.show_mem_peak,
        "exclude_results_in": params.exclude_results_in,
        "stats_xml_out": params.stats_xml_out,
    }


def _build_literature_threshold_context() -> Dict[str, str]:
    return {
        "support": "conceptual threshold from literature",
        "confidence": "conceptual threshold from literature",
        "interest_factor": "conceptual threshold from literature (not auto-mapped to CLI coverage)",
    }


def run_minerful_discovery(
    *,
    log_path: Path,
    minerful_dir: Path,
    output_spec_dir: Path,
    output_automata_dir: Path,
    params: DiscoveryParams = DEFAULT_DISCOVERY_PARAMS,
) -> Dict[str, Any]:
    log_path_abs = log_path.resolve()
    minerful_dir_abs = minerful_dir.resolve()
    output_spec_dir_abs = output_spec_dir.resolve()
    output_automata_dir_abs = output_automata_dir.resolve()
    output_spec_dir_abs.mkdir(parents=True, exist_ok=True)
    output_automata_dir_abs.mkdir(parents=True, exist_ok=True)

    script = minerful_dir_abs / "run-MINERful.sh"
    if not script.exists():
        raise FileNotFoundError(f"MINERful launcher not found: {script}")
    run_name = log_path_abs.stem
    out_json = output_spec_dir_abs / f"{run_name}.json"
    out_csv = output_spec_dir_abs / f"{run_name}.csv"
    out_dot = output_automata_dir_abs / f"{run_name}.dot"

    cmd = [
        str(script),
        "-iLF",
        str(log_path_abs),
        "-prune",
        params.prune,
        "--support",
        str(params.support),
        "--confidence",
        str(params.confidence),
        "--coverage",
        str(params.coverage),
        "--trace-support",
        str(params.trace_support),
        "--trace-confidence",
        str(params.trace_confidence),
        "--trace-coverage",
        str(params.trace_coverage),
        "-oCSV",
        str(out_csv),
        "-oJSON",
        str(out_json),
        "-autoDOT",
        str(out_dot),
    ]
    if params.prune_ranking_by:
        cmd.extend(["-pruneRnk", str(params.prune_ranking_by)])
    if params.prune_hierarchy_by:
        cmd.extend(["-pruneHier", str(params.prune_hierarchy_by)])
    if params.keep_constraints:
        cmd.append("-keep")
    if params.kb_ll_threads is not None:
        cmd.extend(["-para", str(params.kb_ll_threads)])
    if params.q_ll_threads is not None:
        cmd.extend(["-paraQ", str(params.q_ll_threads)])
    if params.foresee_distances:
        cmd.append("-withDist")
    if params.show_mem_peak:
        cmd.append("-memShow")
    if params.exclude_results_in:
        cmd.extend(["-exclTasks", str(Path(params.exclude_results_in).resolve())])
    if params.stats_xml_out:
        cmd.extend(["-statsXML", str(Path(params.stats_xml_out).resolve())])

    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=minerful_dir_abs,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started

    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "discovery_runtime_sec": elapsed,
        "json_path": out_json,
        "csv_path": out_csv,
        "dot_path": out_dot,
    }


def evaluate_log_with_minerful(
    *,
    log_path: Path,
    minerful_dir: Path,
    output_spec_dir: Path,
    output_automata_dir: Path,
    params: DiscoveryParams = DEFAULT_DISCOVERY_PARAMS,
    t_lang_values: Sequence[str] = T_LANG_VALUES,
) -> Dict[str, Any]:
    t_total_start = time.perf_counter()

    run_result = run_minerful_discovery(
        log_path=log_path,
        minerful_dir=minerful_dir,
        output_spec_dir=output_spec_dir,
        output_automata_dir=output_automata_dir,
        params=params,
    )

    minerful_version = detect_minerful_version(minerful_dir)
    json_path = run_result["json_path"]
    t_parse_start = time.perf_counter()
    parsed = parse_and_validate_specification(json_path, t_lang_values=t_lang_values)
    t_parse_spec = time.perf_counter() - t_parse_start

    fitness_csv_path = output_spec_dir.resolve() / f"{log_path.stem}.fitness.csv"
    t_fitness_start = time.perf_counter()
    fitness_summary = run_minerful_fitness_check(
        log_path=log_path,
        minerful_json_path=json_path,
        output_csv_path=fitness_csv_path,
    )
    t_fitness_total = time.perf_counter() - t_fitness_start
    t_total = time.perf_counter() - t_total_start
    stage_runtimes_sec = {
        "discovery": run_result["discovery_runtime_sec"],
        "parse_spec_and_graph_metrics": t_parse_spec,
        "fitness_total": t_fitness_total,
        "fitness_subprocess": fitness_summary.get("fitness_runtime_sec"),
        "total": t_total,
    }
    print(
        f"[minerful-timing] {log_path.stem}: "
        f"discovery={stage_runtimes_sec['discovery']:.3f}s "
        f"parse={t_parse_spec:.3f}s "
        f"fitness_total={t_fitness_total:.3f}s "
        f"fitness_jvm={stage_runtimes_sec['fitness_subprocess']!r} "
        f"total={t_total:.3f}s",
        flush=True,
    )

    graph_metrics = parsed["graph_metrics"]
    notes = list(parsed["model_validation_notes"])
    fitness_check_notes = list(fitness_summary.get("fitness_check_notes") or [])
    # Surface the gap between discovered constraints and constraints actually
    # evaluated by the FitnessChecker. MINERful re-applies its own
    # threshold-based pruning before measurement; constraints whose computed
    # statistics fall below the checker's defaults are silently dropped.
    n_disc = len(parsed["constraints"]) if parsed["constraints"] else 0
    n_eval = (fitness_summary.get("fitness_metrics") or {}).get(
        "n_constraints_evaluated"
    )
    if (
        fitness_summary.get("available")
        and n_disc
        and isinstance(n_eval, int)
        and n_eval < n_disc
    ):
        gap_note = (
            f"FitnessChecker evaluated {n_eval} of {n_disc} discovered "
            "constraints; the rest were pruned by MINERful's internal "
            "threshold/subsumption pass before measurement."
        )
        fitness_check_notes.append(gap_note)
    notes.extend(f"FitnessChecker: {note}" for note in fitness_check_notes)
    if run_result["returncode"] != 0:
        notes.append(f"MINERful return code: {run_result['returncode']}")
    if run_result["stderr"].strip():
        notes.append("MINERful stderr was non-empty")

    constraint_type_counts = parsed["constraint_type_counts"]
    fitness_value = "n/a"
    precision_value = "n/a"
    generalisation_value = "n/a"

    result = {
        "log_name": log_path.stem,
        "log_path": str(log_path),
        "miner": "MINERful",
        "minerful_version": minerful_version,
        "T_lang_version": T_LANG_VERSION,
        "T_lang_values": list(parsed["t_lang_values"]),
        "model_generated": parsed["model_generated"],
        "model_validation_status": parsed["model_validation_status"],
        "model_validation_notes": notes,
        "discovery_runtime_sec": run_result["discovery_runtime_sec"],
        "stage_runtimes_sec": stage_runtimes_sec,
        "used_cli_parameters": _build_cli_parameter_map(params),
        "literature_thresholds_context": _build_literature_threshold_context(),
        "n_activities": len(parsed["activities"]) if parsed["activities"] else 0,
        "n_constraints": len(parsed["constraints"]) if parsed["constraints"] else 0,
        "n_constraint_types": len(constraint_type_counts),
        "constraints_per_type": constraint_type_counts,
        "negative_constraints_present": parsed["negative_constraints_present"],
        "size": graph_metrics["size"] if parsed["model_generated"] else None,
        "density": graph_metrics["density"] if parsed["model_generated"] else None,
        "separability": graph_metrics["separability"] if parsed["model_generated"] else None,
        "constraint_variability": (
            graph_metrics["constraint_variability"] if parsed["model_generated"] else None
        ),
        "fitness": fitness_value,
        "precision": precision_value,
        "generalisation": generalisation_value,
        "json_path": str(run_result["json_path"]),
        "csv_path": str(run_result["csv_path"]),
        "dot_path": str(run_result["dot_path"]),
        # MINERful FitnessChecker results — tool-emitted + pure-arithmetic derived
        "fitness_summary": fitness_summary,
        "fitness_check_executed": bool(fitness_summary.get("available", False)),
        "fitness_tool": fitness_summary.get("tool"),
        "fitness_tool_version": fitness_summary.get("tool_version"),
        "n_constraints_evaluated": fitness_summary.get("fitness_metrics", {}).get(
            "n_constraints_evaluated"
        ),
        "n_traces_evaluated": fitness_summary.get("fitness_metrics", {}).get(
            "n_traces_evaluated"
        ),
        "avg_fitness": fitness_summary.get("fitness_metrics", {}).get("avg_fitness"),
        "trace_fit_ratio": fitness_summary.get("fitness_metrics", {}).get(
            "trace_fit_ratio"
        ),
        "sum_full_satisfactions": fitness_summary.get("fitness_metrics", {}).get(
            "sum_full_satisfactions"
        ),
        "sum_vacuous_satisfactions": fitness_summary.get("fitness_metrics", {}).get(
            "sum_vacuous_satisfactions"
        ),
        "sum_violations": fitness_summary.get("fitness_metrics", {}).get(
            "sum_violations"
        ),
        "vacuity_rate": fitness_summary.get("fitness_metrics", {}).get(
            "vacuity_rate"
        ),
        # Algebraic complement of vacuity_rate on the same discovered
        # post-pruning constraint set (1 - vacuity_rate); single source.
        "non_vacuous_satisfaction_rate": fitness_summary.get(
            "fitness_metrics", {}
        ).get("non_vacuous_satisfaction_rate"),
        "mean_trace_full_satisfaction_rate": fitness_summary.get(
            "model_aggregates", {}
        ).get("mean_trace_full_satisfaction_rate"),
        "mean_trace_non_violation_rate": fitness_summary.get(
            "model_aggregates", {}
        ).get("mean_trace_non_violation_rate"),
        "mean_trace_violation_rate": fitness_summary.get("model_aggregates", {}).get(
            "mean_trace_violation_rate"
        ),
        "share_constraints_with_zero_violations": fitness_summary.get(
            "model_aggregates", {}
        ).get("share_constraints_with_zero_violations"),
        "fitness_check_notes": fitness_check_notes,
        "stdout": run_result["stdout"],
        "stderr": run_result["stderr"],
        "returncode": run_result["returncode"],
    }

    return result


def evaluate_logs_with_minerful(
    *,
    log_paths: Sequence[Path],
    minerful_dir: Path,
    output_spec_dir: Path,
    output_automata_dir: Path,
    params: DiscoveryParams = DEFAULT_DISCOVERY_PARAMS,
    t_lang_values: Sequence[str] = T_LANG_VALUES,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for log_path in log_paths:
        results.append(
            evaluate_log_with_minerful(
                log_path=log_path,
                minerful_dir=minerful_dir,
                output_spec_dir=output_spec_dir,
                output_automata_dir=output_automata_dir,
                params=params,
                t_lang_values=t_lang_values,
            )
        )
    return results


def make_report_row(result: Mapping[str, Any], digits: int = 6) -> Dict[str, Any]:
    notes = result.get("model_validation_notes") or []
    if isinstance(notes, list):
        notes_text = " | ".join(str(n) for n in notes) if notes else ""
    else:
        notes_text = str(notes)

    fitness_check_notes = result.get("fitness_check_notes") or []
    if isinstance(fitness_check_notes, list):
        fitness_notes_text = (
            " | ".join(str(n) for n in fitness_check_notes) if fitness_check_notes else ""
        )
    else:
        fitness_notes_text = str(fitness_check_notes)

    return {
        "Log": result.get("log_name"),
        "Miner": result.get("miner"),
        "Model generated": _format_bool_ja_nein(result.get("model_generated")),
        "Validation status": result.get("model_validation_status"),
        "Discovery (s)": _round_if_number(result.get("discovery_runtime_sec"), digits),
        "#Activities": result.get("n_activities"),
        "#Constraints": result.get("n_constraints"),
        "#Constraint types": result.get("n_constraint_types"),
        "#Constraints per type": json.dumps(result.get("constraints_per_type", {}), ensure_ascii=True),
        "Negative constraints": _format_bool_ja_nein(result.get("negative_constraints_present")),
        "Size": _round_if_number(result.get("size"), digits),
        "Density": _round_if_number(result.get("density"), digits),
        "Separability": _round_if_number(result.get("separability"), digits),
        "Constraint Variability": _round_if_number(result.get("constraint_variability"), digits),
        "Fitness": result.get("fitness", "n/a"),
        "Precision": result.get("precision", "n/a"),
        "Generalisation": result.get("generalisation", "n/a"),
        "T_lang_version": result.get("T_lang_version"),
        "Minerful version": result.get("minerful_version"),
        "Notes": notes_text,
        # MINERful FitnessChecker headline (tool-emitted)
        "fitness_check_executed": _format_yes_no(result.get("fitness_check_executed")),
        "n_constraints_evaluated": _na_if_none(result.get("n_constraints_evaluated")),
        "n_traces_evaluated": _na_if_none(result.get("n_traces_evaluated")),
        "avg_fitness": _na_if_none(_round_if_number(result.get("avg_fitness"), digits)),
        "trace_fit_ratio": _na_if_none(
            _round_if_number(result.get("trace_fit_ratio"), digits)
        ),
        "sum_full_satisfactions": _na_if_none(result.get("sum_full_satisfactions")),
        "sum_vacuous_satisfactions": _na_if_none(result.get("sum_vacuous_satisfactions")),
        "sum_violations": _na_if_none(result.get("sum_violations")),
        # MINERful FitnessChecker derived (pure arithmetic over tool-emitted values)
        "mean_trace_full_satisfaction_rate": _na_if_none(
            _round_if_number(result.get("mean_trace_full_satisfaction_rate"), digits)
        ),
        "mean_trace_non_violation_rate": _na_if_none(
            _round_if_number(result.get("mean_trace_non_violation_rate"), digits)
        ),
        "mean_trace_violation_rate": _na_if_none(
            _round_if_number(result.get("mean_trace_violation_rate"), digits)
        ),
        "share_constraints_with_zero_violations": _na_if_none(
            _round_if_number(result.get("share_constraints_with_zero_violations"), digits)
        ),
        "fitness_check_notes": fitness_notes_text or "n/a",
    }


def make_report_dataframe(results: Iterable[Mapping[str, Any]], digits: int = 6):
    import pandas as pd

    rows = [make_report_row(result, digits=digits) for result in results]
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)
