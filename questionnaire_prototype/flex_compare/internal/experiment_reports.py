from __future__ import annotations

import re
from pathlib import Path


_LOG_CLASS_PATTERN = re.compile(
    r"^(?P<log_id>Log\d+)_(?P<class_name>structured|semiStructured|looselyStructured)$",
    re.IGNORECASE,
)

_CLASS_DIRS = {
    "structured": "structured",
    "semistructured": "semi",
    "looselystructured": "loosely",
}


def infer_experiment_class(log_name: str, *, default: str | None = None) -> str:
    match = _LOG_CLASS_PATTERN.fullmatch(log_name.strip())
    if match is None:
        if default is not None:
            return default
        raise ValueError(
            "Unsupported log name. Expected exactly one of the classes "
            "'structured', 'semiStructured', or 'looselyStructured' in the file stem."
        )
    return _CLASS_DIRS[match.group("class_name").lower()]


def is_supported_experiment_log_name(log_name: str) -> bool:
    return _LOG_CLASS_PATTERN.fullmatch(log_name.strip()) is not None


def build_report_output_dir(
    output_root: Path,
    log_name: str,
    miner_name: str,
    *,
    default_class: str = "custom",
) -> Path:
    experiment_class = infer_experiment_class(log_name, default=default_class)
    return output_root / experiment_class / log_name / miner_name
