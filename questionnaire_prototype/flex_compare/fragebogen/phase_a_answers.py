"""DEPRECATED: backward-compat shim around :mod:`phase_t_answers`.

Translates the legacy ``score`` field to the new ``value`` field
(``"ja"`` / ``"nein"`` / ``"nz"`` / None). Phase T is binary (1 pt per Yes):

* ``score == 1`` → ``value == "ja"`` (``2`` also accepted as legacy "ja")
* ``score == 0`` → ``value == "nein"``
* ``score is None`` → ``value is None``

New code should use :mod:`flex_compare.fragebogen.phase_t_answers`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flex_compare.fragebogen import phase_t_answers as _phase_t_answers


def set_root(path: Optional[Path]) -> None:
    _phase_t_answers.set_root(path)


def _score_to_value(score) -> Optional[str]:
    if score is None:
        return None
    if score in (1, 2):  # 2 accepted for backward-compat with old encoding
        return "ja"
    if score == 0:
        return "nein"
    return None


def _value_to_score(value) -> Optional[int]:
    if value == "ja":
        return 1
    if value == "nein":
        return 0
    return None  # nz / None → legacy n/a


def save_answer(
    *,
    cls: str,
    miner_id: str,
    item_id: str,
    score: Optional[int],
    note: str = "",
) -> Path:
    return _phase_t_answers.save_answer(
        cls=cls, miner_id=miner_id, item_id=item_id,
        value=_score_to_value(score), note=note)


def _translate(payload: Optional[dict]) -> Optional[dict]:
    if payload is None:
        return None
    out = dict(payload)
    out["score"] = _value_to_score(payload.get("value"))
    return out


def load_answer(cls: str, miner_id: str, item_id: str) -> Optional[dict]:
    return _translate(_phase_t_answers.load_answer(cls, miner_id, item_id))


def load_all_answers(cls: str) -> dict[tuple[str, str], dict]:
    return {k: _translate(v)
            for k, v in _phase_t_answers.load_all_answers(cls).items()}
