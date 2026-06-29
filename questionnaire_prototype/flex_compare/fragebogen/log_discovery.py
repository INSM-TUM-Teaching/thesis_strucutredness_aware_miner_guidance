"""Find event logs that belong to a given structuredness class.

Scans a flat directory of ``Log*.xes`` files and groups them by the class
encoded in the filename (``Log01_structured.xes`` → ``structured``). Logs
whose stem does not follow the ``LogNN_<class>`` convention — e.g. the
``unstructured`` calibration logs or mixed-class names — are silently
skipped: the Phase-2 questionnaire is only defined for the three core
classes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from flex_compare.fragebogen.items import class_for_log


def logs_for_class(cls: str, log_dir: Path) -> list[Path]:
    """All ``.xes`` files in ``log_dir`` whose filename class matches ``cls``.

    Sorted by filename so the run-view order is stable (Log01, Log04, Log05, …).
    """
    if not cls or not log_dir.is_dir():
        return []
    matches: list[Path] = []
    for path in sorted(log_dir.glob("*.xes")):
        if class_for_log(str(path)) == cls:
            matches.append(path)
    return matches


def logs_by_class(log_dir: Path,
                  classes: Iterable[str] = ("structured", "semi", "loosely"),
                  ) -> dict[str, list[Path]]:
    """Group every ``.xes`` in ``log_dir`` into the requested classes."""
    out: dict[str, list[Path]] = {c: [] for c in classes}
    if not log_dir.is_dir():
        return out
    for path in sorted(log_dir.glob("*.xes")):
        cls = class_for_log(str(path))
        if cls in out:
            out[cls].append(path)
    return out
