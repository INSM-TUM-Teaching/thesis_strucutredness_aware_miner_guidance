from __future__ import annotations

"""
Evaluation helpers for imperative process discovery with PM4Py.

This module is designed for a thesis-style workflow:
- discover an imperative model with the Inductive Miner
- convert the discovered process tree into a Petri net
- derive quantitative evaluation metrics from the event log
- build a compact reporting table for later comparison across logs

The implementation intentionally separates:
- raw result extraction for reproducibility
- compact report generation for presentation and CSV export
- open qualitative placeholders for manual coding afterwards
"""

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pm4py
from pm4py.algo.evaluation.simplicity import algorithm as simplicity_evaluator

from flex_compare.internal.shared.complexity_metrics import compute_cfc
from flex_compare.internal.shared.formatting import fmt_bool_yes_no, round_if_number


REPORT_COLUMNS = [
    "Log",
    "Miner",
    "Fitness",
    "Precision",
    "F1",
    "Generalization",
    "Simplicity",
    "#Places",
    "#Transitions",
    "#Silent",
    "#Arcs",
    "WF-net",
    "Sound",
    "Discovery (s)",
    "Conformance (s)",
    "Total (s)",
    "Readability",
    "Structural fidelity",
]


def _round_if_number(value: Any, digits: int = 3) -> Any:
    return round_if_number(value, digits)


def _format_bool_for_report(value: Any) -> str:
    return fmt_bool_yes_no(value).capitalize()


def _format_rating_for_report(rating: Any, note: Any) -> str:
    """
    Merge an optional manual rating and an optional note into one compact cell.

    The qualitative fields intentionally stay open in the raw result so they can
    later be filled in manually during thesis coding and interpretation.
    """
    if rating is None and not note:
        return ""
    if note:
        return f"{rating} ({note})" if rating is not None else str(note)
    return str(rating)


def set_log_name(log: Any, name: str) -> None:
    """
    Assign a stable log name across PM4Py object types.

    PM4Py imports can yield different in-memory objects depending on the import
    path and version. In the current project setup we mainly use `EventLog`
    objects from `xes_importer.apply(...)`, but the helper also supports objects
    that expose pandas-like `.attrs`.
    """
    attributes = getattr(log, "attributes", None)
    if isinstance(attributes, dict):
        attributes["concept:name"] = name
        return

    attrs = getattr(log, "attrs", None)
    if isinstance(attrs, dict):
        attrs["concept:name"] = name


def _infer_log_name(log: Any, idx: int) -> str:
    """
    Recover a descriptive log label from PM4Py metadata or fall back to an index.
    """
    attributes = getattr(log, "attributes", None)
    if isinstance(attributes, dict):
        for key in ("concept:name", "name"):
            value = attributes.get(key)
            if value:
                return str(value)

    attrs = getattr(log, "attrs", None)
    if isinstance(attrs, dict):
        for key in ("concept:name", "name"):
            value = attrs.get(key)
            if value:
                return str(value)

    return f"log_{idx:02d}"


def _count_silent_transitions(net) -> int:
    """Count invisible transitions, i.e. transitions without a visible label."""
    return sum(1 for transition in net.transitions if transition.label is None)


def _extract_net_stats(net) -> Dict[str, Any]:
    """Collect simple structural size metrics for the discovered Petri net.

    Also computes the PM4Py arc-degree simplicity heuristic (Blum 2015 /
    Mendling 2008), wrapped in try/except for API robustness across PM4Py
    versions — same defensive pattern as `generalization_tbr` in
    `_extract_fitness_precision`.
    """
    stats: Dict[str, Any] = {
        "n_places": len(net.places),
        "n_transitions": len(net.transitions),
        "n_silent_transitions": _count_silent_transitions(net),
        "n_arcs": len(net.arcs),
        "cfc": compute_cfc(net),
        "simplicity": None,
        "simplicity_method": None,
        "simplicity_unavailable_reason": None,
    }
    try:
        stats["simplicity"] = simplicity_evaluator.apply(
            net,
            variant=simplicity_evaluator.Variants.SIMPLICITY_ARC_DEGREE,
        )
        stats["simplicity_method"] = "simplicity_arc_degree_pm4py"
    except AttributeError as exc:
        stats["simplicity_unavailable_reason"] = (
            f"pm4py simplicity arc-degree variant not available "
            f"in PM4Py {getattr(pm4py, '__version__', '?')}: {exc}"
        )
    except Exception as exc:
        stats["simplicity_unavailable_reason"] = f"{type(exc).__name__}: {exc}"
    return stats


def _serialize_process_tree_node(node) -> Dict[str, Any]:
    """Recursively serialize a PM4Py ProcessTree node into a plain dict.

    Leaves carry their visible activity ``label`` (``None`` marks a silent/tau
    leaf); inner nodes carry the control-flow ``operator`` as both its symbol
    (e.g. ``->``, ``X``, ``+``, ``*``) and its enum name (e.g. ``SEQUENCE``).
    """
    operator = getattr(node, "operator", None)
    children = getattr(node, "children", None) or []
    serialized: Dict[str, Any] = {
        "operator": getattr(operator, "value", None) if operator is not None else None,
        "operator_name": getattr(operator, "name", None) if operator is not None else None,
        "label": getattr(node, "label", None),
        "children": [_serialize_process_tree_node(child) for child in children],
    }
    return serialized


def _extract_process_tree(process_tree) -> Dict[str, Any]:
    """Serialize the discovered process tree so the operator structure survives
    in the result JSON instead of living only in the rendered PNG.

    Without this, structural criteria that need the operator tree — top-level
    structure (root / depth-1-2 operators), correspondence to ARM relations,
    and the operator mix behind simplicity — would be blocked for the
    imperative miner, because reading the PNG visually is disallowed.

    Wrapped in try/except for robustness across PM4Py versions, mirroring the
    defensive pattern used in `_extract_net_stats`.
    """
    info: Dict[str, Any] = {
        "process_tree_string": None,
        "process_tree_structure": None,
        "process_tree_root_operator": None,
        "process_tree_operator_counts": None,
        "process_tree_depth": None,
        "process_tree_n_leaves": None,
        "process_tree_n_tau_leaves": None,
        "process_tree_unavailable_reason": None,
    }
    try:
        structure = _serialize_process_tree_node(process_tree)
        info["process_tree_structure"] = structure
        info["process_tree_string"] = str(process_tree)
        info["process_tree_root_operator"] = structure["operator"]

        operator_counts: Dict[str, int] = {}
        n_leaves = 0
        n_tau_leaves = 0

        def _walk(node: Dict[str, Any], depth: int) -> int:
            nonlocal n_leaves, n_tau_leaves
            op_name = node.get("operator_name")
            if op_name is not None:
                operator_counts[op_name] = operator_counts.get(op_name, 0) + 1
            children = node.get("children") or []
            if not children:
                n_leaves += 1
                if node.get("label") is None:
                    n_tau_leaves += 1
                return depth
            return max(_walk(child, depth + 1) for child in children)

        info["process_tree_depth"] = _walk(structure, 0)
        info["process_tree_operator_counts"] = operator_counts
        info["process_tree_n_leaves"] = n_leaves
        info["process_tree_n_tau_leaves"] = n_tau_leaves
    except Exception as exc:
        info["process_tree_unavailable_reason"] = f"{type(exc).__name__}: {exc}"
    return info


def _extract_fitness_precision(
    log,
    net,
    im,
    fm,
    method: str = "alignments",
) -> Dict[str, Any]:
    """
    Compute conformance metrics for one discovered model.

    The function keeps the raw PM4Py fitness output in `fitness_raw` and also
    derives thesis-friendly scalar metrics:
    - `fitness_primary`: preferred scalar fitness value for comparisons
    - `precision`
    - `f1`: harmonic mean of `fitness_primary` and `precision`
    """
    if method == "alignments":
        fitness_raw = pm4py.conformance.fitness_alignments(log, net, im, fm)
        precision_value = pm4py.conformance.precision_alignments(log, net, im, fm)
    elif method == "token_replay":
        fitness_raw = pm4py.conformance.fitness_token_based_replay(log, net, im, fm)
        precision_value = pm4py.conformance.precision_token_based_replay(log, net, im, fm)
    else:
        raise ValueError("method must be 'alignments' or 'token_replay'")

    avg_fitness = fitness_raw.get("average_trace_fitness")
    perc_fit = (
        fitness_raw.get("percentage_of_fitting_traces")
        if "percentage_of_fitting_traces" in fitness_raw
        else fitness_raw.get("perc_fit_traces")
    )
    log_fitness = fitness_raw.get("log_fitness")

    # Use average trace fitness as the main comparison metric whenever it is
    # available, because it is easier to interpret consistently across logs.
    primary_fitness = avg_fitness if avg_fitness is not None else log_fitness

    f1 = None
    if primary_fitness is not None and precision_value is not None:
        denom = primary_fitness + precision_value
        f1 = (2 * primary_fitness * precision_value / denom) if denom > 0 else None

    # Phase C: heuristic generalization (van der Aalst, Adriansyah, van Dongen 2012,
    # WIREs DMKD 2(2)). PM4Py exposes only the token-based variant
    # (`generalization_tbr`); same heuristic family as the Fusion side's
    # AlignmentPrecGen-Generalization, so methodologically commensurable.
    # Wrapped in try/except for API robustness across PM4Py versions.
    generalization_value: Optional[float] = None
    generalization_method: Optional[str] = None
    generalization_unavailable_reason: Optional[str] = None
    try:
        generalization_value = pm4py.conformance.generalization_tbr(log, net, im, fm)
        generalization_method = "generalization_tbr_pm4py"
    except AttributeError as exc:
        generalization_unavailable_reason = (
            f"pm4py.conformance.generalization_tbr not available "
            f"in PM4Py {getattr(pm4py, '__version__', '?')}: {exc}"
        )
    except Exception as exc:
        generalization_unavailable_reason = f"{type(exc).__name__}: {exc}"

    return {
        "fitness_raw": fitness_raw,
        "fitness_primary": primary_fitness,
        "fitness_average_trace": avg_fitness,
        "fitness_percentage_fitting_traces": perc_fit,
        "fitness_log": log_fitness,
        "precision": precision_value,
        "f1": f1,
        "generalization": generalization_value,
        "generalization_method": generalization_method,
        "generalization_unavailable_reason": generalization_unavailable_reason,
        "conformance_method": method,
    }


def _extract_soundness(net, im, fm) -> Dict[str, Any]:
    """
    Check workflow-net status and soundness in a PM4Py-version-robust way.

    Important compatibility detail:
    - some PM4Py versions return `bool`
    - others return `(bool, diagnostics)`

    The raw return value is preserved in `soundness_raw` for transparency.
    """
    is_wf_net = pm4py.analysis.check_is_workflow_net(net)

    soundness_raw = None
    soundness_diagnostics = None
    soundness_error = None
    is_sound = None

    if is_wf_net:
        try:
            soundness_raw = pm4py.analysis.check_soundness(net, im, fm)

            if isinstance(soundness_raw, tuple):
                is_sound = soundness_raw[0]
                soundness_diagnostics = soundness_raw[1] if len(soundness_raw) > 1 else None
            elif isinstance(soundness_raw, bool):
                is_sound = soundness_raw
            else:
                # Defensive fallback: preserve the unexpected return and avoid
                # silently misclassifying the model as sound or unsound.
                is_sound = None
                soundness_diagnostics = {
                    "unexpected_return_type": type(soundness_raw).__name__
                }
        except Exception as exc:
            soundness_error = str(exc)

    if is_wf_net and is_sound is True:
        soundness_status = "sound"
    elif is_wf_net and is_sound is False:
        soundness_status = "not_sound"
    else:
        soundness_status = "not_checkable_as_sound_wf_net"

    return {
        "is_wf_net": is_wf_net,
        "is_sound": is_sound,
        "soundness_status": soundness_status,
        "soundness_raw": soundness_raw,
        "soundness_diagnostics": soundness_diagnostics,
        "soundness_error": soundness_error,
    }


def _build_error_result(
    *,
    log: Any,
    idx: int,
    miner: str,
    conformance_method: str,
    error: Exception,
    noise_threshold: float = 0.0,
) -> Dict[str, Any]:
    """
    Return a structurally complete result row even when evaluation fails.

    This makes later aggregation easier because downstream code can rely on a
    stable schema for both successful and failed runs.
    """
    return {
        "log_id": idx,
        "log_name": _infer_log_name(log, idx),
        "miner": miner,
        "model_type": "petri_net_from_process_tree",
        "conformance_method": conformance_method,
        "noise_threshold": noise_threshold,
        "fitness_primary": None,
        "fitness_average_trace": None,
        "fitness_percentage_fitting_traces": None,
        "fitness_log": None,
        "precision": None,
        "f1": None,
        "generalization": None,
        "generalization_method": None,
        "generalization_unavailable_reason": None,
        "n_places": None,
        "n_transitions": None,
        "n_silent_transitions": None,
        "n_arcs": None,
        "cfc": None,
        "simplicity": None,
        "simplicity_method": None,
        "simplicity_unavailable_reason": None,
        "process_tree_string": None,
        "process_tree_structure": None,
        "process_tree_root_operator": None,
        "process_tree_operator_counts": None,
        "process_tree_depth": None,
        "process_tree_n_leaves": None,
        "process_tree_n_tau_leaves": None,
        "process_tree_unavailable_reason": None,
        "discovery_runtime_sec": None,
        "conformance_runtime_sec": None,
        "total_runtime_sec": None,
        "is_wf_net": None,
        "is_sound": None,
        "soundness_status": "not_checkable_as_sound_wf_net",
        "soundness_raw": None,
        "soundness_diagnostics": None,
        "soundness_error": None,
        "fitness_raw": None,
        "readability_rating": None,
        "readability_note": None,
        "structural_fidelity_rating": None,
        "structural_fidelity_note": None,
        "error": str(error),
    }


def mine_process_models(
    logs: List,
    conformance_method: str = "alignments",
    noise_threshold: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Discover one Petri-net model per event log and derive evaluation metrics.

    Workflow for each log:
    1. discover a process tree with the Inductive Miner
    2. convert the tree into a Petri net
    3. collect structural metrics
    4. assess workflow-net status and soundness
    5. compute fitness, precision, and F1
    6. keep qualitative fields open for later manual assessment
    """
    results: List[Dict[str, Any]] = []

    for idx, log in enumerate(logs):
        row: Dict[str, Any] = {
            "log_id": idx,
            "log_name": _infer_log_name(log, idx),
            "miner": "inductive_miner",
            "model_type": "petri_net_from_process_tree",
            "noise_threshold": noise_threshold,
        }

        total_start = time.perf_counter()

        try:
            discovery_start = time.perf_counter()
            process_tree = pm4py.discovery.discover_process_tree_inductive(
                log, noise_threshold=noise_threshold,
            )
            net, im, fm = pm4py.convert.convert_to_petri_net(process_tree)
            discovery_end = time.perf_counter()

            row["discovery_runtime_sec"] = discovery_end - discovery_start
            row.update(_extract_process_tree(process_tree))
            row.update(_extract_net_stats(net))
            row.update(_extract_soundness(net, im, fm))

            conformance_start = time.perf_counter()
            row.update(
                _extract_fitness_precision(
                    log=log,
                    net=net,
                    im=im,
                    fm=fm,
                    method=conformance_method,
                )
            )
            conformance_end = time.perf_counter()

            row["conformance_runtime_sec"] = conformance_end - conformance_start
            row["total_runtime_sec"] = time.perf_counter() - total_start

            # These fields are kept intentionally empty because they require a
            # qualitative judgment rather than an automated PM4Py computation.
            row["readability_rating"] = None
            row["readability_note"] = None
            row["structural_fidelity_rating"] = None
            row["structural_fidelity_note"] = None
            row["error"] = None
            results.append(row)
        except Exception as exc:
            results.append(
                _build_error_result(
                    log=log,
                    idx=idx,
                    miner="inductive_miner",
                    conformance_method=conformance_method,
                    error=exc,
                    noise_threshold=noise_threshold,
                )
            )

    return results


def make_report_row(result: Dict[str, Any], digits: int = 3) -> Dict[str, Any]:
    """
    Create one compact, presentation-friendly report row from a raw result.

    The report deliberately focuses on the most interpretable comparison fields
    and rounds floating-point values to keep exported tables readable.
    """
    return {
        "Log": result.get("log_name", result.get("log_id")),
        "Miner": result.get("miner"),
        "Fitness": _round_if_number(result.get("fitness_primary"), digits),
        "Precision": _round_if_number(result.get("precision"), digits),
        "F1": _round_if_number(result.get("f1"), digits),
        "Generalization": _round_if_number(result.get("generalization"), digits),
        "Simplicity": _round_if_number(result.get("simplicity"), digits),
        "#Places": result.get("n_places"),
        "#Transitions": result.get("n_transitions"),
        "#Silent": result.get("n_silent_transitions"),
        "#Arcs": result.get("n_arcs"),
        "WF-net": _format_bool_for_report(result.get("is_wf_net")),
        "Sound": _format_bool_for_report(result.get("is_sound")),
        "Discovery (s)": _round_if_number(result.get("discovery_runtime_sec"), digits),
        "Conformance (s)": _round_if_number(result.get("conformance_runtime_sec"), digits),
        "Total (s)": _round_if_number(result.get("total_runtime_sec"), digits),
        "Readability": _format_rating_for_report(
            result.get("readability_rating"),
            result.get("readability_note"),
        ),
        "Structural fidelity": _format_rating_for_report(
            result.get("structural_fidelity_rating"),
            result.get("structural_fidelity_note"),
        ),
    }


def make_report_rows(
    results: Iterable[Dict[str, Any]],
    digits: int = 3,
) -> List[Dict[str, Any]]:
    """Create compact report rows for multiple raw evaluation results."""
    return [make_report_row(result, digits=digits) for result in results]


def make_report_dataframe(results: Iterable[Dict[str, Any]], digits: int = 3):
    """
    Convert raw evaluation results into a compact pandas DataFrame.

    This function is the main bridge between the raw result schema and notebook
    presentation or CSV export.
    """
    import pandas as pd

    rows = make_report_rows(results, digits=digits)
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def run_example() -> None:
    """
    Execute a minimal end-to-end example on one local XES log.

    The example mirrors the recommended notebook workflow and writes a compact
    CSV report into the project root.
    """
    from pm4py.objects.log.importer.xes import importer as xes_importer

    project_root = Path(__file__).resolve().parent.parent.parent
    log_path = project_root / "data" / "original" / "Log01_structured.xes"
    output_csv = project_root / "imperative_miner_report.csv"

    log = xes_importer.apply(str(log_path))
    set_log_name(log, log_path.stem)

    results = mine_process_models([log], conformance_method="alignments")
    compact_df = make_report_dataframe(results, digits=3)

    print(compact_df.to_string(index=False))
    compact_df.to_csv(output_csv, index=False)
    print(f"\nSaved compact report to: {output_csv}")


if __name__ == "__main__":
    run_example()
