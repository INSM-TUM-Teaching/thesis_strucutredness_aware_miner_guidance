from __future__ import annotations

from pathlib import Path

from flex_compare.internal.shared.ui.config import build_paths

_p = build_paths(__file__)

EVENT_LOGS_DIR: Path = _p["event_logs_dir"]
FALLBACK_EVENT_LOGS_DIR: Path = _p["fallback_event_logs_dir"]
DEFAULT_OUTPUT_ROOT: Path = _p["default_output_root"]
REFERENCE_MARKDOWN_PATH: Path = _p["package_dir"] / "README.md"
PANDOC_AVAILABLE: bool = _p["pandoc_available"]
