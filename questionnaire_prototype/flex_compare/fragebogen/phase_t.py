"""Phase-T scoring — theoretical Yes/No from documented miner disposition.

Phase T is the *theoretical* leg of the T+E architecture (SSOT §2): a binary
Yes/No per item, derived a-priori from a miner's documented properties
(spec / docs / algorithm), NOT from a concrete run. The per-miner seeds live
in each item's ``phase_t_seed`` block in the YAML config; this module
aggregates them into a class T-Fit.

Scoring rules (SSOT §0, §2):
* ``T-Fit(K) = #Yes / #Items(K) × 100``.
* ``No`` and ``n/a = 0 flagged`` both count as 0 in the numerator. ``n/a``
  stays in the denominator (SSOT §5: "not removed from the denominator").
* Unanswered cells (``None``) are pending — excluded from the denominator so
  the running fit is meaningful before the last item is answered.
* within-miner / descriptive — no cross-paradigm numeric comparisons (RC3).
"""
from __future__ import annotations

from typing import Optional

from flex_compare.fragebogen import items as fb_items
from flex_compare.fragebogen import phase_t_answers as fb_answers
from flex_compare.fragebogen.config_loader import load as _load_config


def configured_classes() -> tuple[str, ...]:
    """Classes that currently have a YAML config."""
    return tuple(_load_config().keys())


def phase_t_miners(cls: str) -> list[str]:
    """Union of miner ids that carry a Phase-T seed anywhere in ``cls``."""
    miners: list[str] = []
    for item in fb_items.phase_t_items_for_class(cls):
        for miner_id in (item.get("phase_t_seed") or {}):
            if miner_id not in miners:
                miners.append(miner_id)
    return miners


def phase_t_item_value(item_id: str, miner_id: str) -> Optional[str]:
    """Seed value of ``miner_id`` on ``item_id`` — ``"ja"`` / ``"nein"`` /
    ``"nz"`` / ``None``."""
    entry = fb_items.phase_t_seed(item_id).get(miner_id)
    if not entry:
        return None
    return entry.get("value")


def _value_to_points(value) -> tuple[int, bool]:
    """Translate a Ja/Nein/n.z./None value into (points, counts_in_denominator)."""
    if value == "ja":
        return 1, True
    if value == "nein":
        return 0, True
    if value == "nz":
        # n.z. = 0 markiert (Doc §5): NOT excluded from the denominator.
        return 0, True
    return 0, False  # None / pending — drops from denominator until answered


def phase_t_fit(miner_id: str, cls: str) -> dict:
    """Aggregate ``miner_id``'s Phase-T seeds on ``cls`` into a T-Fit.

    Returns:
        ``per_item``  dict[item_id → {value, note, points}]
        ``points``    sum of points across answered items
        ``max``       #items currently answered (n.z. + ja + nein), each worth 1
        ``max_full``  ``meta.phase_t_max`` (total #items in the class)
        ``n_ja``      count of "ja" answers
        ``n_nein``    count of "nein" answers
        ``n_nz``      count of "n.z." answers
        ``n_pending`` count of unanswered items (no seed, value=null)
        ``fit``       points / max × 100 (1 dp) or ``None`` if all pending
        ``complete``  True iff every item is answered
    """
    return _aggregate(miner_id, cls,
                      override=lambda *_args, **_kw: None)


def phase_t_fit_with_answers(miner_id: str, cls: str) -> dict:
    """Like :func:`phase_t_fit`, but overlays persisted survey answers on
    top of the YAML seeds before aggregating."""
    answers = fb_answers.load_all_answers(cls)
    return _aggregate(miner_id, cls,
                      override=lambda item_id: answers.get((miner_id, item_id)))


def _aggregate(miner_id: str, cls: str, *, override) -> dict:
    per_item: dict[str, dict] = {}
    points = 0
    counted = 0
    n_ja = n_nein = n_nz = n_pending = n_human = 0
    for item in fb_items.phase_t_items_for_class(cls):
        item_id = item["id"]
        seed = (item.get("phase_t_seed") or {}).get(miner_id) or {}
        value = seed.get("value")
        note = seed.get("note", "")
        source = "seed"
        ans = override(item_id)
        if ans is not None:
            value = ans.get("value")
            note = ans.get("note", "") or ""
            source = "human"
            n_human += 1
        pts, counts = _value_to_points(value)
        per_item[item_id] = {"value": value, "note": note,
                             "points": pts, "source": source}
        if counts:
            points += pts
            counted += 1
        if value == "ja":
            n_ja += 1
        elif value == "nein":
            n_nein += 1
        elif value == "nz":
            n_nz += 1
        else:
            n_pending += 1

    meta = fb_items.meta_for_class(cls) or {}
    fit = round(points / counted * 100, 1) if counted else None
    return {
        "miner": miner_id,
        "class": cls,
        "phase": "T",
        "per_item": per_item,
        "points": points,
        "max": counted,
        "max_full": meta.get("phase_t_max"),
        "n_ja": n_ja,
        "n_nein": n_nein,
        "n_nz": n_nz,
        "n_pending": n_pending,
        "n_human": n_human,
        "fit": fit,
        "complete": n_pending == 0,
    }


def phase_t_vector(miner_id: str, *, with_answers: bool = False) -> dict:
    """Phase-T Fit of ``miner_id`` across all configured classes.

    Keys follow the canonical order ``structured`` / ``semi`` / ``loosely``;
    unconfigured classes contribute ``None`` so the vector shape is stable.
    """
    order = ("structured", "semi", "loosely")
    configured = set(configured_classes())
    fit_fn = phase_t_fit_with_answers if with_answers else phase_t_fit
    fits: dict[str, Optional[float]] = {}
    details: dict[str, dict] = {}
    for cls in order:
        if cls in configured:
            res = fit_fn(miner_id, cls)
            fits[cls] = res["fit"]
            details[cls] = res
        else:
            fits[cls] = None

    scorable = {c: f for c, f in fits.items() if f is not None}
    home = max(scorable, key=scorable.get) if scorable else None
    return {
        "miner": miner_id,
        "phase": "T",
        "fits": fits,
        "home_class": home,
        "details": details,
        "complete": configured == set(order),
    }
