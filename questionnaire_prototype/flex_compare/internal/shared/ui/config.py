from __future__ import annotations

import shutil
from pathlib import Path


def build_paths(anchor_file: str) -> dict:
    """Return standard path constants rooted at the project root.

    Pass ``__file__`` from each miner's ``ui_app/utils/config.py``.
    The anchor is expected to live at:
      ``<project_root>/miners/<miner>/ui_app/utils/config.py``

    Returns a dict with keys:
        project_root, event_logs_dir, fallback_event_logs_dir,
        default_output_root, default_minerful_dir, package_dir,
        pandoc_available
    """
    # Vendored layout: utils/ -> ui_app/ -> <miner>/ -> internal/ -> flex_compare/ -> repo_root.
    # PROJECT_ROOT honours FLEX_PROJECT_ROOT, so we defer to it instead of
    # re-counting parents.
    from flex_compare.internal.shared.paths import PROJECT_ROOT

    utils_dir = Path(anchor_file).resolve().parent
    ui_app_dir = utils_dir.parent
    package_dir = ui_app_dir.parent
    project_root = PROJECT_ROOT

    return {
        "project_root": project_root,
        "package_dir": package_dir,
        "event_logs_dir": project_root / "data" / "with-case-ids",
        "fallback_event_logs_dir": project_root / "data" / "original",
        "default_output_root": project_root / "Experimente",
        "default_minerful_dir": project_root / "tools" / "MINERful",
        "pandoc_available": shutil.which("pandoc") is not None,
    }
