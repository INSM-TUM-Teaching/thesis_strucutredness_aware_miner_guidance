"""DEPRECATED: backward-compat shim around :mod:`phase_e`.

The empirical leg is now Phase E (Doc §3). This shim keeps the legacy
``phase_b`` API working for the existing Tab-3 UI: translates the new
``value`` field (which accepts 0/1/2 + ``"nz"`` + Gate ``"ja"``/``"nein"``)
into the legacy numeric ``score`` (n.z. and Gate collapse to ``None``).

New code should import :mod:`flex_compare.fragebogen.phase_e` directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flex_compare.fragebogen import phase_e as _phase_e


DEFAULT_LOG_DIR = _phase_e.DEFAULT_LOG_DIR
DEFAULT_LOGS_PER_CLASS = _phase_e.DEFAULT_LOGS_PER_CLASS


def phase_b_logs(cls: str, log_dir: Optional[Path] = None,
                  limit: int = DEFAULT_LOGS_PER_CLASS) -> list[Path]:
    return _phase_e.phase_e_logs(cls, log_dir, limit=limit)


def is_available(miner_id: str, cls: str = "structured", state=None) -> bool:
    return _phase_e.is_available(miner_id, cls, state=state)


def _value_to_score(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return None  # "nz" / "ja" / "nein" → legacy n/a


def phase_b_fit(miner_id: str, cls: str = "structured", *,
                 state=None, **_kwargs) -> dict:
    res = _phase_e.phase_e_fit(miner_id, cls, state=state)
    per_cell: dict[str, dict] = {}
    for key, cell in (res.get("per_cell") or {}).items():
        per_cell[key] = {**cell, "score": _value_to_score(cell.get("value"))}
    out = dict(res)
    out["per_cell"] = per_cell
    return out
