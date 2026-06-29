"""Paradigm-agnostic flat metric extraction for cached miner results.

Lifted out of ``comparison_app.app`` so UI modules (e.g. the validation page)
can resolve proxy metrics without importing ``app.py`` and pulling Flask, Dash,
and the full callback graph into a circular path.

This module also exposes :func:`extract_metrics_by_paradigm` for the new
``flex_compare`` app: callers pass a registered paradigm
(``"imperativ"``/``"deklarativ"``/``"hybrid"``) instead of one of the four
legacy miner ids. A ``source="imported"`` switch additionally marks the
structural metrics that an externally-imported model cannot provide as
``None`` and records ``_imported=True`` so the UI can render an explicit
"n/a — imported model" pill instead of empty cells.
"""
from __future__ import annotations

from typing import Literal


MetricSource = Literal["native", "imported"]


def _first_present(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _ratio(num, den):
    """Safe num/den; None if either is missing or den is 0."""
    if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
        return num / den
    return None


# ── Process-tree derived structural metrics (pure, read-time) ────────────────

def _tree_leaf_labels(node: dict) -> list:
    """All non-tau leaf labels under a process-tree node."""
    if not isinstance(node, dict):
        return []
    children = node.get("children") or []
    if not children:
        label = node.get("label")
        return [label] if label is not None else []
    out: list = []
    for child in children:
        out.extend(_tree_leaf_labels(child))
    return out


def _imposes_no_order(node: dict) -> bool:
    """True if the node enforces no ordering: a single leaf (activity or tau) or
    an exclusive choice (``X``) of such — the building blocks of a flower body."""
    if not isinstance(node, dict):
        return False
    children = node.get("children") or []
    if not children:
        return True  # leaf (activity or tau): no internal order
    if node.get("operator") == "X":
        return all(_imposes_no_order(c) for c in children)
    return False  # ->, +, *, O with children impose structure


def _flower_activities(node: dict, acc: set) -> None:
    """Collect activities sitting inside a flower loop.

    A flower loop is a ``*`` whose every child imposes no order (tau / leaf /
    XOR-of-leaves) and which spans >= 2 activities — i.e. it permits those
    activities in any order, any number of times (the degenerate flower).
    Matches IM's ``*(tau, a, b, …)`` and ``*(X(a,…), tau)`` shapes alike.
    """
    if not isinstance(node, dict):
        return
    children = node.get("children") or []
    if (node.get("operator") == "*" and children
            and all(_imposes_no_order(c) for c in children)):
        acts = _tree_leaf_labels(node)
        if len(set(acts)) >= 2:
            acc.update(acts)
            return  # whole loop is a flower; don't recurse into it
    for child in children:
        _flower_activities(child, acc)


def _imp_flower(metrics: dict) -> tuple:
    """Return ``(flower_detected, flower_fragment_ratio)`` from the process tree.

    ``flower_fragment_ratio`` = activities inside flower loops / all activities;
    ``flower_detected`` = a majority (> 0.5) of activities sit in flowers.
    Both ``None`` when no process-tree structure is available.
    """
    tree = (metrics or {}).get("process_tree_structure")
    if not isinstance(tree, dict):
        return None, None
    all_acts = set(_tree_leaf_labels(tree))
    if not all_acts:
        return None, None
    flower_acts: set = set()
    _flower_activities(tree, flower_acts)
    ratio = len(flower_acts) / len(all_acts)
    return (ratio > 0.5), ratio


# ── Metric keys an imported model cannot derive ──────────────────────────────
# Structural metrics computed from the *process-tree* or from discovery-internal
# counts (silent transitions, operator counts) are unrecoverable from an imported
# PNML/Declare-JSON model alone. flex_compare's custom-exec path marks them as
# ``None`` with an ``_imported=True`` companion flag so the UI can render an
# explicit "n/a — imported model" chip.
_IMPORT_UNRECOVERABLE: tuple[str, ...] = (
    "process_tree_depth",
    "mean_fan_out",
    "extended_cardoso_cfc",
    "tau_ratio",
    "flower_detected",
    "flower_fragment_ratio",
)


def _empty_result_skeleton() -> dict[str, object]:
    """All flat metric keys flex_compare and comparison_app rely on, initialised to None."""
    return {
        # BQ
        "replay_fitness": None,
        "etc_precision": None,
        "non_vacuous_satisfaction_rate": None,
        "vacuity_rate": None,
        # IN-1
        "process_tree_depth": None,
        "mean_fan_out": None,
        # IN-3 (imperative side)
        "extended_cardoso_cfc": None,
        "tau_ratio": None,
        # IN-3 (constraint side)
        "constraint_density": None,
        "constraint_variability": None,
        # SF-2
        "flower_detected": None,
        "flower_fragment_ratio": None,
        # SF-2 — ARM-coverage evidence (dominant relations). Declared here so the
        # UI can look the keys up; the actual values are resolved out-of-band by
        # the cached arm_coverage_proxies resolver and merged in at call sites
        # where log_path is known. This function stays subprocess-free.
        "arm_native_ratio": None,
        "arm_forced_ratio": None,
        "arm_missing_ratio": None,
        "arm_coverage_score": None,
        "arm_dominant_n": None,
        "arm_suggested_category": None,
        # SF-4
        "soundness_passed": None,
        "constraint_consistency": None,
    }


def _fill_imperative(out: dict, result: dict) -> None:
    m = result.get("metrics") or {}
    out["replay_fitness"] = _first_present(m, "replay_fitness", "fitness_primary", "fitness")
    out["etc_precision"] = _first_present(m, "etc_precision", "precision")
    out["process_tree_depth"] = _first_present(m, "process_tree_depth", "tree_depth")
    out["mean_fan_out"] = _first_present(m, "mean_fan_out", "fan_out_mean")
    out["extended_cardoso_cfc"] = _first_present(m, "extended_cardoso_cfc", "cfc")
    # tau_ratio: fraction of silent transitions in the Petri net; fall back to
    # the tree's tau-leaf share. Derived here from tool-emitted counts.
    out["tau_ratio"] = _first_present(m, "tau_ratio")
    if out["tau_ratio"] is None:
        out["tau_ratio"] = _ratio(m.get("n_silent_transitions"), m.get("n_transitions"))
    if out["tau_ratio"] is None:
        out["tau_ratio"] = _ratio(m.get("process_tree_n_tau_leaves"),
                                  m.get("process_tree_n_leaves"))
    # mean_fan_out: mean children per internal node = (nodes-1)/n_internal,
    # with n_internal = sum of operator counts, nodes = n_internal + n_leaves.
    out["mean_fan_out"] = _first_present(m, "mean_fan_out", "fan_out_mean")
    if out["mean_fan_out"] is None:
        op_counts = m.get("process_tree_operator_counts") or {}
        n_internal = sum(v for v in op_counts.values() if isinstance(v, int))
        n_leaves = m.get("process_tree_n_leaves")
        if n_internal and isinstance(n_leaves, int):
            out["mean_fan_out"] = (n_internal + n_leaves - 1) / n_internal
    # flower_detected / flower_fragment_ratio: computed from the process tree.
    flower_detected, flower_ratio = _imp_flower(m)
    out["flower_detected"] = _first_present(m, "flower_detected")
    if out["flower_detected"] is None:
        out["flower_detected"] = flower_detected
    out["flower_fragment_ratio"] = _first_present(m, "flower_fragment_ratio")
    if out["flower_fragment_ratio"] is None:
        out["flower_fragment_ratio"] = flower_ratio
    out["soundness_passed"] = _first_present(m, "soundness_passed", "is_sound", "sound")


def _fill_declarative(out: dict, result: dict) -> None:
    m = result.get("metrics") or {}
    out["replay_fitness"] = _first_present(
        m, "replay_fitness", "fitness_constraint_aware", "fitness_binary", "fitness"
    )
    out["non_vacuous_satisfaction_rate"] = _first_present(m, "non_vacuous_satisfaction_rate")
    out["vacuity_rate"] = _first_present(m, "vacuity_rate")
    out["constraint_density"] = _first_present(m, "constraint_density")
    out["constraint_variability"] = _first_present(m, "constraint_variability")
    out["flower_detected"] = _first_present(m, "flower_detected")
    out["flower_fragment_ratio"] = _first_present(m, "flower_fragment_ratio")
    out["constraint_consistency"] = _first_present(m, "constraint_consistency")


def _fill_hybrid(out: dict, result: dict) -> None:
    run_data = result.get("run_data") or {}
    m = run_data.get("metrics") or {}
    q = m.get("quality_metrics") or {}

    out["replay_fitness"] = _first_present(q, "replay_fitness", "mpcc_fitness", "fitness") \
        or _first_present(m, "replay_fitness", "mpcc_fitness")
    out["etc_precision"] = _first_present(q, "etc_precision", "precision") \
        or _first_present(m, "etc_precision")
    out["process_tree_depth"] = _first_present(m, "process_tree_depth") \
        or _first_present(q, "process_tree_depth")
    out["mean_fan_out"] = _first_present(m, "mean_fan_out") or _first_present(q, "mean_fan_out")
    out["extended_cardoso_cfc"] = _first_present(m, "extended_cardoso_cfc", "cfc") \
        or _first_present(q, "extended_cardoso_cfc", "cfc")
    out["tau_ratio"] = _first_present(m, "tau_ratio") or _first_present(q, "tau_ratio")
    if out["tau_ratio"] is None:
        out["tau_ratio"] = _ratio(m.get("tau_transition_count"),
                                  m.get("pnwa_transition_count"))
    out["constraint_density"] = _first_present(m, "constraint_density") \
        or _first_present(q, "constraint_density")
    if out["constraint_density"] is None:
        # analog to decl: declarative constraints per activity (procedural node)
        out["constraint_density"] = _ratio(m.get("declarative_constraint_count"),
                                            m.get("procedural_node_count"))
    out["constraint_variability"] = _first_present(m, "constraint_variability") \
        or _first_present(q, "constraint_variability")
    out["flower_detected"] = _first_present(m, "flower_detected") \
        or _first_present(q, "flower_detected")
    out["flower_fragment_ratio"] = _first_present(m, "flower_fragment_ratio") \
        or _first_present(q, "flower_fragment_ratio")
    out["soundness_passed"] = _first_present(q, "soundness_passed", "is_sound") \
        or _first_present(m, "soundness_passed", "is_sound")
    out["constraint_consistency"] = _first_present(m, "constraint_consistency") \
        or _first_present(q, "constraint_consistency")


def extract_metrics_by_paradigm(
    paradigm: str,
    result: dict,
    source: MetricSource = "native",
) -> dict[str, object]:
    """Flat metric extraction keyed by paradigm.

    Parameters
    ----------
    paradigm
        One of ``"imperativ"``, ``"deklarativ"``, ``"hybrid"`` (registry
        spelling, German). Unknown paradigms return an all-``None`` skeleton.
    result
        The miner's result dict (already rehydrated from cache or fresh).
    source
        ``"native"`` (default) for outputs of a real discovery run;
        ``"imported"`` for results assembled from a PNML/Declare-JSON file by
        the flex_compare custom-exec path. ``"imported"`` forces every
        structural metric an imported model cannot derive to ``None`` and adds
        ``_imported=True`` to the returned dict — the UI surfaces that as a
        distinct "n/a — imported model" chip.
    """
    out = _empty_result_skeleton()
    if paradigm == "imperativ":
        _fill_imperative(out, result)
    elif paradigm == "deklarativ":
        _fill_declarative(out, result)
    elif paradigm == "hybrid":
        _fill_hybrid(out, result)
    # else: unknown paradigm → leave the skeleton (all None) in place.

    if source == "imported":
        for key in _IMPORT_UNRECOVERABLE:
            out[key] = None
        out["_imported"] = True
    return out


def _extract_item_metrics(miner: str, result: dict) -> dict[str, object]:
    """Flatten item metrics into a flat per-miner dict (None where missing).

    Legacy comparison_app API. Internally dispatches via paradigm so the two
    apps share one extraction implementation.
    """
    if miner in ("imp", "pm4"):
        paradigm = "imperativ"
    elif miner == "decl":
        paradigm = "deklarativ"
    elif miner == "fus":
        paradigm = "hybrid"
    else:
        # Foreign id (e.g. flex_compare slot) — look up via registry.
        from flex_compare.internal.shared.registry import miner_registry  # local to avoid cycle

        type_id = miner.split("__", 1)[0]
        spec = miner_registry.get(type_id)
        paradigm = spec.paradigm if spec else ""
    return extract_metrics_by_paradigm(paradigm, result, source="native")
