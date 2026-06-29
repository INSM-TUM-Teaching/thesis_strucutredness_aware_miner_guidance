"""Item catalogue + log-class routing — backed by the editable YAML config.

The Fragebogen lives in editable per-class YAML files under ``config/``
(:mod:`flex_compare.fragebogen.config_loader`). This module flattens the
``phase_t`` and ``phase_e`` blocks of every class into a unified ``ITEMS``
catalogue and exposes phase-aware accessors.

Public API:
* :data:`ITEMS`              — dict[id → entry] across all phases/classes.
* :func:`get_item`           — entry with ``id`` injected, or ``None``.
* :func:`phase_t_items_for_class` / :func:`phase_e_items_for_class`
                              — per-class item lists (in YAML order).
* :func:`phase_e_gate_for_class` — Semi gate or ``None``.
* :func:`stufe1_for_class`   — ungescort capability/routing entries.
* :func:`meta_for_class`     — class meta block.
* :func:`phase_t_seed`       — per-miner Ja/Nein/n.z. seed for a T item.
* :func:`class_for_log`      — derive class from log filename.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flex_compare.fragebogen import config_loader
from flex_compare.internal.experiment_reports import infer_experiment_class


# ── catalogue assembly (from YAML) ───────────────────────────────────────────
def _build_items() -> dict[str, dict]:
    """Flatten every class config's phase_t + phase_e into an id-keyed
    catalogue, injecting the owning ``class`` into each entry."""
    catalogue: dict[str, dict] = {}
    for cls, cfg in config_loader.load().items():
        for item in cfg["phase_t"] + cfg["phase_e"]:
            entry = {k: v for k, v in item.items() if k != "id"}
            entry["class"] = cls
            catalogue[item["id"]] = entry
    return catalogue


# Built once at import; call :func:`refresh` after editing a YAML file at
# runtime (tests do this).
ITEMS: dict[str, dict] = _build_items()


def refresh() -> None:
    """Re-read the YAML config and rebuild the in-memory catalogue in place."""
    config_loader.reload()
    rebuilt = _build_items()
    ITEMS.clear()
    ITEMS.update(rebuilt)


def get_item(item_id: str) -> Optional[dict]:
    """Return the catalogue entry (with ``id`` injected) for ``item_id`` or
    ``None`` if no such item is registered."""
    entry = ITEMS.get(item_id)
    if entry is None:
        return None
    return {"id": item_id, **entry}


def _items_block(cls: Optional[str], block: str) -> list[dict]:
    if not cls:
        return []
    cfg = config_loader.load().get(cls)
    if cfg is None:
        return []
    return [{"id": item["id"], "class": cls,
             **{k: v for k, v in item.items() if k != "id"}}
            for item in cfg.get(block) or []]


def phase_t_items_for_class(cls: Optional[str]) -> list[dict]:
    """Phase-T (binary Ja/Nein) items for ``cls`` in YAML order."""
    return _items_block(cls, "phase_t")


def phase_e_items_for_class(cls: Optional[str]) -> list[dict]:
    """Phase-E (0/1/2) items for ``cls`` in YAML order."""
    return _items_block(cls, "phase_e")


# ── Backward-compat aliases for the existing Tab-3 UI ────────────────────────
# The UI iterates over items expecting a numeric ``score`` scale plus a
# per-miner ``phase_a`` seed dict. Phase T is binary (1 pt per Yes), so Ja/Nein
# maps to a 1/0 scale (Ja=1, Nein=0); phase_t_seed → phase_a (ja→1, nein→0,
# nz→null).

def _t_to_legacy(item: dict) -> dict:
    scale: list[dict] = []
    for row in item.get("scale", []):
        if row["value"] == "ja":
            scale.append({"score": 1, "label": f"Yes — {row['label']}"})
        elif row["value"] == "nein":
            scale.append({"score": 0, "label": f"No — {row['label']}"})
    legacy_phase_a: dict[str, dict] = {}
    for miner_id, entry in (item.get("phase_t_seed") or {}).items():
        v = entry.get("value")
        score = 1 if v == "ja" else 0 if v == "nein" else None
        legacy_phase_a[miner_id] = {"score": score, "note": entry.get("note", "")}
    legacy = dict(item)
    legacy["scale"] = scale
    legacy["phase_a"] = legacy_phase_a
    legacy.setdefault("route", "observation")
    legacy.setdefault("metric_keys", [])
    legacy.setdefault("f3", item.get("doku_hint"))
    return legacy


def items_for_class(cls: Optional[str]) -> list[dict]:
    """Legacy alias: Phase-T items in the legacy 2/1/0 ``score`` shape."""
    return [_t_to_legacy(item) for item in phase_t_items_for_class(cls)]


def items_phase_b_for_class(cls: Optional[str]) -> list[dict]:
    """Legacy alias for Phase-E items (already 0/1/2)."""
    return phase_e_items_for_class(cls)


def phase_a_profile(item_id: str) -> dict[str, dict]:
    """Legacy alias: per-miner seed of a T-item translated to legacy scores."""
    legacy: dict[str, dict] = {}
    for miner_id, entry in phase_t_seed(item_id).items():
        v = entry.get("value")
        score = 1 if v == "ja" else 0 if v == "nein" else None
        legacy[miner_id] = {"score": score, "note": entry.get("note", "")}
    return legacy


def phase_e_gate_for_class(cls: Optional[str]) -> Optional[dict]:
    """Phase-E gate descriptor for ``cls`` (Semi only) or ``None``."""
    if not cls:
        return None
    cfg = config_loader.load().get(cls)
    if cfg is None:
        return None
    gate = cfg.get("phase_e_gate")
    if gate is None:
        return None
    return {"class": cls, **gate}


def stufe1_for_class(cls: Optional[str]) -> list[dict]:
    """Stufe-1 capability/routing questions for ``cls`` (ungescort)."""
    if not cls:
        return []
    cfg = config_loader.load().get(cls)
    return list(cfg["stufe1"]) if cfg else []


def meta_for_class(cls: Optional[str]) -> Optional[dict]:
    """Class ``meta`` block (phase_t_max, phase_e_max, combination, …)."""
    if not cls:
        return None
    cfg = config_loader.load().get(cls)
    return cfg["meta"] if cfg else None


def phase_t_seed(item_id: str) -> dict[str, dict]:
    """Per-miner Phase-T seed (``{miner_id: {value, note}}``) for ``item_id``.

    Empty dict if the item carries no ``phase_t_seed`` block."""
    entry = ITEMS.get(item_id)
    if entry is None:
        return {}
    return dict(entry.get("phase_t_seed") or {})


def class_for_log(log_path: Optional[str]) -> Optional[str]:
    """Derive the structuredness class from the log filename.

    ``log_path`` may be a filesystem path or a bare filename. Returns one of
    ``"structured"`` / ``"semi"`` / ``"loosely"``, or ``None`` if the stem
    does not follow the ``LogNN_<class>`` convention.
    """
    if not log_path:
        return None
    stem = Path(log_path).stem
    _sentinel = "__no_class__"
    result = infer_experiment_class(stem, default=_sentinel)
    return None if result == _sentinel else result
