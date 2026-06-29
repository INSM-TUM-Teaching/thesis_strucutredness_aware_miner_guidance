"""Variant-level holdout splits for the OOS Phase-B Triangulation rollout.

Two strategies, picked automatically by `n_variants`:

- ``n_variants >= 10`` ⇒ **k-fold stratified by variant frequency**, with
  multiple repeats (different seeds). Within each repeat, variants are
  binned by frequency quartile and distributed across the k folds so
  every fold pulls one variant from each frequency bucket. This avoids
  the "all-rare-variants-in-one-fold" pathology that would otherwise
  inflate variance between folds.
- ``n_variants <  10`` ⇒ **leave-one-variant-out (LOO)**. Each variant
  is held out exactly once. No repeats (deterministic). Logs with
  ``n_variants < 5`` are additionally flagged as
  ``underpowered=True``; the experiment runs anyway so the §7 report
  can name *where* the OOS axis is informative vs. tautological.

Each call yields one (train_xes, test_xes, meta) per fold; the caller
decides how many folds to consume. Splits are written to disk and
cached: re-invocations with identical (log, seed, repeat, fold_idx)
return the cached artifacts.
"""

from __future__ import annotations

import json
import logging
import random
import warnings
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

warnings.filterwarnings("ignore")
logging.getLogger("pm4py").setLevel(logging.ERROR)

CASE_COL = "case:concept:name"
ACT_COL = "concept:name"
TIME_COL = "time:timestamp"

DEFAULT_K = 5
DEFAULT_REPEATS = 3
DEFAULT_SEEDS: Tuple[int, ...] = (42, 1337, 2026)
LOO_THRESHOLD = 10  # n_variants < LOO_THRESHOLD ⇒ LOO over variants
UNDERPOWERED_THRESHOLD = 5  # n_variants < UNDERPOWERED_THRESHOLD ⇒ also flag


@dataclass(frozen=True)
class FoldSpec:
    """Identifier for one fold."""

    repeat_idx: int  # 0..repeats-1 ; for LOO always 0
    fold_idx: int  # 0..k-1 (default) ; 0..n_variants-1 (LOO)
    seed: int
    split_kind: str  # "kfold_stratified" | "loo" | "loo_underpowered"

    @property
    def slug(self) -> str:
        return f"r{self.repeat_idx}_f{self.fold_idx}"


@dataclass
class SplitArtifact:
    """Materialised one-fold split on disk."""

    log_name: str
    fold: FoldSpec
    train_xes: Path
    test_xes: Path
    meta_path: Path
    n_train_traces: int
    n_test_traces: int
    n_train_variants: int
    n_test_variants: int
    underpowered: bool

    def as_meta_dict(self) -> Dict[str, Any]:
        return {
            "log_name": self.log_name,
            "repeat_idx": self.fold.repeat_idx,
            "fold_idx": self.fold.fold_idx,
            "seed": self.fold.seed,
            "split_kind": self.fold.split_kind,
            "underpowered": self.underpowered,
            "n_train_traces": self.n_train_traces,
            "n_test_traces": self.n_test_traces,
            "n_train_variants": self.n_train_variants,
            "n_test_variants": self.n_test_variants,
        }


# --------------------------------------------------------------------------- #
# Variant extraction
# --------------------------------------------------------------------------- #
def _load_variants(log_path: Path) -> Tuple[Any, Dict[Tuple[str, ...], List[str]]]:
    """Return (full_dataframe, variant→[case_ids]) for the log."""
    import pm4py

    df = pm4py.read_xes(str(log_path))
    df = df.copy()
    df[CASE_COL] = df[CASE_COL].astype(str)
    ordered = df.sort_values([CASE_COL, TIME_COL])
    case_variant = ordered.groupby(CASE_COL)[ACT_COL].apply(tuple)
    var_to_cases: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for case_id, variant in case_variant.items():
        var_to_cases[variant].append(case_id)
    return df, dict(var_to_cases)


def _quartile_buckets(
    variants: List[Tuple[str, ...]],
    var_to_cases: Dict[Tuple[str, ...], List[str]],
    k: int,
) -> List[List[Tuple[str, ...]]]:
    """Partition variants into k equal-ish buckets ordered by trace frequency.

    The lowest-frequency variants land in bucket 0, the highest in bucket k-1.
    Within each fold-pick we then take one variant from each bucket so the
    fold's holdout spans rare-to-common.
    """
    by_freq = sorted(variants, key=lambda v: (len(var_to_cases[v]), v))
    buckets: List[List[Tuple[str, ...]]] = [[] for _ in range(k)]
    for i, v in enumerate(by_freq):
        # round-robin into buckets so each bucket has ⌈n/k⌉ or ⌊n/k⌋ variants
        buckets[i % k].append(v)
    return buckets


# --------------------------------------------------------------------------- #
# Strategy A: k-fold stratified (n_variants >= LOO_THRESHOLD)
# --------------------------------------------------------------------------- #
def _kfold_assignments(
    variants: List[Tuple[str, ...]],
    var_to_cases: Dict[Tuple[str, ...], List[str]],
    k: int,
    seed: int,
) -> List[List[Tuple[str, ...]]]:
    """Return one fold-assignment per fold: ``[fold_0_test_variants, ...]``.

    Strategy: sort variants by trace-frequency (ascending), shuffle within
    each frequency-tier-block, then interleaved round-robin assign to folds.
    This guarantees each fold gets ``⌈n/k⌉`` or ``⌊n/k⌋`` variants AND each
    fold's variants span the full frequency range.
    """
    by_freq = sorted(variants, key=lambda v: (len(var_to_cases[v]), v))
    rng = random.Random(seed)
    # Optional within-tier shuffle: variants with equal frequency get
    # randomised order per repeat. Sorted-by-frequency block + local shuffle.
    blocks: List[List[Tuple[str, ...]]] = []
    current_block: List[Tuple[str, ...]] = []
    current_freq: Optional[int] = None
    for v in by_freq:
        f = len(var_to_cases[v])
        if current_freq is None or f == current_freq:
            current_block.append(v)
            current_freq = f
        else:
            blocks.append(current_block)
            current_block = [v]
            current_freq = f
    if current_block:
        blocks.append(current_block)
    for b in blocks:
        rng.shuffle(b)
    ordered: List[Tuple[str, ...]] = [v for b in blocks for v in b]

    folds: List[List[Tuple[str, ...]]] = [[] for _ in range(k)]
    # Rotate starting offset per repeat (driven by the same seed) so
    # different repeats partition differently even when the freq-ordering
    # is identical.
    offset = rng.randrange(k)
    for i, v in enumerate(ordered):
        folds[(i + offset) % k].append(v)
    return folds


# --------------------------------------------------------------------------- #
# Strategy B: LOO over variants (n_variants < LOO_THRESHOLD)
# --------------------------------------------------------------------------- #
def _loo_assignments(
    variants: List[Tuple[str, ...]],
) -> List[List[Tuple[str, ...]]]:
    """Each variant becomes a single-variant test fold (sorted)."""
    return [[v] for v in sorted(variants)]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def iter_variant_folds(
    log_path: Path,
    splits_root: Path,
    *,
    k: int = DEFAULT_K,
    repeats: int = DEFAULT_REPEATS,
    seeds: Tuple[int, ...] = DEFAULT_SEEDS,
    force: bool = False,
) -> Iterator[SplitArtifact]:
    """Yield SplitArtifact per fold for ``log_path``.

    Caching: per-fold ``train.xes``, ``test.xes`` and ``split_meta.json``
    are written under
    ``splits_root/<log_name>/<split_kind>/<repeat>_<fold>/``. A second
    invocation skips the rewrite unless ``force=True``.
    """
    import pm4py

    log_name = log_path.stem
    df, var_to_cases = _load_variants(log_path)
    variants = list(var_to_cases.keys())
    n_var = len(variants)

    if n_var < LOO_THRESHOLD:
        split_kind = (
            "loo_underpowered" if n_var < UNDERPOWERED_THRESHOLD else "loo"
        )
        fold_assignments = _loo_assignments(variants)
        repeats_iter: List[Tuple[int, int]] = [(0, seeds[0])]
    else:
        split_kind = "kfold_stratified"
        repeats_iter = [
            (r, seeds[r % len(seeds)] + r * 31)  # deterministic per (r, seed)
            for r in range(repeats)
        ]

    for repeat_idx, seed in repeats_iter:
        if split_kind == "kfold_stratified":
            fold_assignments = _kfold_assignments(variants, var_to_cases, k, seed)
        for fold_idx, test_variants in enumerate(fold_assignments):
            spec = FoldSpec(
                repeat_idx=repeat_idx,
                fold_idx=fold_idx,
                seed=seed,
                split_kind=split_kind,
            )
            test_var_set = set(test_variants)
            train_variants = [v for v in variants if v not in test_var_set]

            test_ids = {
                cid for v in test_variants for cid in var_to_cases[v]
            }
            train_ids = {
                cid for v in train_variants for cid in var_to_cases[v]
            }

            out_dir = (
                splits_root
                / log_name
                / split_kind
                / spec.slug
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            train_xes = out_dir / "train.xes"
            test_xes = out_dir / "test.xes"
            meta_path = out_dir / "split_meta.json"

            underpowered = split_kind == "loo_underpowered"

            if force or not (train_xes.exists() and test_xes.exists() and meta_path.exists()):
                train_df = df[df[CASE_COL].isin(train_ids)]
                test_df = df[df[CASE_COL].isin(test_ids)]
                pm4py.write_xes(train_df, str(train_xes))
                pm4py.write_xes(test_df, str(test_xes))
                meta_dict = {
                    "log_name": log_name,
                    "repeat_idx": repeat_idx,
                    "fold_idx": fold_idx,
                    "seed": seed,
                    "split_kind": split_kind,
                    "underpowered": underpowered,
                    "n_train_traces": len(train_ids),
                    "n_test_traces": len(test_ids),
                    "n_train_variants": len(train_variants),
                    "n_test_variants": len(test_variants),
                    "test_variant_repr": [list(v) for v in test_variants],
                }
                meta_path.write_text(json.dumps(meta_dict, indent=2), encoding="utf-8")
            else:
                meta_dict = json.loads(meta_path.read_text(encoding="utf-8"))

            yield SplitArtifact(
                log_name=log_name,
                fold=spec,
                train_xes=train_xes,
                test_xes=test_xes,
                meta_path=meta_path,
                n_train_traces=meta_dict["n_train_traces"],
                n_test_traces=meta_dict["n_test_traces"],
                n_train_variants=meta_dict["n_train_variants"],
                n_test_variants=meta_dict["n_test_variants"],
                underpowered=meta_dict["underpowered"],
            )


def summarise_log(log_path: Path) -> Dict[str, Any]:
    """Cheap reporting helper: variant counts and chosen split-kind."""
    _, var_to_cases = _load_variants(log_path)
    n_var = len(var_to_cases)
    if n_var < UNDERPOWERED_THRESHOLD:
        kind = "loo_underpowered"
    elif n_var < LOO_THRESHOLD:
        kind = "loo"
    else:
        kind = "kfold_stratified"
    return {
        "log_name": log_path.stem,
        "n_traces": sum(len(c) for c in var_to_cases.values()),
        "n_variants": n_var,
        "split_kind": kind,
    }
