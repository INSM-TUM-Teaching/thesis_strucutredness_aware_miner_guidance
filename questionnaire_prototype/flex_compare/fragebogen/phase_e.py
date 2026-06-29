"""Phase-E scoring — empirical 0/1/2 from concrete miner runs.

Phase E (Doc §3) is the *empirical* leg: for each class log in
``logs_for_class(cls)`` and each Phase-E item the rater scores the discovered
model on the 2/1/0 scale. ``n.z.`` is allowed where the YAML sets
``allow_nz: true`` and counts as 0 markiert (Doc §5: not removed from the
denominator).

Semi gate (Doc §3): the optional ``E-Sm-Gate`` is ungescort. When the gate is
answered ``"nein"`` the Semi item ``E-Sm-SF-1`` is forced to 0 (per
``gate_zero_on_no: true`` in the YAML) and the four zone items fall back to a
global read over the whole model — their scores are NOT auto-zeroed; the gate
state is exposed alongside the cells so the UI can label them as "globaler
Read".

Scoring rules (Doc §0, §3, §5):
* Per log: ``E-Fit(log) = points(log) / (2 × answered cells in log) × 100``.
* ``E-Fit(K)`` = mean ("Mittelmaß") of the per-log Fits, so each class log
  carries equal weight regardless of how many of its cells are rated.
* While cells are unanswered they are excluded from the per-log denominator so
  the displayed fit reflects only what has been scored.
* ``n.z.`` counts as 0 and stays in the denominator.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flex_compare import runner as fc_runner
from flex_compare.fragebogen import items as fb_items
from flex_compare.fragebogen import phase_e_answers as fb_scores
from flex_compare.fragebogen.log_discovery import logs_for_class
from flex_compare.internal.shared.cache import result_cache
from flex_compare.internal.shared.paths import PROJECT_ROOT
from flex_compare.internal.shared.registry import miner_registry
from flex_compare.state import MinerInstance


DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "with-case-ids"
DEFAULT_LOGS_PER_CLASS = 3

_GATE_ID = "E-Sm-Gate"


def phase_e_logs(cls: str, log_dir: Optional[Path] = None,
                 limit: int = DEFAULT_LOGS_PER_CLASS) -> list[Path]:
    """The (up to ``limit``) class logs Phase E is evaluated on."""
    base = log_dir or DEFAULT_LOG_DIR
    return logs_for_class(cls, base)[:limit]


def _ephemeral_instance_for_spec(miner_id: str) -> Optional[MinerInstance]:
    """Synthesize a registry-backed instance with default config.

    Mirrors the Tab-3 UI helper of the same name
    (``ui.tabs.fragebogen._ephemeral_instance_for_spec``) so the slot computed
    here matches the one the save path used for an ephemeral registry miner.
    """
    spec = miner_registry.get(miner_id)
    if spec is None:
        return None
    config = {p.key: p.default for p in spec.config_schema}
    return MinerInstance(
        id=miner_id,
        spec_source="registry",
        spec_id=miner_id,
        label=spec.label,
        config=config,
    )


def _resolve_slot(miner_id: str, state) -> Optional[tuple[str, object]]:
    """Find the live :class:`MinerInstance` for ``miner_id`` and its cache slot.

    This MUST resolve the same instance (and therefore the same cache slot) that
    the save and render paths use, or scores are written under one slot and read
    under another and the Fit never moves. Tab 3 renders every tile and donut
    with the ephemeral default-config instance whose ``id == spec_id`` (see
    ``ui.tabs.fragebogen._ephemeral_instance_for_spec``), and the save callbacks
    resolve the miner via ``_find_instance`` which matches ``state.instances`` by
    ``inst.id``. We mirror that exactly: match by ``inst.id == miner_id`` (the
    back-compat case where a session stored an instance UUID), else build the
    ephemeral default-config instance. Matching by ``spec_id`` here was the bug:
    a Tab-2 instance of the same registry spec (id != spec_id) carries its own
    config, so its slot diverged from the default-config slot the save path used.
    """
    for inst in getattr(state, "instances", ()) or ():
        if getattr(inst, "id", None) != miner_id:
            continue
        try:
            slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
        except Exception:
            continue
        return slot, inst
    inst = _ephemeral_instance_for_spec(miner_id)
    if inst is None:
        return None
    try:
        slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
    except Exception:
        return None
    return slot, inst


def _value_to_points(value, *, max_score: int = 2) -> tuple[int, bool, bool]:
    """Translate an E-cell value into ``(points, counted, is_nz)``.

    ``value`` may be 0/1/2 (numeric), ``"nz"`` (n.z. = 0 markiert) or ``None``
    (pending — excluded from the denominator).
    """
    if value == "nz":
        return 0, True, True
    if value is None:
        return 0, False, False
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0, False, False
    if 0 <= score <= max_score:
        return score, True, False
    return 0, False, False


def is_available(miner_id: str, cls: str, *, state=None) -> bool:
    """Whether at least one Phase-E cell has been persisted for ``miner_id``."""
    resolved = _resolve_slot(miner_id, state)
    if resolved is None:
        return False
    slot, _ = resolved
    items = fb_items.phase_e_items_for_class(cls)
    if not items:
        return False
    for log_path in phase_e_logs(cls):
        log_id = _safe_log_id(log_path)
        if log_id is None:
            continue
        cells = fb_scores.load_all_scores(log_id)
        for item in items:
            cell = cells.get((slot, item["id"]))
            if cell and cell.get("value") is not None:
                return True
    return False


def gate_state(log_id: str, slot: str) -> Optional[str]:
    """Persisted Semi-gate answer for ``(log_id, slot)`` — ``"ja"``/``"nein"``/``None``."""
    cell = fb_scores.load_score(log_id, slot, _GATE_ID)
    if cell is None:
        return None
    value = cell.get("value")
    if value in ("ja", "nein"):
        return value
    return None


def phase_e_fit(miner_id: str, cls: str, *, state=None) -> dict:
    """Aggregate persisted Phase-E cells for ``miner_id`` on ``cls`` into a Fit.

    The class Empirical Fit is the mean ("Mittelmaß") of the per-log Fits: each
    log is scored on its own answered cells, then the per-log Fits are averaged
    so every log carries equal weight. ``points``/``max`` remain the pooled
    totals (for the coverage line and the donut sublabel); ``fit_pooled`` keeps
    the old pooled ``points / max`` reading for reference.

    Returns a dict with per-cell breakdown plus
        ``points``       sum of scored cells (pooled across logs)
        ``max``          2 × (#answered cells), excluding pending (pooled)
        ``max_full``     ``meta.phase_e_max`` × n_logs (total possible)
        ``fit``          mean of per-log Fits (1 dp) or ``None`` if no log scored
        ``fit_pooled``   pooled points / max × 100 (1 dp) or ``None``
        ``per_log``      dict[log_stem → {points, max, counted, n_pending, fit}]
        ``n_logs_scored``count of logs with at least one counted cell
        ``n_pending``    count of (log × item) cells not yet rated
        ``n_nz``         count of n.z. cells
        ``gates``        dict[log_stem → "ja"/"nein"/None] for Semi
        ``complete``     True iff no cell is pending
    """
    items = fb_items.phase_e_items_for_class(cls)
    logs = phase_e_logs(cls)
    resolved = _resolve_slot(miner_id, state)
    meta = fb_items.meta_for_class(cls) or {}

    per_cell: dict[str, dict] = {}
    per_log: dict[str, dict] = {}
    points = 0
    counted = 0
    n_nz = n_pending = 0
    gates: dict[str, Optional[str]] = {}
    slot: Optional[str] = None

    def _log_acc(stem: str) -> dict:
        return per_log.setdefault(
            stem, {"log": stem, "points": 0, "counted": 0,
                   "n_nz": 0, "n_pending": 0, "fit": None})

    if resolved is not None:
        slot, _inst = resolved
        for log_path in logs:
            stem = log_path.stem
            acc = _log_acc(stem)
            log_id = _safe_log_id(log_path)
            if log_id is None:
                continue
            cells = fb_scores.load_all_scores(log_id)
            gate_value = None
            gate_cell = cells.get((slot, _GATE_ID))
            if gate_cell:
                raw = gate_cell.get("value")
                if raw in ("ja", "nein"):
                    gate_value = raw
            gates[stem] = gate_value
            for item in items:
                key = f"{stem}::{item['id']}"
                cell = cells.get((slot, item["id"]))
                raw_value = cell.get("value") if cell else None
                note = (cell.get("note") if cell else "") or ""
                forced = False
                if (gate_value == "nein"
                        and item.get("gate_zero_on_no")
                        and raw_value is None):
                    raw_value = 0
                    forced = True
                pts, counts, is_nz = _value_to_points(raw_value)
                per_cell[key] = {
                    "value": raw_value,
                    "note": note,
                    "log": stem,
                    "item": item["id"],
                    "points": pts,
                    "forced_by_gate": forced,
                    "global_read": (gate_value == "nein"
                                     and item.get("zone_kind") is not None),
                }
                if counts:
                    points += pts
                    counted += 1
                    acc["points"] += pts
                    acc["counted"] += 1
                if is_nz:
                    n_nz += 1
                    acc["n_nz"] += 1
                if raw_value is None:
                    n_pending += 1
                    acc["n_pending"] += 1
    else:
        for log_path in logs:
            stem = log_path.stem
            _log_acc(stem)
            gates[stem] = None
            for item in items:
                key = f"{stem}::{item['id']}"
                per_cell[key] = {"value": None, "note": "", "log": stem,
                                 "item": item["id"], "points": 0,
                                 "forced_by_gate": False, "global_read": False}
                n_pending += 1
                per_log[stem]["n_pending"] += 1

    # Per-log Fit: each log scored on its own answered cells. The class Empirical
    # Fit is the mean ("Mittelmaß") of the per-log Fits, so every log carries the
    # same weight regardless of how many of its cells have been rated. ``points``
    # / ``max`` stay pooled for the coverage line and donut sublabel.
    log_fits: list[float] = []
    for acc in per_log.values():
        lmax = 2 * acc["counted"]
        acc["max"] = lmax
        acc["fit"] = round(acc["points"] / lmax * 100, 1) if lmax else None
        if acc["fit"] is not None:
            log_fits.append(acc["fit"])

    max_scored = 2 * counted
    fit = round(sum(log_fits) / len(log_fits), 1) if log_fits else None
    fit_pooled = round(points / max_scored * 100, 1) if max_scored else None
    available = counted > 0
    return {
        "miner": miner_id,
        "class": cls,
        "phase": "E",
        "available": available,
        "fit": fit,
        "fit_pooled": fit_pooled,
        "points": points,
        "max": max_scored,
        "max_full": (meta.get("phase_e_max") or 0) * len(logs),
        "per_cell": per_cell,
        "per_log": per_log,
        "n_scored": counted,
        "n_nz": n_nz,
        "n_pending": n_pending,
        "n_logs": len(logs),
        "n_logs_scored": len(log_fits),
        "n_items": len(items),
        "slot": slot,
        "gates": gates,
        "complete": (counted + n_pending) > 0 and n_pending == 0,
        "reason": None if available else "No Phase-E cells persisted yet.",
    }


def phase_e_vector(miner_id: str, *, state=None) -> dict:
    """Phase-E Fit of ``miner_id`` across all configured classes."""
    order = ("structured", "semi", "loosely")
    configured = set(fb_items.config_loader.load().keys()) if hasattr(
        fb_items, "config_loader") else set()
    # Defer the import to avoid a circular reference at module load time.
    if not configured:
        from flex_compare.fragebogen import config_loader as _cl
        configured = set(_cl.load().keys())
    fits: dict[str, Optional[float]] = {}
    details: dict[str, dict] = {}
    for cls in order:
        if cls in configured:
            res = phase_e_fit(miner_id, cls, state=state)
            fits[cls] = res["fit"]
            details[cls] = res
        else:
            fits[cls] = None

    scorable = {c: f for c, f in fits.items() if f is not None}
    home = max(scorable, key=scorable.get) if scorable else None
    return {
        "miner": miner_id,
        "phase": "E",
        "fits": fits,
        "home_class": home,
        "details": details,
        "complete": configured == set(order),
    }


def _safe_log_id(log_path: Path) -> Optional[str]:
    try:
        return result_cache.compute_log_id(Path(log_path))
    except Exception:
        return None
