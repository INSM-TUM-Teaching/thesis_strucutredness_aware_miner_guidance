"""Per-cell Phase-T answer persistence (Ja/Nein/n.z./null).

The Phase-T questionnaire is answered interactively as a survey in Tab 3.
One JSON file per ``(class, miner_id, item_id)`` cell under
``<PROJECT_ROOT>/.miner_cache/phase_t_eval/<class>/<miner_id>__<item_id>.json``.

The YAML ``phase_t_seed`` remains the **default pre-fill**; once a cell is
saved on disk, that answer overlays the seed in
:mod:`flex_compare.fragebogen.phase_t`. Writes are atomic (temp +
``os.replace``); reads return ``None`` for missing cells.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flex_compare.internal.shared.paths import PROJECT_ROOT


_SUBDIR = "phase_t_eval"
_ALLOWED = ("ja", "nein", "nz", None)

_root_override: Optional[Path] = None


def set_root(path: Optional[Path]) -> None:
    """Override the answers root (for tests). Pass ``None`` to revert."""
    global _root_override
    _root_override = Path(path) if path is not None else None


def _root() -> Path:
    if _root_override is not None:
        return _root_override
    return PROJECT_ROOT / ".miner_cache" / _SUBDIR


_SAFE = re.compile(r"[^A-Za-z0-9._\-]+")


def _slug(value: str) -> str:
    return _SAFE.sub("_", str(value)).strip("_")


def _answer_path(cls: str, miner_id: str, item_id: str) -> Path:
    return _root() / _slug(cls) / f"{_slug(miner_id)}__{_slug(item_id)}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def save_answer(
    *,
    cls: str,
    miner_id: str,
    item_id: str,
    value: Optional[str],
    note: str = "",
) -> Path:
    """Atomically write the Phase-T answer for ``(cls, miner_id, item_id)``.

    ``value`` must be ``"ja"`` / ``"nein"`` / ``"nz"`` (n.z. = 0 markiert) or
    ``None`` (explicit pending / cleared). Returns the written path.
    """
    if not cls or not miner_id or not item_id:
        raise ValueError("cls, miner_id and item_id must all be non-empty")
    if value not in _ALLOWED:
        raise ValueError(
            f"value must be one of {_ALLOWED!r}, got {value!r}")
    payload = {
        "class": cls,
        "miner_id": miner_id,
        "item_id": item_id,
        "value": value,
        "note": note or "",
        "updated_at": _now_iso(),
    }
    path = _answer_path(cls, miner_id, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_answer(cls: str, miner_id: str, item_id: str) -> Optional[dict]:
    """Return the persisted Phase-T answer or ``None`` if not yet given."""
    path = _answer_path(cls, miner_id, item_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_all_answers(cls: str) -> dict[tuple[str, str], dict]:
    """All persisted answers for ``cls`` keyed by ``(miner_id, item_id)``."""
    out: dict[tuple[str, str], dict] = {}
    class_dir = _root() / _slug(cls)
    if not class_dir.is_dir():
        return out
    for path in class_dir.glob("*__*.json"):
        if path.name.endswith(".tmp"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        miner = str(payload.get("miner_id") or "")
        item = str(payload.get("item_id") or "")
        if miner and item:
            out[(miner, item)] = payload
    return out
