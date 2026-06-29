"""Per-cell Phase-E score persistence (0/1/2 + n.z. + Gate ja/nein).

One JSON file per ``(log_id, slot, item_id)`` cell under
``<PROJECT_ROOT>/.miner_cache/phase_e_eval/<log_id>/<slot>__<item_id>.json``.
Writes are atomic (temp + ``os.replace``); reads return ``None`` for missing
cells.

The on-disk shape is a unified ``value`` field that accepts integers (0/1/2
for scored items), the string ``"nz"`` (n.z. = 0 markiert, Doc §5), and
``"ja"`` / ``"nein"`` for the Semi gate (``E-Sm-Gate``). ``None`` clears.

``log_id`` and ``slot`` follow the same conventions the runner uses:
``log_id = result_cache.compute_log_id(log_path)`` and
``slot = runner.slot_id(type_id, config)``.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from flex_compare.internal.shared.paths import PROJECT_ROOT


_SUBDIR = "phase_e_eval"

CellValue = Union[int, str, None]

_root_override: Optional[Path] = None


def set_root(path: Optional[Path]) -> None:
    """Override the score-cache root (for tests). Pass ``None`` to revert."""
    global _root_override
    _root_override = Path(path) if path is not None else None


def _root() -> Path:
    if _root_override is not None:
        return _root_override
    return PROJECT_ROOT / ".miner_cache" / _SUBDIR


def _score_path(log_id: str, slot: str, item_id: str) -> Path:
    return _root() / log_id / f"{slot}__{item_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _validate_value(value: CellValue) -> None:
    if value is None:
        return
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        raise ValueError(f"value must not be a bool, got {value!r}")
    if isinstance(value, int) and 0 <= value <= 2:
        return
    if isinstance(value, str) and value in ("nz", "ja", "nein"):
        return
    raise ValueError(
        f"value must be 0/1/2, 'nz', 'ja'/'nein' (gate), or None — got {value!r}")


def save_score(
    *,
    log_id: str,
    slot: str,
    item_id: str,
    value: CellValue,
    note: str = "",
    log_stem: str = "",
    instance_id: str = "",
    instance_label: str = "",
    metric_evidence: Optional[dict] = None,
) -> Path:
    """Atomically write the score cell for ``(log_id, slot, item_id)`` to disk."""
    if not log_id or not slot or not item_id:
        raise ValueError("log_id, slot and item_id must all be non-empty")
    _validate_value(value)
    payload = {
        "item_id": item_id,
        "log_id": log_id,
        "log_stem": log_stem,
        "slot": slot,
        "instance_id": instance_id,
        "instance_label": instance_label,
        "value": value,
        "note": note or "",
        "metric_evidence": dict(metric_evidence or {}),
        "updated_at": _now_iso(),
    }
    path = _score_path(log_id, slot, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_score(log_id: str, slot: str, item_id: str) -> Optional[dict]:
    """Return the persisted score cell or ``None`` if not yet rated."""
    path = _score_path(log_id, slot, item_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_all_scores(log_id: str) -> dict[tuple[str, str], dict]:
    """All persisted cells for ``log_id`` keyed by ``(slot, item_id)``."""
    out: dict[tuple[str, str], dict] = {}
    log_dir = _root() / log_id
    if not log_dir.is_dir():
        return out
    for path in log_dir.glob("*__*.json"):
        if path.name.endswith(".tmp"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        slot = str(payload.get("slot") or "")
        item_id = str(payload.get("item_id") or "")
        if slot and item_id:
            out[(slot, item_id)] = payload
    return out
