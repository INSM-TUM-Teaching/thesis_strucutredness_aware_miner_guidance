"""Precision-proxy indicators for Declare / MINERful models.

These are *not* classical precision metrics. For Declare there is no widely
established standard precision, so the module deliberately exposes only
proxy indicators and a disclaimer string. The caller is expected to render
them clearly as such (see `report_render.py`, Comparison-UI, and
`docs/declarative_metrics.md`).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

DISCLAIMER = "Not a standard precision metric. Proxy indicators only."


_EXISTENCE_TEMPLATES = {
    "existence",
    "absence",
    "init",
    "end",
    "atleast1",
    "atleast2",
    "atleast3",
    "atmost1",
    "atmost2",
    "atmost3",
    "exactly",
    "participation",
}
_CHOICE_TEMPLATES = {
    "choice",
    "exclusivechoice",
    "coexistence",
}
_RELATION_TEMPLATES = {
    "respondedexistence",
    "response",
    "alternateresponse",
    "chainresponse",
    "precedence",
    "alternateprecedence",
    "chainprecedence",
    "succession",
    "alternatesuccession",
    "chainsuccession",
}


def _classify_template(raw_name: str) -> str:
    name = raw_name.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    if name.startswith("not"):
        return "negation"
    if name in _EXISTENCE_TEMPLATES:
        return "existence"
    if name in _CHOICE_TEMPLATES:
        return "choice"
    if name in _RELATION_TEMPLATES:
        return "relation"
    return "other"


def compute_precision_proxies(
    *,
    fitness_result: Mapping[str, Any],
    vacuity_result: Mapping[str, Any] | None = None,
    constraints: Sequence[Mapping[str, Any]] | None = None,
    activities: Sequence[str] | None = None,
) -> Dict[str, Any]:
    # avg_constraint_fulfillment_rate maps to the model-level mean trace full
    # satisfaction rate from the MINERful FitnessChecker — pure arithmetic over
    # tool-emitted FullSatisfactions counts (see minerful_fitness.py).
    model_aggregates = fitness_result.get("model_aggregates") or {}
    avg_rate = model_aggregates.get("mean_trace_full_satisfaction_rate")

    # non_vacuous_satisfaction_rate comes from the SAME fitness result as
    # vacuity_rate (single source, discovered post-pruning constraint basis;
    # see minerful_fitness._derive_fitness_metrics). The legacy ``vacuity_result``
    # parameter is no longer consulted — the Java vacuity POC has been retired.
    fitness_metrics = fitness_result.get("fitness_metrics") or {}
    non_vac_rate = fitness_metrics.get("non_vacuous_satisfaction_rate")
    vacuity_check_available = bool(fitness_result.get("available")) and (
        non_vac_rate is not None
    )

    constraints = list(constraints or [])
    activities = list(activities or [])
    n_constraints = len(constraints)
    n_activities = len(activities)

    by_template: Dict[str, int] = {}
    for c in constraints:
        tmpl = c.get("template") or ""
        category = _classify_template(str(tmpl))
        by_template[category] = by_template.get(category, 0) + 1

    # NOTE: constraint_density is intentionally NOT computed here. The canonical
    # value lives in metrics["constraint_density"] (see comparison_app
    # run_miners.py), derived from the full discovered MINERful spec
    # (n_constraints / n_activities over ALL tasks). Recomputing it here from the
    # FitnessChecker-evaluated subset would yield a second, divergent number on a
    # post-measurement-pruning basis — redundant and misleading. Removed.
    return {
        "avg_constraint_fulfillment_rate": avg_rate,
        "non_vacuous_satisfaction_rate": non_vac_rate,
        "vacuity_check_available": vacuity_check_available,
        "model_size": {
            "n_constraints": n_constraints,
            "n_activities": n_activities,
            "by_template": by_template,
        },
        "disclaimer": DISCLAIMER,
    }
