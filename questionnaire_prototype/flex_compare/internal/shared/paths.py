"""Project-root resolution for shared modules in the standalone flex_compare repo.

``PROJECT_ROOT`` resolves to the top-level repo root (``flex_compare/`` —
the dir that holds ``pyproject.toml``, ``flex_compare/`` and ``tools/``).
Override with the ``FLEX_PROJECT_ROOT`` env var if you want caches /
binaries to live elsewhere (e.g. on a faster scratch disk during a CI run).
"""
from __future__ import annotations

import os
from pathlib import Path

# parents[3] from flex_compare/flex_compare/internal/shared/paths.py
#  → flex_compare/ (the standalone repo root, NOT the inner Python package).
_DEFAULT_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

_env_override = os.environ.get("FLEX_PROJECT_ROOT")
PROJECT_ROOT: Path = Path(_env_override).expanduser().resolve() if _env_override else _DEFAULT_PROJECT_ROOT
