from __future__ import annotations

"""
Generic pm4py discovery backend for the comparison app's extensibility PoC.

This module demonstrates the *achievable core* of "plug in an arbitrary miner":
any pm4py discovery algorithm that yields a Petri net flows through the **same**
imperative evaluation path (pm4py alignment fitness/precision, net-size and
soundness metrics) that the Inductive Miner already uses. We deliberately reuse
the imperative miner's extraction helpers rather than re-implementing them, so
the produced metrics are directly commensurable with the ``imp`` miner and need
no separate harmonisation.

Supported algorithms (``algorithm`` argument):
* ``"heuristics"`` — Heuristics Miner (``dependency_threshold``); no process tree.
* ``"alpha"``      — Alpha Miner; no parameters; no process tree.
* ``"inductive"``  — Inductive Miner (``noise_threshold``); yields a process tree,
                     so the tree-derived structural metrics (depth, flower) are
                     populated too — same as the standalone imperative miner.

The thesis-relevant honesty caveat: for the tree-less algorithms the
process-tree structural metrics stay ``None`` (the UI already renders missing
metrics gracefully), and the paradigm is *declared* imperative in the registry
rather than auto-detected.
"""

import datetime as dt
import getpass
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pm4py
from pm4py.objects.log.importer.xes import importer as xes_importer

from flex_compare.internal.experiment_reports import build_report_output_dir, infer_experiment_class
from flex_compare.internal.imperative_miner.evaluation import (
    _extract_fitness_precision,
    _extract_net_stats,
    _extract_process_tree,
    _extract_soundness,
    _infer_log_name,
    set_log_name,
)
from flex_compare.internal.shared.pdf_export import safe_pdf_export as _safe_pdf_export


# Display label per algorithm — used in the report and (later) the UI.
ALGORITHM_LABELS = {
    # Petri-net family
    "heuristics":  "Heuristics Miner",
    "alpha":       "Alpha Miner",
    "alpha_plus":  "Alpha+ Miner",
    "inductive":   "Inductive Miner",
    "ilp":         "ILP Miner",
    "genetic":     "Genetic Miner",
    # Declarative family (Constraint outputs — NOT Petri nets)
    "declare":     "Declare Miner (pm4py)",
    "log_skeleton": "Log Skeleton",
}

# Which algorithms produce a declarative constraint set instead of a Petri net.
# Used by ``evaluate_log`` to choose the right evaluation/render path.
DECLARATIVE_ALGORITHMS = frozenset({"declare", "log_skeleton"})


def _discover(
    log,
    *,
    algorithm: str,
    dependency_threshold: float,
    and_threshold: float,
    loop_two_threshold: float,
    noise_threshold: float,
    disable_fallthroughs: bool,
    ilp_alpha: float,
    population_size: int,
    generations: int,
    crossover_rate: float,
    mutation_rate: float,
) -> Tuple[Any, Any, Any, Optional[Any]]:
    """Discover a Petri net with the chosen pm4py algorithm.

    Returns ``(net, im, fm, process_tree_or_None)``. Only the Inductive variant
    yields a process tree; the others return ``None`` for it.
    """
    if algorithm == "heuristics":
        net, im, fm = pm4py.discover_petri_net_heuristics(
            log,
            dependency_threshold=dependency_threshold,
            and_threshold=and_threshold,
            loop_two_threshold=loop_two_threshold,
        )
        return net, im, fm, None
    if algorithm == "alpha":
        net, im, fm = pm4py.discover_petri_net_alpha(log)
        return net, im, fm, None
    if algorithm == "alpha_plus":
        net, im, fm = pm4py.discover_petri_net_alpha_plus(log)
        return net, im, fm, None
    if algorithm == "inductive":
        process_tree = pm4py.discover_process_tree_inductive(
            log,
            noise_threshold=noise_threshold,
            disable_fallthroughs=disable_fallthroughs,
        )
        net, im, fm = pm4py.convert_to_petri_net(process_tree)
        return net, im, fm, process_tree
    if algorithm == "ilp":
        net, im, fm = pm4py.discover_petri_net_ilp(log, alpha=ilp_alpha)
        return net, im, fm, None
    if algorithm == "genetic":
        net, im, fm = pm4py.discover_petri_net_genetic(
            log,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
        )
        return net, im, fm, None
    raise ValueError(
        f"unknown Petri-net algorithm {algorithm!r}; expected one of "
        f"{sorted(set(ALGORITHM_LABELS) - DECLARATIVE_ALGORITHMS)}"
    )


def _discover_declarative(
    log,
    *,
    algorithm: str,
    min_support_ratio: Optional[float],
    min_confidence_ratio: Optional[float],
    noise_threshold: float,
) -> Dict[str, Any]:
    """Discover a declarative model (Declare or Log Skeleton).

    Returns a plain dict with the constraint payload + a render-ready summary.
    pm4py's ``discover_declare`` / ``discover_log_skeleton`` return native
    Python dicts already; we just JSON-stringify them here so they survive the
    result-cache round-trip without losing structure.
    """
    if algorithm == "declare":
        model = pm4py.discover_declare(
            log,
            min_support_ratio=min_support_ratio,
            min_confidence_ratio=min_confidence_ratio,
        )
    elif algorithm == "log_skeleton":
        model = pm4py.discover_log_skeleton(log, noise_threshold=noise_threshold)
    else:
        raise ValueError(
            f"unknown declarative algorithm {algorithm!r}; "
            "expected one of {'declare', 'log_skeleton'}"
        )
    return _serialise_declarative(model, algorithm)


def _serialise_declarative(model, algorithm: str) -> Dict[str, Any]:
    """Convert a pm4py declarative model into a JSON-safe summary + raw payload.

    The summary feeds ``constraint_density`` / ``constraint_variability`` /
    ``flower_detected`` proxies; the raw payload is persisted so the UI can
    render the constraint table.
    """
    constraints: list[dict] = []
    activities: set[str] = set()
    if algorithm == "declare":
        # pm4py returns: {template_name: {(act_a, act_b): {"support": ..., ...}}}
        for template, pairs in (model or {}).items():
            for params, stats in (pairs or {}).items():
                if isinstance(params, tuple):
                    param_list = [list(params)]
                    for a in params:
                        activities.add(str(a))
                elif isinstance(params, str):
                    param_list = [[params]]
                    activities.add(params)
                else:
                    param_list = []
                constraints.append({
                    "template": template,
                    "parameters": param_list,
                    "support": (stats or {}).get("support") if isinstance(stats, dict) else None,
                    "confidence": (stats or {}).get("confidence") if isinstance(stats, dict) else None,
                })
    elif algorithm == "log_skeleton":
        # pm4py returns: {"equivalence": set[(a, b)], "always_after": ..., ...}
        for relation, pairs in (model or {}).items():
            if not isinstance(pairs, (set, list, tuple)):
                continue
            for pair in pairs:
                if isinstance(pair, tuple) and len(pair) == 2:
                    constraints.append({
                        "template": relation,
                        "parameters": [[str(pair[0])], [str(pair[1])]],
                    })
                    activities.add(str(pair[0]))
                    activities.add(str(pair[1]))
    n_constraints = len(constraints)
    n_activities = max(len(activities), 1)
    n_templates = len({c["template"] for c in constraints}) if constraints else 0
    return {
        "constraints": constraints,
        "activities": sorted(activities),
        "n_constraints": n_constraints,
        "n_activities": len(activities),
        "constraint_density": n_constraints / n_activities if n_constraints else 0.0,
        "constraint_variability": (n_templates / n_constraints) if n_constraints else None,
    }


def evaluate_log(
    log,
    *,
    algorithm: str = "heuristics",
    dependency_threshold: float = 0.5,
    and_threshold: float = 0.65,
    loop_two_threshold: float = 0.5,
    noise_threshold: float = 0.0,
    disable_fallthroughs: bool = False,
    ilp_alpha: float = 1.0,
    population_size: int = 500,
    generations: int = 100,
    crossover_rate: float = 1.0,
    mutation_rate: float = 0.01,
    min_support_ratio: Optional[float] = None,
    min_confidence_ratio: Optional[float] = None,
    conformance_method: str = "alignments",
) -> Dict[str, Any]:
    """Discover + evaluate one log, returning a result row.

    For Petri-net algorithms the row matches the imperative schema (slots into
    ``metric_proxies`` imperative path). For declarative algorithms
    (``declare`` / ``log_skeleton``) the row carries a flattened constraint
    summary in the ``metrics`` field so the declarative metric path picks up
    ``constraint_density``/``constraint_variability``. On discovery/eval
    failure the row is structurally complete with ``error`` set.
    """
    if algorithm in DECLARATIVE_ALGORITHMS:
        return _evaluate_declarative(
            log,
            algorithm=algorithm,
            min_support_ratio=min_support_ratio,
            min_confidence_ratio=min_confidence_ratio,
            noise_threshold=noise_threshold,
        )

    row: Dict[str, Any] = {
        "log_id": 0,
        "log_name": _infer_log_name(log, 0),
        "miner": f"pm4py_{algorithm}",
        "model_type": "petri_net",
        "algorithm": algorithm,
        "dependency_threshold": dependency_threshold,
        "and_threshold": and_threshold,
        "loop_two_threshold": loop_two_threshold,
        "noise_threshold": noise_threshold,
        "disable_fallthroughs": disable_fallthroughs,
        "ilp_alpha": ilp_alpha,
        "population_size": population_size,
        "generations": generations,
        "crossover_rate": crossover_rate,
        "mutation_rate": mutation_rate,
    }
    total_start = time.perf_counter()
    try:
        discovery_start = time.perf_counter()
        net, im, fm, process_tree = _discover(
            log,
            algorithm=algorithm,
            dependency_threshold=dependency_threshold,
            and_threshold=and_threshold,
            loop_two_threshold=loop_two_threshold,
            noise_threshold=noise_threshold,
            disable_fallthroughs=disable_fallthroughs,
            ilp_alpha=ilp_alpha,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
        )
        row["discovery_runtime_sec"] = time.perf_counter() - discovery_start

        # Tree-derived structural metrics: only the Inductive variant has a tree;
        # for the others these stay None (the UI treats them as "not available").
        if process_tree is not None:
            row.update(_extract_process_tree(process_tree))
        row.update(_extract_net_stats(net))
        row.update(_extract_soundness(net, im, fm))

        conf_start = time.perf_counter()
        row.update(
            _extract_fitness_precision(
                log=log, net=net, im=im, fm=fm, method=conformance_method
            )
        )
        row["conformance_runtime_sec"] = time.perf_counter() - conf_start
        row["total_runtime_sec"] = time.perf_counter() - total_start
        row["error"] = None
        row["_net"] = net  # transient handle for visualisation; stripped before caching
        row["_im"] = im
        row["_fm"] = fm
    except Exception as exc:  # noqa: BLE001 — surface as a result row, not a crash
        row["total_runtime_sec"] = time.perf_counter() - total_start
        row["error"] = str(exc)
    return row


def _evaluate_declarative(
    log,
    *,
    algorithm: str,
    min_support_ratio: Optional[float],
    min_confidence_ratio: Optional[float],
    noise_threshold: float,
) -> Dict[str, Any]:
    """Declare / Log-Skeleton evaluation — no Petri net, no replay.

    Promotes ``constraint_density`` / ``constraint_variability`` /
    ``n_constraints`` / ``n_activities`` onto the row's top level so the
    declarative metric proxy (``metric_proxies._fill_declarative``) picks them
    up without any additional plumbing.
    """
    row: Dict[str, Any] = {
        "log_id": 0,
        "log_name": _infer_log_name(log, 0),
        "miner": f"pm4py_{algorithm}",
        "model_type": "declarative",
        "algorithm": algorithm,
        "min_support_ratio": min_support_ratio,
        "min_confidence_ratio": min_confidence_ratio,
        "noise_threshold": noise_threshold,
    }
    total_start = time.perf_counter()
    try:
        discovery_start = time.perf_counter()
        summary = _discover_declarative(
            log,
            algorithm=algorithm,
            min_support_ratio=min_support_ratio,
            min_confidence_ratio=min_confidence_ratio,
            noise_threshold=noise_threshold,
        )
        row["discovery_runtime_sec"] = time.perf_counter() - discovery_start
        row["constraint_density"]      = summary["constraint_density"]
        row["constraint_variability"]  = summary["constraint_variability"]
        row["n_constraints"]           = summary["n_constraints"]
        row["n_activities"]            = summary["n_activities"]
        row["_declarative_summary"]    = summary
        row["total_runtime_sec"]       = time.perf_counter() - total_start
        row["error"] = None
    except Exception as exc:  # noqa: BLE001
        row["total_runtime_sec"] = time.perf_counter() - total_start
        row["error"] = str(exc)
    return row


def _collect_log_stats(log) -> Dict[str, int]:
    n_cases = len(log)
    n_events = sum(len(trace) for trace in log)
    activities = {
        event.get("concept:name")
        for trace in log
        for event in trace
        if event.get("concept:name") is not None
    }
    return {"n_cases": n_cases, "n_events": n_events, "n_activities": len(activities)}


def _safe_visualisation(net, im, fm, assets_dir: Path) -> Dict[str, Optional[str]]:
    """Render the Petri net PNG (+ PNML for downstream tools). Soft-fails."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Optional[str]] = {
        "petri_net_path": None,
        "petri_net_pnml_path": None,
        "model_error": None,
    }
    try:
        png = assets_dir / "petri_net.png"
        pm4py.save_vis_petri_net(net, im, fm, str(png))
        out["petri_net_path"] = str(png)
    except Exception as exc:  # noqa: BLE001
        out["model_error"] = f"Petri net visualization failed: {exc}"
    try:
        pnml = assets_dir / "model.pnml"
        pm4py.write_pnml(net, im, fm, str(pnml))
        out["petri_net_pnml_path"] = str(pnml)
    except Exception as exc:  # noqa: BLE001
        prev = out.get("model_error") or ""
        sep = "; " if prev else ""
        out["model_error"] = f"{prev}{sep}PNML export failed: {exc}"
    return out


def _make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(v) for v in value]
    return str(value)


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if isinstance(value, float) else str(value)
    return "-" if value is None else str(value)


def _build_markdown(
    *,
    run_id: str,
    date_str: str,
    bearbeiter: str,
    log_name: str,
    structuredness: str,
    log_path: Path,
    log_stats: Dict[str, int],
    algorithm: str,
    metrics: Dict[str, Any],
    petri_net_rel: Optional[str],
    pm4py_version: str,
    conformance_method: str,
) -> str:
    algo_label = ALGORITHM_LABELS.get(algorithm, algorithm)
    visual = (
        f"- Petri Net: ![Petri Net]({petri_net_rel})"
        if petri_net_rel
        else "- No visualization available."
    )
    return f"""# pm4py Miner Results Report

## 1. Run Metadata
- Run ID: {run_id}
- Date: {date_str}
- Author: {bearbeiter}
- Log name: {log_name}
- Structuredness class: {structuredness}

## 2. Input Log
- Number of cases: {log_stats['n_cases']}
- Number of events: {log_stats['n_events']}
- Number of activities: {log_stats['n_activities']}

## 3. Miner Setup
- Miner: {algo_label} (pm4py)
- Tool: PM4Py {pm4py_version}
- Output format: Petri Net (PNML + PNG)
- Conformance: {conformance_method}

## 4. Structural Metrics
| Fitness | Precision | F1 | #Places | #Transitions | #Silent | #Arcs | WF-net | Sound |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| {_fmt(metrics.get('fitness_primary'))} | {_fmt(metrics.get('precision'))} | {_fmt(metrics.get('f1'))} | {_fmt(metrics.get('n_places'), 0)} | {_fmt(metrics.get('n_transitions'), 0)} | {_fmt(metrics.get('n_silent_transitions'), 0)} | {_fmt(metrics.get('n_arcs'), 0)} | {_fmt(metrics.get('is_wf_net'))} | {_fmt(metrics.get('is_sound'))} |

## 5. Visualization
{visual}
"""


def generate_report(
    *,
    log_path: Path,
    output_root: Path,
    run_id: Optional[str],
    bearbeiter: Optional[str],
    algorithm: str = "heuristics",
    dependency_threshold: float = 0.5,
    and_threshold: float = 0.65,
    loop_two_threshold: float = 0.5,
    noise_threshold: float = 0.0,
    disable_fallthroughs: bool = False,
    ilp_alpha: float = 1.0,
    population_size: int = 500,
    generations: int = 100,
    crossover_rate: float = 1.0,
    mutation_rate: float = 0.01,
    min_support_ratio: Optional[float] = None,
    min_confidence_ratio: Optional[float] = None,
    conformance_method: str = "alignments",
    preprocessing_note: str = "",
    export_pdf: bool = False,
) -> Dict[str, Any]:
    """Run the full pm4py evaluation and write a report bundle.

    Mirrors ``imperative_miner.pilot_sheet.generate_pilot_sheet`` (slimmer):
    returns ``output_dir``, ``markdown_path``, ``data_path``, ``petri_net_path``,
    ``pdf_path`` and the metric ``row`` (imperative schema, ``_net``/``_im``/``_fm``
    stripped).
    """
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    log = xes_importer.apply(str(log_path))
    log_name = log_path.stem
    set_log_name(log, log_name)

    run_id_val = run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bearbeiter_val = bearbeiter or getpass.getuser()
    date_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    structuredness = infer_experiment_class(log_name, default="custom")

    out_dir = build_report_output_dir(output_root, log_name, f"pm4py_{algorithm}")
    assets_dir = out_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    log_stats = _collect_log_stats(log)
    row = evaluate_log(
        log,
        algorithm=algorithm,
        dependency_threshold=dependency_threshold,
        and_threshold=and_threshold,
        loop_two_threshold=loop_two_threshold,
        noise_threshold=noise_threshold,
        disable_fallthroughs=disable_fallthroughs,
        ilp_alpha=ilp_alpha,
        population_size=population_size,
        generations=generations,
        crossover_rate=crossover_rate,
        mutation_rate=mutation_rate,
        min_support_ratio=min_support_ratio,
        min_confidence_ratio=min_confidence_ratio,
        conformance_method=conformance_method,
    )

    net, im, fm = row.pop("_net", None), row.pop("_im", None), row.pop("_fm", None)
    visuals = (
        _safe_visualisation(net, im, fm, assets_dir)
        if net is not None
        else {"petri_net_path": None, "petri_net_pnml_path": None,
              "model_error": row.get("error")}
    )

    # Declarative branch: persist the constraint payload alongside the report
    # so the result-cache picks it up and the metric proxies have a stable
    # JSON anchor.
    declarative_payload = row.pop("_declarative_summary", None)
    declarative_json_path: Optional[Path] = None
    if declarative_payload is not None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        declarative_json_path = assets_dir / "declare_model.json"
        declarative_json_path.write_text(
            json.dumps(_make_json_safe(declarative_payload), indent=2,
                       ensure_ascii=False),
            encoding="utf-8",
        )

    petri_net_path = visuals.get("petri_net_path")
    try:
        petri_net_rel = (
            str(Path(petri_net_path).relative_to(out_dir)) if petri_net_path else None
        )
    except ValueError:
        petri_net_rel = petri_net_path

    markdown = _build_markdown(
        run_id=run_id_val,
        date_str=date_str,
        bearbeiter=bearbeiter_val,
        log_name=log_name,
        structuredness=structuredness,
        log_path=log_path,
        log_stats=log_stats,
        algorithm=algorithm,
        metrics=row,
        petri_net_rel=petri_net_rel,
        pm4py_version=pm4py.__version__,
        conformance_method=conformance_method,
    )
    markdown_path = out_dir / "ergebnisbericht.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    data_path = out_dir / "result_data.json"
    data_payload = {
        "run_id": run_id_val,
        "generated_at": date_str,
        "bearbeiter": bearbeiter_val,
        "log_name": log_name,
        "log_path": str(log_path),
        "structuredness_class": structuredness,
        "log_stats": log_stats,
        "parameters": {
            "algorithm": algorithm,
            "dependency_threshold": dependency_threshold,
            "and_threshold": and_threshold,
            "loop_two_threshold": loop_two_threshold,
            "noise_threshold": noise_threshold,
            "disable_fallthroughs": disable_fallthroughs,
            "ilp_alpha": ilp_alpha,
            "population_size": population_size,
            "generations": generations,
            "crossover_rate": crossover_rate,
            "mutation_rate": mutation_rate,
            "min_support_ratio": min_support_ratio,
            "min_confidence_ratio": min_confidence_ratio,
            "conformance_method": conformance_method,
            "preprocessing_note": preprocessing_note,
            "pm4py_version": pm4py.__version__,
        },
        "metrics": row,
        "artifacts": {
            "markdown_path": str(markdown_path),
            "petri_net_path": petri_net_path,
            "petri_net_pnml_path": visuals.get("petri_net_pnml_path"),
            "declarative_model_path": str(declarative_json_path)
                if declarative_json_path else None,
        },
    }
    data_path.write_text(
        json.dumps(_make_json_safe(data_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pdf_path = _safe_pdf_export(markdown_path) if export_pdf else None

    return {
        "output_dir": out_dir,
        "markdown_path": markdown_path,
        "data_path": data_path,
        "pdf_path": pdf_path,
        "petri_net_path": petri_net_path,
        "petri_net_pnml_path": visuals.get("petri_net_pnml_path"),
        "declarative_model_path": str(declarative_json_path)
            if declarative_json_path else None,
        "model_error": visuals.get("model_error"),
        "log_stats": log_stats,
        "row": row,
    }
