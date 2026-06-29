"""Subprocess wrapper around the Rust ARM (Activity Relationship Matrix) tool.

Invokes ``matrix_classifier --print-matrix`` (Andree et al. algorithm,
implemented in
``tools/automated-process-classification/``) on an XES log and returns the
parsed JSON.

A thin file cache under ``.miner_cache/arm/`` keys results by
``(log_content_hash, temporal_threshold, existential_threshold)`` so repeat
opens of the ARM tab are instant.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# Resolve binary + cache via PROJECT_ROOT (honors FLEX_PROJECT_ROOT override).
from flex_compare.internal.shared.paths import PROJECT_ROOT as _REPO_ROOT  # noqa: E402

_DEFAULT_BINARY = (
    _REPO_ROOT
    / "tools"
    / "automated-process-classification"
    / "target"
    / "release"
    / "matrix_classifier"
)
_CACHE_ROOT = _REPO_ROOT / ".miner_cache" / "arm"


class ArmCell(TypedDict, total=False):
    from_: str  # JSON key is "from"
    to: str
    temporal_type: Optional[str]
    temporal_direction: Optional[str]
    existential_type: Optional[str]
    existential_direction: Optional[str]
    code: str


class ArmThresholds(TypedDict):
    temporal: float
    existential: float


class ArmResult(TypedDict):
    activities: list[str]
    thresholds: ArmThresholds
    classification: str
    matched_rules: list[str]
    percentages: dict[str, float]
    cells: list[dict[str, Any]]  # raw cells with "from" key (Python keyword-safe)


class ArmRunnerError(RuntimeError):
    pass


def _binary_path() -> Path:
    override = os.environ.get("ARM_BINARY")
    if override:
        return Path(override)
    return _DEFAULT_BINARY


def _short_hash(log_path: Path) -> str:
    return hashlib.sha1(log_path.read_bytes()).hexdigest()[:12]


def _cache_path(log_path: Path, temporal: float, existential: float) -> Path:
    digest = _short_hash(log_path)
    fname = f"{log_path.stem}__{digest}__t{temporal:.3f}_e{existential:.3f}.json"
    return _CACHE_ROOT / fname


def run_arm(
    log_path: Path,
    *,
    temporal_threshold: float = 1.0,
    existential_threshold: float = 1.0,
    use_cache: bool = True,
) -> ArmResult:
    """Compute the ARM for ``log_path``.

    Raises ``ArmRunnerError`` if the binary is missing, the log cannot be
    parsed, or the JSON output is malformed.
    """
    log_path = Path(log_path)
    if not log_path.is_file():
        raise ArmRunnerError(f"Log file not found: {log_path}")

    if not (0.0 <= temporal_threshold <= 1.0):
        raise ArmRunnerError(
            f"temporal_threshold must be in [0, 1]; got {temporal_threshold}"
        )
    if not (0.0 <= existential_threshold <= 1.0):
        raise ArmRunnerError(
            f"existential_threshold must be in [0, 1]; got {existential_threshold}"
        )

    cache_file = _cache_path(log_path, temporal_threshold, existential_threshold)
    if use_cache and cache_file.is_file():
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("ARM cache read failed (%s); recomputing", e)

    binary = _binary_path()
    if not binary.is_file():
        raise ArmRunnerError(
            f"ARM binary not found at {binary}. Build it with:\n"
            f"  (cd {_REPO_ROOT}/tools/automated-process-classification && "
            f"cargo build --release)\n"
            f"Or set ARM_BINARY to the binary path."
        )

    cmd = [
        str(binary),
        "--file-path",
        str(log_path),
        "--temporal-threshold",
        f"{temporal_threshold}",
        "--existential-threshold",
        f"{existential_threshold}",
        "--print-matrix",
    ]
    logger.info("Running ARM tool: %s", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError as e:
        raise ArmRunnerError(f"Failed to invoke ARM binary: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise ArmRunnerError(
            f"ARM computation timed out after 120s for {log_path.name}"
        ) from e

    if completed.returncode != 0:
        raise ArmRunnerError(
            f"ARM binary exited {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        result: ArmResult = json.loads(completed.stdout)
    except json.JSONDecodeError as e:
        raise ArmRunnerError(
            f"ARM binary output was not valid JSON: {e}\n--- stdout ---\n"
            f"{completed.stdout[:500]}"
        ) from e

    if use_cache:
        try:
            _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
            with cache_file.open("w", encoding="utf-8") as f:
                json.dump(result, f)
        except OSError as e:
            logger.warning("ARM cache write failed (%s); ignoring", e)

    return result


@dataclass(frozen=True)
class CellLookup:
    """Index helper for fast (from, to) → cell lookup in a matrix UI."""

    by_pair: dict[tuple[str, str], dict[str, Any]]

    @classmethod
    def from_result(cls, result: ArmResult) -> "CellLookup":
        return cls({(c["from"], c["to"]): c for c in result["cells"]})
