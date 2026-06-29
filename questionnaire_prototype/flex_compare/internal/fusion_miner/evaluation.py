from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import traceback
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from flex_compare.internal.fusion_miner.runtime import FACADE_MAIN_CLASS
from flex_compare.internal.fusion_miner.runtime import LPSOLVE_NATIVE_DIR
from flex_compare.internal.fusion_miner.runtime import LPSOLVE_LIBRARY_PATHS
from flex_compare.internal.fusion_miner.runtime import build_runtime_classpath
from flex_compare.internal.fusion_miner.runtime import compile_java_facade
from flex_compare.internal.fusion_miner.runtime import materialize_prom_lock
from flex_compare.internal.fusion_miner.runtime import select_java_binaries
from flex_compare.internal.shared.complexity_metrics import compute_cfc
from flex_compare.internal.shared.params_base import BaseMinerParams


DEFAULT_PRECISION_VALID_SAMPLES = 5000
DEFAULT_PRECISION_SEED = 42
DEFAULT_PRECISION_K = 2


@dataclass(frozen=True)
class HeuristicsParams(BaseMinerParams):
    relative_to_best_threshold: float = 0.05
    positive_observation_threshold: int = 1
    dependency_threshold: float = 0.9
    l1l_threshold: float = 0.9
    l2l_threshold: float = 0.9
    long_distance_threshold: float = 0.9
    dependency_divisor: int = 1
    use_all_connected_heuristics: bool = True
    use_long_distance_dependency: bool = False
    use_unique_start_end_tasks: bool = False


@dataclass(frozen=True)
class FusionParams(BaseMinerParams):
    declare_support: float = 1.0
    declare_alpha: float = 1.0
    activity_entropy: float = 0.4
    resilience: float = 0.1
    im_fitness: float = 0.2
    size_multiplicator: int = 1
    cut: bool = True
    prune: bool = True
    negative: bool = True
    check_model: bool = False


DEFAULT_HEURISTICS_PARAMS = HeuristicsParams()
DEFAULT_FUSION_PARAMS = FusionParams()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _collect_artifacts(output_dir: Path) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            artifacts.append(
                {
                    "name": str(path.relative_to(output_dir)),
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return artifacts


def _build_java_command(
    *,
    log_path: Path,
    output_dir: Path,
    heuristics: HeuristicsParams,
    fusion: FusionParams,
    java_headless: bool,
    precision_valid_samples: int = DEFAULT_PRECISION_VALID_SAMPLES,
    precision_max_trace_length: int = 200,
    precision_seed: int = DEFAULT_PRECISION_SEED,
) -> List[str]:
    java_bins = select_java_binaries()
    classpath = build_runtime_classpath()
    java_library_path = os.pathsep.join(str(path) for path in LPSOLVE_LIBRARY_PATHS) or "."
    cmd = [
        str(java_bins["java"]),
        "-Xmx4G",
        f"-Djava.awt.headless={'true' if java_headless else 'false'}",
        f"-Djava.library.path={java_library_path}",
        f"-Dthesis.fusion.lpsolve.native.dir={LPSOLVE_NATIVE_DIR}" if LPSOLVE_NATIVE_DIR.exists() else "-Dthesis.fusion.lpsolve.native.dir=",
        "-Djava.system.class.loader=org.processmining.framework.util.ProMClassLoader",
        "-cp",
        classpath,
        FACADE_MAIN_CLASS,
        "--log",
        str(log_path.resolve()),
        "--output-dir",
        str(output_dir.resolve()),
        "--relative-to-best-threshold",
        str(heuristics.relative_to_best_threshold),
        "--positive-observation-threshold",
        str(heuristics.positive_observation_threshold),
        "--dependency-threshold",
        str(heuristics.dependency_threshold),
        "--l1l-threshold",
        str(heuristics.l1l_threshold),
        "--l2l-threshold",
        str(heuristics.l2l_threshold),
        "--long-distance-threshold",
        str(heuristics.long_distance_threshold),
        "--dependency-divisor",
        str(heuristics.dependency_divisor),
        "--use-all-connected-heuristics",
        str(heuristics.use_all_connected_heuristics).lower(),
        "--use-long-distance-dependency",
        str(heuristics.use_long_distance_dependency).lower(),
        "--use-unique-start-end-tasks",
        str(heuristics.use_unique_start_end_tasks).lower(),
        "--declare-support",
        str(fusion.declare_support),
        "--declare-alpha",
        str(fusion.declare_alpha),
        "--activity-entropy",
        str(fusion.activity_entropy),
        "--resilience",
        str(fusion.resilience),
        "--im-fitness",
        str(fusion.im_fitness),
        "--size-multiplicator",
        str(fusion.size_multiplicator),
        "--cut",
        str(fusion.cut).lower(),
        "--prune",
        str(fusion.prune).lower(),
        "--negative",
        str(fusion.negative).lower(),
        "--check-model",
        str(fusion.check_model).lower(),
        "--precision-valid-samples",
        str(precision_valid_samples),
        "--precision-max-trace-length",
        str(precision_max_trace_length),
        "--precision-seed",
        str(precision_seed),
    ]
    return cmd


def _compute_metrics(
    *,
    java_manifest: Mapping[str, Any],
    hybrid_model: Mapping[str, Any],
    pnwa_model: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    procedural = hybrid_model.get("procedural", {})
    declarative = hybrid_model.get("declarative", {})
    procedural_nodes = procedural.get("nodes") or []
    procedural_edges = procedural.get("edges") or []
    declarative_constraints = declarative.get("constraints") or []
    pnwa_metrics: Dict[str, Any] = {
        "pnwa_transition_count": None,
        "pnwa_place_count": None,
        "pnwa_arc_count": None,
        "pnwa_constraint_count": None,
        "pnwa_constraint_type_counts": {},
        "pnwa_unary_constraint_count": None,
        "pnwa_binary_constraint_count": None,
        "pnwa_procedural_to_declarative_ratio": None,
    }
    if pnwa_model:
        constraints = pnwa_model.get("constraints") or []
        type_counts: Dict[str, int] = {}
        unary = 0
        binary = 0
        for constraint in constraints:
            ctype = str(constraint.get("type") or "unknown")
            type_counts[ctype] = type_counts.get(ctype, 0) + 1
            arity = str(constraint.get("arity") or "").lower()
            if arity == "binary":
                binary += 1
            elif arity == "unary":
                unary += 1
        pnwa_metrics = {
            "pnwa_transition_count": len(pnwa_model.get("transitions") or []),
            "pnwa_place_count": len(pnwa_model.get("places") or []),
            "pnwa_arc_count": len(pnwa_model.get("arcs") or []),
            "pnwa_constraint_count": len(constraints),
            "pnwa_constraint_type_counts": type_counts,
            "pnwa_unary_constraint_count": unary,
            "pnwa_binary_constraint_count": binary,
            "pnwa_procedural_to_declarative_ratio": (
                round(
                    (len(pnwa_model.get("arcs") or []) / len(constraints)),
                    6,
                )
                if constraints
                else None
            ),
        }

    constraint_type_counts: Dict[str, int] = {}
    for constraint in declarative_constraints:
        ctype = str(constraint.get("template") or "unknown")
        constraint_type_counts[ctype] = constraint_type_counts.get(ctype, 0) + 1
    declarative_constraint_count = len(declarative_constraints)

    # Cardoso CFC on the procedural Petri net (PNML).
    # Captures only the procedural backbone; the declarative constraint layer
    # of fusion models has no gateway semantics and is therefore not reflected.
    cfc_value: Optional[int] = None
    cfc_pnml_path = java_manifest.get("pnml_path")
    if cfc_pnml_path:
        try:
            import pm4py

            cfc_net, _, _ = pm4py.read_pnml(str(cfc_pnml_path))
            cfc_value = compute_cfc(cfc_net)
        except Exception:
            cfc_value = None

    mpcc_fitness = java_manifest.get("mpcc_fitness")
    pnwa_precision_status = java_manifest.get("pnwa_precision_status", "not_available")
    pnwa_precision_value = java_manifest.get("pnwa_precision")
    pnwa_precision_method = java_manifest.get("pnwa_precision_method")
    pnwa_precision_scope = "pnwa" if pnwa_precision_status == "ok" else None

    # Always re-measure precision with PM4Py on the exported pure Petri net
    # (no Declare automata). This gives a metric that is directly comparable
    # to the imperative miner's precision, regardless of how many constraints
    # the PNwA carries. When constraints == 0 the PM4Py value also becomes
    # the primary precision (then PNwA == pure net structurally, and using
    # AlignmentPrecGen would just compare two ETC implementations against
    # each other instead of the actual model).
    primary_precision = pnwa_precision_value
    primary_precision_method = pnwa_precision_method
    primary_precision_scope = pnwa_precision_scope
    pure_net_fallback_reason: Optional[str] = None
    pure_net_metrics: Optional[Dict[str, Any]] = None
    pure_net_runtime_ms: Optional[int] = None
    pnml_path = java_manifest.get("pnml_path")
    log_path = java_manifest.get("log_path")
    if pnml_path and log_path:
        pure_net_started_at = time.perf_counter()
        try:
            pure_net_metrics = _compute_pure_net_precision(
                pnml_path=Path(pnml_path),
                log_path=Path(log_path),
            )
            pure_net_runtime_ms = int((time.perf_counter() - pure_net_started_at) * 1000)
            if pnwa_metrics.get("pnwa_constraint_count") == 0 and pnwa_precision_status == "ok":
                primary_precision = pure_net_metrics["precision"]
                primary_precision_method = "alignment_based_etc_pure_net_pm4py"
                primary_precision_scope = "pure_net"
        except Exception as exc:
            pure_net_fallback_reason = f"{type(exc).__name__}: {exc}"
            pure_net_runtime_ms = int((time.perf_counter() - pure_net_started_at) * 1000)

    # ── Phase B: derived diagnostics on top of pure-net + PNwA precision ────
    pure_net_precision_value = pure_net_metrics.get("precision") if pure_net_metrics else None
    pure_net_fitness_value = pure_net_metrics.get("fitness") if pure_net_metrics else None

    # Fallback when AlignmentPrecGen failed/skipped: surface the Pure-Net
    # PM4Py value as primary precision so the report is not empty. Any
    # pnwa_precision still in the manifest is unreliable when status != ok,
    # so we override it. Method/scope encode that this is a different state
    # space (no Declare automata). Independent of the
    # `precision_pure_net_meaningful` threshold; that flag is reported
    # separately so consumers can warn on low-fitness cases.
    if pnwa_precision_status != "ok" and pure_net_precision_value is not None:
        primary_precision = pure_net_precision_value
        primary_precision_method = "alignment_based_etc_pure_net_pm4py_fallback"
        primary_precision_scope = "pure_net_fallback"

    # Symmetric fallback for fitness: when MixedParadigm replay failed/aborted
    # (mpcc_status != "success") the manifest's mpcc_fitness is null. Expose
    # the PM4Py alignment fitness on the procedural Petri-net as a
    # clearly-labeled fallback so the table shows a value. This is the same
    # measure the imperative miner reports, scoped to the procedural backbone
    # only — Declare automata are not enforced.
    mpcc_status = java_manifest.get("mpcc_status", "not_available")
    primary_fitness = mpcc_fitness
    fitness_method: Optional[str] = "mpcc_pnwa_replay" if mpcc_status == "success" else None
    fitness_scope: Optional[str] = "pnwa" if mpcc_status == "success" else None
    if mpcc_status != "success" and pure_net_fitness_value is not None:
        primary_fitness = pure_net_fitness_value
        fitness_method = "alignment_based_pure_net_pm4py_fallback"
        fitness_scope = "pure_net_fallback"

    # Heuristic threshold: PM4Py ETC precision collapses to ~0 when many log
    # activities are not modelled by the procedural skeleton (alignments fill
    # with model-only moves → trie pollution). At ≥0.95 trace fitness those
    # ETC artefacts become empirically small. Threshold is arbitrary and
    # documented in fusion_miner/PRECISION.md §9.
    PURE_NET_PRECISION_FITNESS_THRESHOLD = 0.95
    precision_pure_net_meaningful: Optional[bool] = None
    if pure_net_fitness_value is not None:
        precision_pure_net_meaningful = (
            pure_net_fitness_value >= PURE_NET_PRECISION_FITNESS_THRESHOLD
        )

    # Hybrid precision lift Δ — only meaningful when:
    #  - PNwA precision came from a successful AlignmentPrecGen run, AND
    #  - pure-net precision is itself meaningful (≥ 0.95 fitness), AND
    #  - the PNwA actually carries Declare constraints (otherwise the Δ
    #    collapses to PM4Py-vs-ProM implementation drift on identical
    #    structures, not to a constraint-induced behavioral restriction).
    hybrid_precision_lift: Optional[float] = None
    if (
        pnwa_precision_status == "ok"
        and pnwa_precision_value is not None
        and pure_net_precision_value is not None
        and precision_pure_net_meaningful is True
        and (pnwa_metrics.get("pnwa_constraint_count") or 0) > 0
    ):
        hybrid_precision_lift = pnwa_precision_value - pure_net_precision_value

    # F1 (Fusion) — harmonic mean of MPCC fitness and PNwA precision. Only
    # filled when both operands are PNwA-scope and both have status == "ok",
    # so the operands come from the same methodology family on the same
    # state space (no spurious mixing with Pure-Net values).
    fusion_f1: Optional[float] = None
    if (
        java_manifest.get("mpcc_status") == "success"
        and pnwa_precision_status == "ok"
        and primary_precision_method == "alignment_based_etc_pnwa"
        and isinstance(mpcc_fitness, (int, float))
        and isinstance(pnwa_precision_value, (int, float))
        and (mpcc_fitness + pnwa_precision_value) > 0
    ):
        fusion_f1 = (
            2 * mpcc_fitness * pnwa_precision_value
            / (mpcc_fitness + pnwa_precision_value)
        )

    quality_metrics: Dict[str, Any] = {
        "mpcc_fitness": mpcc_fitness,
        "fitness": primary_fitness,
        "fitness_method": fitness_method,
        "fitness_scope": fitness_scope,
        "precision": primary_precision,
        "generalization": java_manifest.get("pnwa_generalization"),
        "precision_status": pnwa_precision_status,
        "precision_method": primary_precision_method,
        "precision_scope": primary_precision_scope,
        "precision_error": java_manifest.get("pnwa_precision_error"),
        "precision_runtime_ms": java_manifest.get("pnwa_precision_runtime_ms"),
        "precision_pnwa_alignmentprecgen": pnwa_precision_value,
        "precision_pure_net_pm4py": pure_net_precision_value,
        "fitness_pure_net_pm4py": pure_net_fitness_value,
        "precision_pure_net_meaningful": precision_pure_net_meaningful,
        "precision_pure_net_runtime_ms": pure_net_runtime_ms,
        "precision_pure_net_fallback_reason": pure_net_fallback_reason,
        "hybrid_precision_lift": hybrid_precision_lift,
        "f1": fusion_f1,
        "hybrid_sampling_n_valid": java_manifest.get("hybrid_sampling_n_valid"),
        "hybrid_sampling_n_attempts": java_manifest.get("hybrid_sampling_n_attempts"),
        "hybrid_sampling_n_rejected_deadlock": java_manifest.get("hybrid_sampling_n_rejected_deadlock"),
        "hybrid_sampling_n_rejected_too_long": java_manifest.get("hybrid_sampling_n_rejected_too_long"),
        "hybrid_sampling_n_truncated_at_final": java_manifest.get("hybrid_sampling_n_truncated_at_final"),
        "hybrid_sampling_max_trace_length": java_manifest.get("hybrid_sampling_max_trace_length"),
        "hybrid_sampling_seed": java_manifest.get("hybrid_sampling_seed"),
        "hybrid_sampling_runtime_ms": java_manifest.get("hybrid_sampling_runtime_ms"),
    }
    return {
        "discovery_runtime_ms": java_manifest.get("runtime_ms"),
        "success": java_manifest.get("status") == "success",
        "mpcc_fitness": mpcc_fitness,
        "mpcc_status": java_manifest.get("mpcc_status", "not_available"),
        "mpcc_runtime_ms": java_manifest.get("mpcc_runtime_ms"),
        "mpcc_error": java_manifest.get("mpcc_error"),
        "mpcc_method": java_manifest.get("mpcc_method"),
        "mpcc_replay_result_size": java_manifest.get("mpcc_replay_result_size"),
        "mpcc_mapped_transition_count": java_manifest.get("mpcc_mapped_transition_count"),
        "mpcc_unmapped_transition_count": java_manifest.get("mpcc_unmapped_transition_count"),
        "procedural_node_count": len(procedural_nodes),
        "procedural_edge_count": len(procedural_edges),
        "declarative_constraint_count": declarative_constraint_count,
        "hybrid_has_declarative_part": declarative_constraint_count > 0,
        "declarative_constraint_type_counts": constraint_type_counts,
        "entropic_activity_count": len(hybrid_model.get("entropic_activities") or []),
        "removed_constraint_count": len(hybrid_model.get("removed_constraints") or []),
        "tau_transition_count": len(hybrid_model.get("tau_transitions") or []),
        "cfc": cfc_value,
        **pnwa_metrics,
        "quality_metrics": quality_metrics,
    }


def _compute_pure_net_precision(
    *,
    pnml_path: Path,
    log_path: Path,
) -> Dict[str, Any]:
    """Re-measure precision/fitness on the procedural Petri net via PM4Py.

    Used when the PNwA contains zero declarative constraints — then the
    "PNwA" is structurally a pure Petri net, and applying PM4Py's
    `precision_alignments` makes the value directly comparable to the
    imperative miner's precision (same implementation, same model class).
    """
    import pm4py

    net, im, fm = pm4py.read_pnml(str(pnml_path))
    for transition in net.transitions:
        label = transition.label
        if not label:
            continue
        # FusionMINERful suffixes visible labels with "+" (lifecycle:complete).
        # The XES log uses bare concept:names, so strip the suffix.
        if label.endswith("+"):
            label = label[:-1]
        # PNML round-trip can leave tau transitions with a visible label like
        # "tau split"/"tau join"/"tau from tree". Mark them invisible so
        # PM4Py's silent-closure treats them correctly in `available`.
        if label.startswith("tau "):
            transition.label = None
        else:
            transition.label = label
    log = pm4py.read_xes(str(log_path), return_legacy_log_object=True)
    fitness_raw = pm4py.conformance.fitness_alignments(log, net, im, fm)
    precision = pm4py.conformance.precision_alignments(log, net, im, fm)
    return {
        "precision": precision,
        "fitness": fitness_raw.get("average_trace_fitness"),
        "fitness_raw": fitness_raw,
    }


def _load_log_traces(log_path: Path) -> list[list[str]]:
    """Read XES into a list of activity-name sequences (concept:name)."""
    try:
        import pm4py
    except ImportError:
        return []
    try:
        log = pm4py.read_xes(str(log_path), return_legacy_log_object=True)
    except Exception:
        try:
            log = pm4py.read_xes(str(log_path))
        except Exception:
            return []
    traces: list[list[str]] = []
    try:
        iterator = iter(log)
    except TypeError:
        return []
    for trace in iterator:
        seq: list[str] = []
        for event in trace:
            name = event.get("concept:name") if hasattr(event, "get") else None
            if name is not None:
                seq.append(str(name))
        traces.append(seq)
    return traces


def evaluate_log_with_fusion(
    *,
    log_path: Path,
    output_dir: Path,
    run_id: str,
    heuristics: HeuristicsParams = DEFAULT_HEURISTICS_PARAMS,
    fusion: FusionParams = DEFAULT_FUSION_PARAMS,
    java_headless: bool = False,
    precision_valid_samples: int = DEFAULT_PRECISION_VALID_SAMPLES,
    precision_seed: int = DEFAULT_PRECISION_SEED,
    precision_k: int = DEFAULT_PRECISION_K,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "java_stdout.log"
    stderr_path = logs_dir / "java_stderr.log"

    started_at_epoch = time.time()
    started_perf = time.perf_counter()
    materialize_prom_lock(download_missing_archives=False)
    compile_java_facade()

    cmd = _build_java_command(
        log_path=log_path,
        output_dir=output_dir,
        heuristics=heuristics,
        fusion=fusion,
        java_headless=java_headless,
        precision_valid_samples=precision_valid_samples,
        precision_seed=precision_seed,
    )
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=output_dir,
    )
    java_headless_effective = java_headless
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    raw_dir = output_dir / "assets" / "raw"
    normalized_dir = output_dir / "assets" / "normalized"
    rendered_dir = output_dir / "assets" / "rendered"
    java_manifest_path = raw_dir / "headless_manifest.json"

    status = "success" if proc.returncode == 0 else "error"
    error_class = None
    error_message = None
    if java_manifest_path.exists():
        java_manifest = json.loads(java_manifest_path.read_text(encoding="utf-8"))
        status = java_manifest.get("status", status)
        error_class = java_manifest.get("error_class")
        error_message = java_manifest.get("error_message")
    else:
        java_manifest = {
            "status": status,
            "runtime_ms": int((time.perf_counter() - started_perf) * 1000),
            "error_class": "JavaProcessFailure" if proc.returncode != 0 else None,
            "error_message": f"Headless facade exited with code {proc.returncode}" if proc.returncode != 0 else None,
        }
        error_class = java_manifest["error_class"]
        error_message = java_manifest["error_message"]

    hybrid_model_path = normalized_dir / "hybrid_model.json"
    pnwa_model_path = normalized_dir / "pnwa_model.json"
    hybrid_model = (
        json.loads(hybrid_model_path.read_text(encoding="utf-8"))
        if hybrid_model_path.exists()
        else {}
    )
    pnwa_model = (
        json.loads(pnwa_model_path.read_text(encoding="utf-8"))
        if pnwa_model_path.exists()
        else None
    )

    def _valid_png(path: Path) -> bool:
        try:
            return path.exists() and path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    hybrid_render_path = None
    pnwa_render_path = None
    hybrid_png_path = None
    pnwa_png_path = None
    hybrid_visualization_fallback = None
    java_hybrid_png = rendered_dir / "hybrid_model.png"
    java_pnwa_png = rendered_dir / "pnwa_model.png"
    hybrid_png_created_flag = bool(java_manifest.get("hybrid_png_created"))
    pnwa_png_created_flag = bool(java_manifest.get("pnwa_png_created"))
    if hybrid_png_created_flag and _valid_png(java_hybrid_png):
        hybrid_png_path = java_hybrid_png
        hybrid_render_path = java_hybrid_png
    if pnwa_png_created_flag and _valid_png(java_pnwa_png):
        pnwa_png_path = java_pnwa_png
        pnwa_render_path = java_pnwa_png

    lock = json.loads(
        (Path(__file__).resolve().parent / "prom-lock.json").read_text(encoding="utf-8")
    )
    java_bins = select_java_binaries()
    finished_at_epoch = time.time()

    metrics = _compute_metrics(
        java_manifest=java_manifest,
        hybrid_model=hybrid_model,
        pnwa_model=pnwa_model,
    )
    artifacts = _collect_artifacts(output_dir)

    run = {
        "run_id": run_id,
        "input_log_path": str(log_path.resolve()),
        "input_log_sha256": _sha256(log_path),
        "miner_name": "FusionMINERful",
        "miner_version": "6.12.2",
        "prom_version": lock.get("prom_version"),
        "package_versions": {
            item["name"]: item["version"]
            for item in lock.get("resolved_packages", [])
        },
        "java_version": java_bins["version_text"],
        "parameters": {
            "heuristics": asdict(heuristics),
            "fusion": asdict(fusion),
        },
        "started_at": started_at_epoch,
        "finished_at": finished_at_epoch,
        "runtime_ms": java_manifest.get("runtime_ms"),
        "exit_status": status,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "artifacts": artifacts,
        "metrics": metrics,
        "error_class": error_class,
        "error_message": error_message,
        "hybrid_model_path": str(hybrid_model_path) if hybrid_model_path.exists() else None,
        "pnwa_model_path": str(pnwa_model_path) if pnwa_model_path.exists() else None,
        "hybrid_rendered_png_path": str(hybrid_png_path) if hybrid_png_path else None,
        "pnwa_rendered_png_path": str(pnwa_png_path) if pnwa_png_path else None,
        "hybrid_rendered_path": str(hybrid_render_path) if hybrid_render_path else None,
        "pnwa_rendered_path": str(pnwa_render_path) if pnwa_render_path else None,
        "hybrid_visualization_fallback": hybrid_visualization_fallback,
        "connections_path": java_manifest.get("connections_path"),
        "hybrid_png_created": java_manifest.get("hybrid_png_created"),
        "hybrid_png_error": java_manifest.get("hybrid_png_error"),
        "hybrid_svg_created": java_manifest.get("hybrid_svg_created"),
        "pnwa_png_created": java_manifest.get("pnwa_png_created"),
        "pnwa_png_error": java_manifest.get("pnwa_png_error"),
        "pnwa_svg_created": java_manifest.get("pnwa_svg_created"),
        "mpcc_result_path": java_manifest.get("mpcc_result_path"),
        "mpcc_status": java_manifest.get("mpcc_status"),
        "mpcc_fitness": java_manifest.get("mpcc_fitness"),
        "mpcc_runtime_ms": java_manifest.get("mpcc_runtime_ms"),
        "mpcc_error": java_manifest.get("mpcc_error"),
        "mpcc_method": java_manifest.get("mpcc_method"),
        "java_command": cmd,
        "java_returncode": proc.returncode,
        "java_headless_requested": java_headless,
        "java_headless_effective": java_headless_effective,
    }

    canonical_run_path = output_dir / "run.json"
    canonical_run_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    mirror_path = output_dir / "result_data.json"
    mirror_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return run


def run_safe_evaluation(
    *,
    log_path: Path,
    output_dir: Path,
    run_id: str,
    heuristics: HeuristicsParams = DEFAULT_HEURISTICS_PARAMS,
    fusion: FusionParams = DEFAULT_FUSION_PARAMS,
    java_headless: bool = False,
    precision_valid_samples: int = DEFAULT_PRECISION_VALID_SAMPLES,
    precision_seed: int = DEFAULT_PRECISION_SEED,
    precision_k: int = DEFAULT_PRECISION_K,
) -> Dict[str, Any]:
    try:
        return evaluate_log_with_fusion(
            log_path=log_path,
            output_dir=output_dir,
            run_id=run_id,
            heuristics=heuristics,
            fusion=fusion,
            java_headless=java_headless,
            precision_valid_samples=precision_valid_samples,
            precision_seed=precision_seed,
            precision_k=precision_k,
        )
    except Exception as exc:  # pragma: no cover - defensive integration path
        failed = {
            "run_id": run_id,
            "input_log_path": str(log_path),
            "exit_status": "error",
            "error_class": exc.__class__.__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "artifacts": _collect_artifacts(output_dir) if output_dir.exists() else [],
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "run.json").write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding="utf-8")
        (output_dir / "result_data.json").write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding="utf-8")
        return failed
