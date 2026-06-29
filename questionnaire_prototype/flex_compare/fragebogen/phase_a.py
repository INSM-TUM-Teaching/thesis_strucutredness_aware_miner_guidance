"""DEPRECATED: backward-compat shim around :mod:`phase_t`.

The questionnaire moved to a T+E architecture (Doc §0): Phase T is binary
Ja/Nein, Phase E is 0/1/2 + n.z. This shim keeps the old ``phase_a`` API
working for the existing Tab-3 UI by translating field names back to the
legacy ``score`` shape:

* ``"ja"`` → ``2``  (full point in legacy 0/1/2)
* ``"nein"`` → ``0``
* ``"nz"`` / ``None`` → ``None`` (legacy n/a)

New code should import :mod:`flex_compare.fragebogen.phase_t` directly.
"""
from __future__ import annotations

from typing import Optional

from flex_compare.fragebogen import phase_t as _phase_t


def _value_to_score(value) -> Optional[int]:
    if value == "ja":
        return 2
    if value == "nein":
        return 0
    return None  # nz / None → legacy n/a


def _translate(res: dict) -> dict:
    out = dict(res)
    per_item: dict[str, dict] = {}
    for item_id, cell in (res.get("per_item") or {}).items():
        per_item[item_id] = {
            "score": _value_to_score(cell.get("value")),
            "note": cell.get("note", ""),
            "source": cell.get("source", "seed"),
        }
    out["per_item"] = per_item
    out["max"] = 2 * (res.get("n_ja", 0) + res.get("n_nein", 0))
    out["points"] = 2 * res.get("n_ja", 0)
    out["n_scored"] = res.get("n_ja", 0) + res.get("n_nein", 0)
    out["n_nb"] = res.get("n_pending", 0) + res.get("n_nz", 0)
    return out


def configured_classes() -> tuple[str, ...]:
    return _phase_t.configured_classes()


def phase_a_miners(cls: str) -> list[str]:
    return _phase_t.phase_t_miners(cls)


def phase_a_item_score(item_id: str, miner_id: str) -> Optional[int]:
    return _value_to_score(_phase_t.phase_t_item_value(item_id, miner_id))


def phase_a_fit(miner_id: str, cls: str = "structured") -> dict:
    return _translate(_phase_t.phase_t_fit(miner_id, cls))


def phase_a_fit_with_answers(miner_id: str, cls: str = "structured") -> dict:
    return _translate(_phase_t.phase_t_fit_with_answers(miner_id, cls))


def phase_a_vector(miner_id: str) -> dict:
    vec = _phase_t.phase_t_vector(miner_id, with_answers=False)
    return {**vec, "details": {c: _translate(d) for c, d in vec["details"].items()}}


def phase_a_vector_with_answers(miner_id: str) -> dict:
    vec = _phase_t.phase_t_vector(miner_id, with_answers=True)
    return {**vec, "details": {c: _translate(d) for c, d in vec["details"].items()}}
