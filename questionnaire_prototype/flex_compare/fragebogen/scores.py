"""DEPRECATED: backward-compat shim around :mod:`phase_e_answers`.

The Phase-E cell store now uses a unified ``value`` field (0/1/2 / ``"nz"`` /
``"ja"`` / ``"nein"``). This shim keeps the legacy ``score: int`` API alive
for the existing Tab-3 UI; new code should use the ``value`` field directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flex_compare.fragebogen import phase_e_answers as _phase_e_answers


def set_root(path: Optional[Path]) -> None:
    _phase_e_answers.set_root(path)


def _translate(payload: Optional[dict]) -> Optional[dict]:
    if payload is None:
        return None
    out = dict(payload)
    raw = payload.get("value")
    out["score"] = raw if isinstance(raw, int) else None
    return out


def save_score(
    *,
    log_id: str,
    slot: str,
    item_id: str,
    score: Optional[int],
    note: str = "",
    log_stem: str = "",
    instance_id: str = "",
    instance_label: str = "",
    metric_evidence: Optional[dict] = None,
) -> Path:
    return _phase_e_answers.save_score(
        log_id=log_id, slot=slot, item_id=item_id, value=score, note=note,
        log_stem=log_stem, instance_id=instance_id,
        instance_label=instance_label, metric_evidence=metric_evidence)


def load_score(log_id: str, slot: str, item_id: str) -> Optional[dict]:
    return _translate(_phase_e_answers.load_score(log_id, slot, item_id))


def load_all_scores(log_id: str) -> dict[tuple[str, str], dict]:
    return {k: _translate(v)
            for k, v in _phase_e_answers.load_all_scores(log_id).items()}
