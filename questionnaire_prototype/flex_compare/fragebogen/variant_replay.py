"""Per-variant replay — the evidence base for S-BQ-2.

For one ``(log, discovered model)`` pair, group the log by trace variant,
decide for each variant whether the model accepts it, and return a structured
breakdown.

Two paradigm paths are wired up:

* **Imperative (``imperativ``)** — Petri net via the cached ``.pnml``;
  pm4py's token-based replay on a one-variant-per-trace mini-log.
* **Declarative (``deklarativ``)** — MINERful constraint spec via the cached
  per-log JSON; pure-Python Declare evaluation (see
  :mod:`flex_compare.fragebogen.declare_check`). A variant is *replayable*
  iff no Declare constraint is violated — vacuous satisfactions count as
  accepted, matching the S-BQ-2 reading (*Replay = non-violation*; vacuity
  remains a separate axis).

Hybrid Fusion (PNwA + constraints) is not yet supported and returns
``supported=False`` with a reason so the UI does not invent a number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VariantReplay:
    """Result of a per-variant replay against one discovered model.

    ``method`` identifies which checker produced the verdict — surfaced in the
    UI so the reader knows whether they're looking at a PN token-replay or a
    Declare constraint evaluation. ``n_unknown_constraints`` is non-zero only
    on the declarative path when MINERful emits a template the Python checker
    doesn't recognise yet; the panel mentions it so the answer is not silently
    overstated.
    """
    supported: bool
    reason: str = ""
    method: str = ""                # "petri-net-replay" | "declare-check" | ""
    n_traces: int = 0
    n_variants: int = 0
    n_variants_replayable: int = 0
    replayable_trace_share: float = 0.0
    variants: tuple[dict, ...] = ()  # each: {variant, count, share, replayable}
    n_unknown_constraints: int = 0

    @property
    def non_replayable_trace_share(self) -> float:
        return max(0.0, 1.0 - self.replayable_trace_share)


def compute_variant_replay(log_path: Path, result: dict,
                            paradigm: str) -> VariantReplay:
    """Compute the per-variant replay breakdown for ``(log_path, result)``.

    Dispatches by paradigm:

    * ``imperativ`` → cached ``.pnml`` + pm4py token replay.
    * ``deklarativ`` → cached MINERful constraint spec + Python Declare check.
    * ``hybrid`` and everything else → ``supported=False`` with a reason.

    Errors during loading are turned into the same ``supported=False`` shape so
    the UI never raises.
    """
    if paradigm == "deklarativ":
        spec_path = _resolve_declare_spec_path(result)
        if spec_path is None:
            return VariantReplay(
                supported=False,
                reason=("No MINERful constraint JSON in the cached run. "
                        "Likely an older cache; please re-run the miner "
                        "(▶ Run now on the log)."))
        return _cached_compute_declare(
            str(Path(log_path).resolve()), str(spec_path))

    if paradigm == "imperativ":
        pnml_path = _resolve_pnml_path(result, paradigm)
        if pnml_path is None:
            return VariantReplay(
                supported=False,
                reason=("No PNML in the cached run. Likely an older cache "
                        "from before the PNML export was added. Please "
                        "re-run the miner (▶ Run now on the log)."))
        return _cached_compute(
            str(Path(log_path).resolve()), str(pnml_path))

    if paradigm == "hybrid":
        return VariantReplay(
            supported=False,
            reason=("Fusion (hybrid) is not implemented yet — the PNwA "
                    "parser is missing. Coming in the next step; until then "
                    "rely on the aggregate metrics."))

    return VariantReplay(
        supported=False,
        reason=f'Paradigm "{paradigm or "unknown"}" is not supported.')


def _resolve_pnml_path(result: dict, paradigm: str) -> Optional[str]:
    """Return the cached ``.pnml`` path or ``None``.

    Keys checked (top-level + one nested dict level):

    * ``petri_net_pnml_path`` — the explicit PNML emitted by the IM adapter.
    * ``petri_net_path`` — accepted only if it actually ends in ``.pnml``;
      most adapters store the rendered PNG under this name, which is not what
      we want.
    """
    if not isinstance(result, dict):
        return None

    def _accept(value) -> Optional[str]:
        if not isinstance(value, str) or not value:
            return None
        if not value.lower().endswith(".pnml"):
            return None
        return value if Path(value).is_file() else None

    # Preferred: the explicit PNML key.
    direct = _accept(result.get("petri_net_pnml_path"))
    if direct:
        return direct
    # Fallback: a petri_net_path that genuinely points to a PNML (some adapters
    # do this; ours don't, but a custom-exec PNML import would).
    direct = _accept(result.get("petri_net_path"))
    if direct:
        return direct
    # Nested locations (run_data / run_results — Fusion-style payloads).
    for key in ("run_data", "run_results"):
        nested = result.get(key)
        if not isinstance(nested, dict):
            continue
        for inner in ("petri_net_pnml_path", "petri_net_path"):
            candidate = _accept(nested.get(inner))
            if candidate:
                return candidate
    return None


@lru_cache(maxsize=128)
def _cached_compute(log_path_str: str, pnml_path_str: str) -> VariantReplay:
    """Heavy compute path, memoized on the absolute log + PNML paths."""
    try:
        return _compute(Path(log_path_str), Path(pnml_path_str))
    except Exception as exc:  # noqa: BLE001 — defensive, UI must not crash
        logger.warning("variant_replay compute failed for %s / %s: %s",
                       log_path_str, pnml_path_str, exc)
        return VariantReplay(
            supported=False,
            reason=f"Replay computation failed: {type(exc).__name__}: {exc}",
        )


def _compute(log_path: Path, pnml_path: Path) -> VariantReplay:
    import pm4py  # local import — pm4py is heavy, skip on cold imports
    from pm4py.algo.conformance.tokenreplay import algorithm as token_replay
    from pm4py.objects.log.obj import EventLog, Event, Trace

    log = pm4py.read_xes(str(log_path))
    net, im, fm = pm4py.read_pnml(str(pnml_path))

    # ``get_variants_as_tuples`` returns ``{tuple_of_activities: count}``.
    # On newer pm4py the helper sits on the top-level namespace; fall back to
    # the variants filter for older versions.
    if hasattr(pm4py, "get_variants_as_tuples"):
        variants = pm4py.get_variants_as_tuples(log)
    else:
        from pm4py.statistics.variants.log import get as variants_get
        variants = variants_get.get_variants(log)
    # Normalise to a {variant_tuple: count} dict regardless of pm4py version.
    items: list[tuple[tuple, int]] = []
    for key, value in variants.items():
        var_tuple = tuple(key) if not isinstance(key, tuple) else key
        if isinstance(value, int):
            count = value
        elif isinstance(value, list):
            count = len(value)
        else:
            count = int(getattr(value, "__len__", lambda: 0)() or 0)
        items.append((var_tuple, count))
    items.sort(key=lambda kv: (-kv[1], kv[0]))  # desc by count, stable by activities

    if not items:
        return VariantReplay(supported=True, n_traces=0, n_variants=0,
                             variants=())

    # Build one representative trace per variant; replay returns one diagnostic
    # dict per trace, co-indexed with the variant order above.
    variant_log = EventLog()
    for var, _count in items:
        trace = Trace()
        for act in var:
            trace.append(Event({"concept:name": act}))
        variant_log.append(trace)

    diagnostics = token_replay.apply(variant_log, net, im, fm)

    rows = []
    n_traces = sum(c for _, c in items)
    replayable_traces = 0
    n_variants_replayable = 0
    for (var, count), diag in zip(items, diagnostics):
        fit = bool(diag.get("trace_is_fit"))
        share = count / n_traces if n_traces else 0.0
        rows.append({
            "variant": tuple(var),
            "count": count,
            "share": share,
            "replayable": fit,
        })
        if fit:
            n_variants_replayable += 1
            replayable_traces += count

    replayable_share = replayable_traces / n_traces if n_traces else 0.0
    return VariantReplay(
        supported=True,
        method="petri-net-replay",
        n_traces=n_traces,
        n_variants=len(rows),
        n_variants_replayable=n_variants_replayable,
        replayable_trace_share=replayable_share,
        variants=tuple(rows),
    )


# ── Declarative path ───────────────────────────────────────────────────────

def _resolve_declare_spec_path(result: dict) -> Optional[str]:
    """Return the path to the cached MINERful constraint JSON, or ``None``.

    The MINERful adapter caches the spec under the run's ``artifacts/`` and
    stores the path under ``metrics.json_path``. Older runs may carry the path
    at the top level instead; we look in both places before giving up.
    """
    if not isinstance(result, dict):
        return None

    def _accept(value) -> Optional[str]:
        if not isinstance(value, str) or not value:
            return None
        return value if Path(value).is_file() else None

    direct = _accept(result.get("declare_model_json_path"))
    if direct:
        return direct
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        cand = _accept(metrics.get("json_path"))
        if cand:
            return cand
    return None


@lru_cache(maxsize=128)
def _cached_compute_declare(log_path_str: str,
                             spec_path_str: str) -> VariantReplay:
    try:
        return _compute_declare(Path(log_path_str), Path(spec_path_str))
    except Exception as exc:  # noqa: BLE001
        logger.warning("declarative replay failed for %s / %s: %s",
                       log_path_str, spec_path_str, exc)
        return VariantReplay(
            supported=False,
            method="declare-check",
            reason=(f"Replay computation failed: "
                    f"{type(exc).__name__}: {exc}"),
        )


def _compute_declare(log_path: Path, spec_path: Path) -> VariantReplay:
    import json
    import pm4py

    from flex_compare.fragebogen.declare_check import evaluate_trace

    log = pm4py.read_xes(str(log_path))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    constraints = spec.get("constraints") or []

    if hasattr(pm4py, "get_variants_as_tuples"):
        variants = pm4py.get_variants_as_tuples(log)
    else:
        from pm4py.statistics.variants.log import get as variants_get
        variants = variants_get.get_variants(log)

    items: list[tuple[tuple, int]] = []
    for key, value in variants.items():
        var_tuple = tuple(key) if not isinstance(key, tuple) else key
        if isinstance(value, int):
            count = value
        elif isinstance(value, list):
            count = len(value)
        else:
            count = int(getattr(value, "__len__", lambda: 0)() or 0)
        items.append((var_tuple, count))
    items.sort(key=lambda kv: (-kv[1], kv[0]))

    rows = []
    n_traces = sum(c for _, c in items)
    replayable_traces = 0
    n_variants_replayable = 0
    total_unknown = 0
    for var, count in items:
        verdict = evaluate_trace(constraints, list(var))
        fit = bool(verdict["replayable"])
        share = count / n_traces if n_traces else 0.0
        total_unknown += int(verdict["n_unknown"])
        rows.append({
            "variant": tuple(var),
            "count": count,
            "share": share,
            "replayable": fit,
            "constraint_diagnostics": {
                "n_total": int(verdict["n_total"]),
                "n_satisfied": int(verdict["n_satisfied"]),
                "n_violated": int(verdict["n_violated"]),
                "n_unknown": int(verdict["n_unknown"]),
            },
        })
        if fit:
            n_variants_replayable += 1
            replayable_traces += count

    return VariantReplay(
        supported=True,
        method="declare-check",
        n_traces=n_traces,
        n_variants=len(rows),
        n_variants_replayable=n_variants_replayable,
        replayable_trace_share=(replayable_traces / n_traces
                                  if n_traces else 0.0),
        variants=tuple(rows),
        # Average unknown-count across variants — same value would appear
        # constant per variant since the constraint set is shared, but storing
        # the per-variant maximum gives the UI an honest number to surface.
        n_unknown_constraints=max(
            (row["constraint_diagnostics"]["n_unknown"] for row in rows),
            default=0),
    )
