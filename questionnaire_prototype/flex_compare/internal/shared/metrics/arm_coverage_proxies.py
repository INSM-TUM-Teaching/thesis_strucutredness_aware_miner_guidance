"""Cached SF-2 ARM-coverage proxies.

A thin, defensive wrapper around :mod:`miners.shared.arm_coverage` (the engine
is reused, never duplicated). It resolves the *dominant*-only ARM-relation
coverage for a ``(miner, log)`` and exposes it as flat, neutral evidence keys
the UI can look up and render as chips.

SF-2 reading (e2-measurement-spec §0.3, §7): ARM-coverage is a *qualitative
structure hint*, not a numeric verdict. The ARM is the input/ground-truth;
using it as a yardstick is itself an open tension (§7). Hence these keys are
neutral evidence only — ``arm_suggested_category`` is a *non-binding
suggestion*, never an auto-grade.

Subprocess discipline: ``arm_runner.run_arm`` (the Rust ARM binary) is invoked
only here, behind an ``lru_cache`` + the on-disk ARM cache. The pure,
result-based ``metric_proxies._extract_item_metrics`` stays subprocess-free —
callers merge these proxies in at the sites where ``log_path`` is already known.

``_sf2_scale`` defers to ``comparison_app.ui.characteristics`` when reachable so
the legacy app keeps its config-driven SF-2 scale; the static fallback covers
the flex_compare app, which has no characteristics config.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from flex_compare.internal.shared import arm_coverage
from flex_compare.internal.shared.arm_coverage import CoverageReport
from flex_compare.internal.shared.arm_runner import ArmRunnerError, run_arm
from flex_compare.internal.shared.cache import result_cache

logger = logging.getLogger(__name__)

# Flat, neutral evidence keys exposed to the UI. ``None`` == "not available".
ARM_COVERAGE_KEYS: tuple[str, ...] = (
    "arm_native_ratio",
    "arm_forced_ratio",
    "arm_missing_ratio",
    "arm_coverage_score",
    "arm_dominant_n",
    "arm_suggested_category",
)

# §7 caveat — single-sourced so the ARM tab and the SF-2 proxy callout render
# the exact same wording.
SECTION7_CAVEAT = (
    "ARM coverage = qualitative structural hint. The ARM is input / "
    "ground truth; using it as a yardstick is an open tension (§7) — not a "
    "hard score."
)

# Fallback for the SF-2 grade_scale (characteristics_config.yaml). The suggested
# category is sourced from the live config when reachable; this mirrors it.
_FALLBACK_SF2_SCALE: tuple[str, ...] = (
    "structure-faithful (native)",
    "mode-appropriate mixed",
    "mostly forced",
    "ignored / degenerate",
)


def _empty_proxies() -> dict[str, object]:
    return {k: None for k in ARM_COVERAGE_KEYS}


def _sf2_scale() -> tuple[str, ...]:
    """The SF-2 grade_scale categories, read from comparison_app config with
    a static fallback. flex_compare has no characteristics config and
    transparently falls back."""
    try:
        from miners.comparison_app.ui import characteristics

        for c in characteristics.list_characteristics():
            if c.get("axis") == "SF" and c.get("grade_scale"):
                return tuple(str(x) for x in c["grade_scale"])
    except Exception:  # config not loadable → fall back, never crash
        pass
    return _FALLBACK_SF2_SCALE


def _suggest_category(
    native_ratio: Optional[float],
    forced_ratio: Optional[float],
    missing_ratio: Optional[float],
) -> Optional[str]:
    """Non-binding category suggestion from the verdict mix.

    NOT a score and NOT a grade (e2 §0.3): a transparent read of the dominant
    relation mix, mapped onto the SF-2 grade_scale. The rater stays the decider
    — the UI shows this as a 'suggestion', never a checkmark. The cut points
    are generic structural reads, deliberately *not* tuned to any calibration
    miner.
    """
    scale = _sf2_scale()
    if native_ratio is None or forced_ratio is None or missing_ratio is None:
        return None
    if len(scale) < 4:
        return None
    if missing_ratio >= 0.5:
        return scale[3]  # ignored / degenerate
    if native_ratio >= 0.8:
        return scale[0]  # structure-faithful (native)
    if forced_ratio > native_ratio:
        return scale[2]  # mostly forced
    return scale[1]      # mode-appropriate mixed


def _flat_from_report(report: Optional[CoverageReport]) -> dict[str, object]:
    """Project a dominant-only :class:`CoverageReport` onto the flat UI keys.

    ``arm_dominant_n`` is the count of *scorable* dominant relations
    (native + forced + missing); the three ratios are taken over that same
    denominator (they sum to 1). ``not_applicable`` dominant relations are a
    fairness exclusion and are not counted here.
    """
    if report is None:
        return _empty_proxies()
    counts = report.counts or {}
    native = counts.get("native", 0)
    forced = counts.get("forced", 0)
    missing = counts.get("missing", 0)
    denom = native + forced + missing
    if denom == 0:
        out = _empty_proxies()
        out["arm_dominant_n"] = 0
        return out
    native_ratio = native / denom
    forced_ratio = forced / denom
    missing_ratio = missing / denom
    score = report.coverage_score
    return {
        "arm_native_ratio": round(native_ratio, 4),
        "arm_forced_ratio": round(forced_ratio, 4),
        "arm_missing_ratio": round(missing_ratio, 4),
        "arm_coverage_score": None if score is None else round(score, 4),
        "arm_dominant_n": denom,
        "arm_suggested_category": _suggest_category(
            native_ratio, forced_ratio, missing_ratio
        ),
    }


def _coverage_report(
    miner: str, log_path: str | Path, *, arm: Optional[dict], dominant_only: bool
) -> Optional[CoverageReport]:
    """Shared, defensive ARM-coverage resolution for ``(miner, log)``.

    Reuses ``arm`` (an :class:`~miners.shared.arm_runner.ArmResult`-shaped dict,
    e.g. the one already computed in the session) when given, else runs the
    cached ARM. Builds the model index from the cached miner result and runs the
    engine. ``dominant_only`` only trims the displayed ``verdicts`` (the score is
    unaffected — see :func:`miners.shared.arm_coverage.map_coverage`). Never
    raises — a missing cache, missing model JSON, or an unavailable ARM binary
    all degrade to ``None`` so the UI can fall back to 'n/a'.
    """
    try:
        path = Path(log_path)
        if not path.is_file():
            return None
        if arm is None:
            arm = run_arm(path)  # disk-cached
        log_id = result_cache.compute_log_id(path)
        entry = result_cache.lookup(miner, log_id)
        if entry is None:
            return None
        paradigm = arm_coverage._MINER_TO_PARADIGM.get(miner)
        if paradigm is None:
            return None
        result_data = result_cache.rehydrate(entry)
        idx = arm_coverage.load_model_index(miner, result_data, log_path=path)
        return arm_coverage.map_coverage(
            arm, idx, paradigm, log_id, dominant_only=dominant_only
        )
    except (ArmRunnerError, FileNotFoundError, KeyError, ValueError, OSError) as exc:
        logger.debug("ARM coverage unavailable for %s/%s: %s", miner, log_path, exc)
        return None
    except Exception as exc:  # defensive: proxy resolution must never crash the UI
        logger.warning("Unexpected ARM coverage failure for %s/%s: %s",
                       miner, log_path, exc)
        return None


def dominant_coverage_report(
    miner: str, log_path: str | Path, *, arm: Optional[dict] = None
) -> Optional[CoverageReport]:
    """Dominant-only ARM coverage for ``(miner, log)``; ``None`` on any gap.

    ``verdicts`` lists only the log's *dominant* (present) relations, so the
    per-relation table is not swamped by the O(n²) ``correctly_absent`` pairs.
    Use this for the table view, not the matrix overlay.
    """
    return _coverage_report(miner, log_path, arm=arm, dominant_only=True)


def full_coverage_report(
    miner: str, log_path: str | Path, *, arm: Optional[dict] = None
) -> Optional[CoverageReport]:
    """Full ARM coverage for ``(miner, log)`` — *every* relation in ``verdicts``.

    Unlike :func:`dominant_coverage_report`, ``verdicts`` carries the present
    **and** absent (``correctly_absent`` / ``spurious``) relations, which is what
    the per-cell matrix overlay needs to colour every cell. ``None`` on any gap
    (no cached model, no ARM binary, …) so the UI can fall back to 'n/a'.
    """
    return _coverage_report(miner, log_path, arm=arm, dominant_only=False)


def _cache_version_token(miner: str, log_path: str | Path) -> Optional[int]:
    """A token that bumps whenever the cached model for ``(miner, log)`` changes.

    ``result_cache.store`` atomically swaps in a freshly written
    ``result_data.json`` on every miner run; its mtime therefore uniquely
    versions the cached model without re-reading it. Folding this token into the
    lru key makes the memo **recompute-aware**: a new run (e.g. a fresh Fusion
    model) invalidates the cached coverage instead of returning a stale value.
    ``None`` when there is no cached entry yet.
    """
    try:
        path = Path(log_path)
        if not path.is_file():
            return None
        log_id = result_cache.compute_log_id(path)
        entry = result_cache.lookup(miner, log_id)
        if entry is None:
            return None
        return entry.result_data_path.stat().st_mtime_ns
    except Exception:
        return None


@lru_cache(maxsize=512)
def _proxies_cached(
    miner: str, log_path_str: str, version: Optional[int]
) -> dict[str, object]:
    # `version` is part of the key (see _cache_version_token): a fresh miner run
    # rewrites the cached model, bumps the token, and forces a recompute here.
    return _flat_from_report(dominant_coverage_report(miner, log_path_str, arm=None))


def arm_coverage_proxies(
    miner: str, log_path: str | Path, *, arm: Optional[dict] = None
) -> dict[str, object]:
    """Flat, neutral SF-2 ARM-coverage evidence for ``(miner, log)``.

    Keys: :data:`ARM_COVERAGE_KEYS`. All ``None`` when coverage is unavailable
    (no cached result, no ARM binary, …) so callers can merge unconditionally.

    Pass ``arm`` (already computed for the session) to skip the ARM subprocess;
    that path is computed fresh each call. Without ``arm`` the result is memoised
    per ``(miner, log_path, cache_version)`` on top of the on-disk ARM cache —
    the cache_version makes the memo recompute-aware, so re-running a miner
    refreshes the coverage rather than returning a stale value.
    """
    log_path_str = str(Path(log_path))
    if arm is not None:
        return _flat_from_report(dominant_coverage_report(miner, log_path_str, arm=arm))
    version = _cache_version_token(miner, log_path_str)
    return dict(_proxies_cached(miner, log_path_str, version))
