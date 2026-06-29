"""Combine Phase-T and Phase-E Fits into one class fit (and report both legs).

The thesis (``ssec:scoring``) combines the theoretical and empirical legs by
weighting every item equally. Each class has ``n_T`` Phase-T items and ``n_E``
Phase-E items, so

    ``Fit_c(m) = (n_T / (n_T + n_E)) · Tfit_c(m) + (n_E / (n_T + n_E)) · Efit_c(m)``

With three Phase-T items and four Phase-E items this is exactly
``3/7 · Tfit + 4/7 · Efit``. The weights are derived from the live item counts
(:func:`class_weights`) rather than hardcoded, so they stay correct if a class
ever gains or loses an item. The combined fit is defined only when **both** legs
are scorable; otherwise it is ``None``.

This module assembles a per-miner view that exposes the combined fit, both legs
side by side (for the detail views), and a borderline flag (top two scorable
combined fits within ``borderline_margin`` percentage points).
"""
from __future__ import annotations

from typing import Optional

from flex_compare.fragebogen import items as fb_items
from flex_compare.fragebogen import phase_e as fb_phase_e
from flex_compare.fragebogen import phase_t as fb_phase_t

_DEFAULT_MARGIN = 10.0


def combination_config(cls: str) -> dict:
    """The ``meta.combination`` block for ``cls`` (mode + borderline margin)."""
    meta = fb_items.meta_for_class(cls) or {}
    return dict(meta.get("combination") or {})


def class_weights(cls: str) -> dict:
    """Per-item weights for ``cls``, derived from the live item counts.

    Returns ``{n_t, n_e, w_t, w_e}`` where ``w_t = n_t / (n_t + n_e)`` and
    ``w_e = n_e / (n_t + n_e)`` (equal weight per item). ``w_t``/``w_e`` are
    ``None`` if the class declares no items.
    """
    n_t = len(fb_items.phase_t_items_for_class(cls))
    n_e = len(fb_items.phase_e_items_for_class(cls))
    total = n_t + n_e
    if total <= 0:
        return {"n_t": n_t, "n_e": n_e, "w_t": None, "w_e": None}
    return {"n_t": n_t, "n_e": n_e, "w_t": n_t / total, "w_e": n_e / total}


def combined_fit(tfit: Optional[float], efit: Optional[float], *,
                 n_t: int, n_e: int) -> Optional[float]:
    """Equal-per-item combination of a T-Fit and E-Fit (``None`` if either leg
    is unscorable or the class declares no items)."""
    if tfit is None or efit is None:
        return None
    total = n_t + n_e
    if total <= 0:
        return None
    return round((n_t * tfit + n_e * efit) / total, 1)


def borderline(fits: dict[str, Optional[float]], margin: float) -> bool:
    """``True`` if the top two scorable class fits are within ``margin`` pp."""
    scorable = sorted((f for f in fits.values() if f is not None), reverse=True)
    if len(scorable) < 2:
        return False
    return (scorable[0] - scorable[1]) <= margin


def report(miner_id: str, *, with_answers: bool = False, state=None) -> dict:
    """Per-class combined Fit for ``miner_id``, with both legs side by side.

    Returns:
        ``fits``         dict[class → combined Fit % | None]
        ``home``         arg-max over scorable combined Fits
        ``borderline``   near-tie between top-two combined Fits
        ``complete``     both legs complete across all configured classes
        ``t_fits``       dict[class → T-Fit % | None]
        ``e_fits``       dict[class → E-Fit % | None]
        ``t_home``       arg-max over scorable T-Fits (detail views only)
        ``e_home``       arg-max over scorable E-Fits (detail views only)
        ``per_class``    dict[class → {phase_t, phase_e, fit, weights,
                         borderline_margin}]
        ``t_borderline`` near-tie between top-two T-Fits
        ``e_borderline`` near-tie between top-two E-Fits
        ``mode``         "weighted" (equal weight per item)
    """
    t_vec = fb_phase_t.phase_t_vector(miner_id, with_answers=with_answers)
    e_vec = fb_phase_e.phase_e_vector(miner_id, state=state)
    per_class: dict[str, dict] = {}
    fits: dict[str, Optional[float]] = {}
    margin = _DEFAULT_MARGIN
    for cls in t_vec["fits"]:
        comb = combination_config(cls)
        margin = float(comb.get("borderline_margin", _DEFAULT_MARGIN))
        w = class_weights(cls)
        fit_c = combined_fit(t_vec["fits"].get(cls), e_vec["fits"].get(cls),
                             n_t=w["n_t"], n_e=w["n_e"])
        fits[cls] = fit_c
        per_class[cls] = {
            "phase_t": t_vec["details"].get(cls),
            "phase_e": e_vec["details"].get(cls),
            "fit": fit_c,
            "weights": w,
            "borderline_margin": margin,
        }
    scorable = {c: f for c, f in fits.items() if f is not None}
    home = max(scorable, key=scorable.get) if scorable else None
    return {
        "miner": miner_id,
        "mode": "weighted",
        "fits": fits,
        "home": home,
        "borderline": borderline(fits, margin),
        "complete": t_vec["complete"] and e_vec["complete"],
        "t_fits": t_vec["fits"],
        "e_fits": e_vec["fits"],
        "t_home": t_vec["home_class"],
        "e_home": e_vec["home_class"],
        "per_class": per_class,
        "t_borderline": borderline(t_vec["fits"], margin),
        "e_borderline": borderline(e_vec["fits"], margin),
        "t_complete": t_vec["complete"],
        "e_complete": e_vec["complete"],
    }


def combined_vector(miner_id: str, *, with_answers: bool = False,
                    state=None) -> dict:
    """Combined Fit vector across all configured classes.

    ``home_class`` is the arg-max over scorable combined fits; ``weights``
    records the per-class ``{n_t, n_e, w_t, w_e}`` used for the combination.
    """
    t_vec = fb_phase_t.phase_t_vector(miner_id, with_answers=with_answers)
    e_vec = fb_phase_e.phase_e_vector(miner_id, state=state)
    fits: dict[str, Optional[float]] = {}
    weights: dict[str, dict] = {}
    for cls, tfit in t_vec["fits"].items():
        w = class_weights(cls)
        weights[cls] = w
        fits[cls] = combined_fit(tfit, e_vec["fits"].get(cls),
                                 n_t=w["n_t"], n_e=w["n_e"])
    scorable = {c: f for c, f in fits.items() if f is not None}
    home = max(scorable, key=scorable.get) if scorable else None
    return {
        "miner": miner_id,
        "fits": fits,
        "home_class": home,
        "weights": weights,
        "borderline": borderline(fits, _DEFAULT_MARGIN),
        "complete": t_vec["complete"] and e_vec["complete"],
    }


def combine_fit(fit_a, fit_b, *, weights=None, cls: str = "structured") -> dict:
    """Combine a T-Fit and E-Fit for ``cls`` with equal-per-item weights.

    ``weights`` may override the derived ``{"phase_a": w_t, "phase_b": w_e}``;
    otherwise the live item counts for ``cls`` decide them.
    """
    w = class_weights(cls)
    if weights:
        wa = float(weights.get("phase_a", w["w_t"] or 0.0))
        wb = float(weights.get("phase_b", w["w_e"] or 0.0))
    else:
        wa, wb = w["w_t"], w["w_e"]
    if fit_a is None or fit_b is None or wa is None or wb is None:
        fit = None
    else:
        fit = round(wa * fit_a + wb * fit_b, 1)
    return {
        "fit": fit,
        "phase_a": fit_a,
        "phase_b": fit_b,
        "weights": {"phase_a": wa, "phase_b": wb},
        "phase_b_pending": fit_b is None,
    }


def combination_config_legacy(cls: str) -> dict:
    """Legacy alias exposing the per-item weights — kept for tests that read
    them."""
    raw = combination_config(cls)
    w = class_weights(cls)
    return {**raw, "phase_a_weight": w["w_t"], "phase_b_weight": w["w_e"],
            "borderline_margin": raw.get("borderline_margin", _DEFAULT_MARGIN)}
