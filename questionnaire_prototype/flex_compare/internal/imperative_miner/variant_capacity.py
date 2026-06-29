"""Variant capacity analysis for Inductive-Miner process trees.

Motivation
----------
The Inductive Miner's AND-cut fires when activities in the DFG follow one
another mutually. In the flexible region of a semi-structured log almost every
activity follows almost every other in both directions, the AND-cut condition is
met, and a large PARALLEL block is produced. A PARALLEL block over k activities
admits k! orderings, so the model *generalises*: it allows far more trace
variants than were ever observed.

This module turns that "over-generalisation" from an adjective into a number. It
computes, per model, how many trace variants the discovered process tree
theoretically allows (its language size) and contrasts that with the number of
variants actually observed in the log.

Why the count is exact
-----------------------
For these synthetic logs every visible activity label occurs *exactly once* in
the tree. Under that unique-label property no two different derivations ever
yield the same activity sequence, so the language size is computed exactly by a
recursion over a length generating function (a dict mapping trace-length L to the
number of distinct traces of length L):

  leaf 'a'      -> {1: 1}
  tau           -> {0: 1}
  XOR  X(...)   -> per-length sum of children      (disjoint -> exact)
  SEQ  ->(...)  -> convolution / polynomial product (lengths add, counts multiply)
  AND  +(...)   -> shuffle: choosing traces of length l_i from each child yields
                   multinomial(sum l_i; l_1,...,l_n) distinct interleavings
  LOOP *(do,re) -> do . (re . do)*  -> infinite (bounded by max length if asked)

If the unique-label property does not hold, the recursion is an *upper bound*
(string collisions can only reduce the true count) and the result is flagged.

Run
---
    .venv/bin/python -m miners.imperative_miner.variant_capacity
    .venv/bin/python -m miners.imperative_miner.variant_capacity --log Log06
"""

from __future__ import annotations

import argparse
import glob
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Length generating function: length -> count of distinct traces of that length.
LengthGF = Dict[int, int]

# pm4py process-tree operator symbols (see _serialize_process_tree_node).
OP_SEQUENCE = "->"
OP_XOR = "X"
OP_PARALLEL = "+"
OP_LOOP = "*"

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "data", "with-case-ids")


# ---------------------------------------------------------------------------
# Length generating function algebra
# ---------------------------------------------------------------------------

def _gf_add(a: LengthGF, b: LengthGF) -> LengthGF:
    """XOR: union of two disjoint languages -> per-length sum."""
    out: LengthGF = dict(a)
    for length, count in b.items():
        out[length] = out.get(length, 0) + count
    return out


def _gf_concat(a: LengthGF, b: LengthGF, max_length: Optional[int]) -> LengthGF:
    """SEQUENCE of two factors: lengths add, counts multiply (convolution)."""
    out: LengthGF = {}
    for la, ca in a.items():
        for lb, cb in b.items():
            total = la + lb
            if max_length is not None and total > max_length:
                continue
            out[total] = out.get(total, 0) + ca * cb
    return out


def _gf_shuffle(a: LengthGF, b: LengthGF, max_length: Optional[int]) -> LengthGF:
    """PARALLEL of two operands: every interleaving of a trace of length la and a
    trace of length lb is a distinct string (unique labels), and there are
    C(la+lb, la) of them. Folding this pairwise reproduces the full multinomial."""
    out: LengthGF = {}
    for la, ca in a.items():
        for lb, cb in b.items():
            total = la + lb
            if max_length is not None and total > max_length:
                continue
            inter = math.comb(total, la)
            out[total] = out.get(total, 0) + ca * cb * inter
    return out


# ---------------------------------------------------------------------------
# Tree -> length generating function
# ---------------------------------------------------------------------------

@dataclass
class CapacityResult:
    gf: LengthGF
    has_loop: bool
    loop_bounded: bool  # True if a loop was truncated at max_length

    @property
    def total(self) -> int:
        return sum(self.gf.values())

    @property
    def max_len(self) -> int:
        return max(self.gf) if self.gf else 0


def tree_capacity(node: Dict[str, Any], max_length: Optional[int] = None) -> CapacityResult:
    """Compute the length generating function of a serialized process-tree node.

    ``max_length`` truncates traces longer than the bound; it is *required* for
    trees containing a LOOP (otherwise the language is infinite and we mark the
    result as unbounded by returning has_loop=True with the loop's body only).
    """
    op = node.get("operator")
    children = node.get("children") or []

    # Leaf
    if not children:
        label = node.get("label")
        if label is None:
            return CapacityResult({0: 1}, has_loop=False, loop_bounded=False)
        return CapacityResult({1: 1}, has_loop=False, loop_bounded=False)

    child_results = [tree_capacity(c, max_length) for c in children]
    has_loop = any(cr.has_loop for cr in child_results)
    loop_bounded = any(cr.loop_bounded for cr in child_results)

    if op == OP_XOR:
        gf: LengthGF = {}
        for cr in child_results:
            gf = _gf_add(gf, cr.gf)
        return CapacityResult(gf, has_loop, loop_bounded)

    if op == OP_SEQUENCE:
        gf = {0: 1}
        for cr in child_results:
            gf = _gf_concat(gf, cr.gf, max_length)
        return CapacityResult(gf, has_loop, loop_bounded)

    if op == OP_PARALLEL:
        gf = {0: 1}
        for cr in child_results:
            gf = _gf_shuffle(gf, cr.gf, max_length)
        return CapacityResult(gf, has_loop, loop_bounded)

    if op == OP_LOOP:
        # pm4py loop: *(do, redo[, ...]) == do . (redo . do)*
        do_gf = child_results[0].gf
        redo_gf: LengthGF = {}
        for cr in child_results[1:]:
            redo_gf = _gf_add(redo_gf, cr.gf)
        if max_length is None:
            # Unbounded language; return the zero-iteration body and flag it.
            return CapacityResult(do_gf, has_loop=True, loop_bounded=False)
        gf = dict(do_gf)
        term = do_gf
        cycle = _gf_concat(redo_gf, do_gf, max_length)
        # Each extra iteration appends (redo . do); keep going while it can fit.
        while term:
            term = _gf_concat(term, cycle, max_length)
            if not term:
                break
            gf = _gf_add(gf, term)
        return CapacityResult(gf, has_loop=True, loop_bounded=True)

    # Unknown operator: treat as opaque single token (defensive).
    return CapacityResult({1: 1}, has_loop, loop_bounded)


# ---------------------------------------------------------------------------
# Label inventory / unique-label check
# ---------------------------------------------------------------------------

def collect_labels(node: Dict[str, Any]) -> List[str]:
    labels: List[str] = []
    label = node.get("label")
    children = node.get("children") or []
    if not children and label is not None:
        labels.append(str(label))
    for c in children:
        labels.extend(collect_labels(c))
    return labels


def labels_are_unique(node: Dict[str, Any]) -> bool:
    labels = collect_labels(node)
    return len(labels) == len(set(labels))


# ---------------------------------------------------------------------------
# AND-block extraction (local over-generalisation)
# ---------------------------------------------------------------------------

@dataclass
class AndBlock:
    activities: List[str]          # visible activities under the PARALLEL node
    n_branches: int                # direct children of the PARALLEL node
    allowed_orderings: int         # language size of the block subtree (exact)
    has_loop: bool


def find_and_blocks(node: Dict[str, Any], max_length: Optional[int] = None) -> List[AndBlock]:
    blocks: List[AndBlock] = []
    if node.get("operator") == OP_PARALLEL:
        cr = tree_capacity(node, max_length)
        blocks.append(
            AndBlock(
                activities=sorted(set(collect_labels(node))),
                n_branches=len(node.get("children") or []),
                allowed_orderings=cr.total,
                has_loop=cr.has_loop,
            )
        )
    for c in node.get("children") or []:
        blocks.extend(find_and_blocks(c, max_length))
    return blocks


# ---------------------------------------------------------------------------
# Log loading + observed variants
# ---------------------------------------------------------------------------

@dataclass
class ObservedStats:
    n_cases: int
    n_variants: int
    max_len: int
    variants: List[Tuple[str, ...]] = field(default_factory=list)


def observed_stats(log) -> ObservedStats:
    variants: Dict[Tuple[str, ...], int] = {}
    max_len = 0
    n_cases = 0
    for trace in log:
        n_cases += 1
        seq: List[str] = []
        for event in trace:
            name = event.get("concept:name") if hasattr(event, "get") else None
            if name:
                seq.append(str(name))
        max_len = max(max_len, len(seq))
        key = tuple(seq)
        variants[key] = variants.get(key, 0) + 1
    return ObservedStats(
        n_cases=n_cases,
        n_variants=len(variants),
        max_len=max_len,
        variants=list(variants.keys()),
    )


def observed_orderings_for(activities: List[str], obs: ObservedStats) -> int:
    """Distinct orderings of the given activity set actually seen in the log
    (each trace projected onto exactly those activities)."""
    act = set(activities)
    seen: set[Tuple[str, ...]] = set()
    for variant in obs.variants:
        seen.add(tuple(a for a in variant if a in act))
    return len(seen)


# ---------------------------------------------------------------------------
# End-to-end per-log analysis
# ---------------------------------------------------------------------------

@dataclass
class LogAnalysis:
    log_name: str
    structuredness: str
    n_cases: int
    n_obs_variants: int
    max_len: int
    root_op: Optional[str]
    n_leaves: int
    allowed_variants: int
    unbounded: bool
    labels_unique: bool
    and_blocks: List[AndBlock]
    precision: Optional[float] = None


def _structuredness_from_name(name: str) -> str:
    for tag in ("unstructured", "looselyStructured", "semiStructured", "structured"):
        if tag.lower() in name.lower():
            return tag
    return "?"


def analyze_tree(
    log_name: str,
    tree: Dict[str, Any],
    obs: ObservedStats,
    precision: Optional[float] = None,
) -> LogAnalysis:
    unique = labels_are_unique(tree)
    # Bound loops at the longest observed trace so the comparison stays finite.
    cap = tree_capacity(tree, max_length=obs.max_len)
    unbounded = cap.has_loop and not cap.loop_bounded
    cap_for_total = (
        tree_capacity(tree, max_length=obs.max_len) if cap.has_loop else tree_capacity(tree)
    )
    blocks = find_and_blocks(tree, max_length=obs.max_len if cap.has_loop else None)
    return LogAnalysis(
        log_name=log_name,
        structuredness=_structuredness_from_name(log_name),
        n_cases=obs.n_cases,
        n_obs_variants=obs.n_variants,
        max_len=obs.max_len,
        root_op=tree.get("operator"),
        n_leaves=len(collect_labels(tree)),
        allowed_variants=cap_for_total.total,
        unbounded=unbounded,
        labels_unique=unique,
        and_blocks=blocks,
        precision=precision,
    )


def discover_tree(log, noise_threshold: float = 0.0) -> Dict[str, Any]:
    """Run IMf and return the serialized process tree (matching the cache schema)."""
    import pm4py
    from .evaluation import _serialize_process_tree_node

    process_tree = pm4py.discovery.discover_process_tree_inductive(
        log, noise_threshold=noise_threshold
    )
    return _serialize_process_tree_node(process_tree)


def load_log(path: str):
    from pm4py.objects.log.importer.xes import importer as xes_importer

    return xes_importer.apply(path, parameters={"show_progress_bar": False})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt_int(n: int) -> str:
    if n >= 10**15:
        return f"{n:.3e}"
    return f"{n:,}"


def run(log_dir: str, only: Optional[str], noise: float) -> None:
    paths = sorted(glob.glob(os.path.join(log_dir, "*.xes")))
    if only:
        paths = [p for p in paths if only.lower() in os.path.basename(p).lower()]
    if not paths:
        print(f"No logs matched in {log_dir}")
        return

    analyses: List[LogAnalysis] = []
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        log = load_log(path)
        obs = observed_stats(log)
        tree = discover_tree(log, noise_threshold=noise)
        analyses.append(analyze_tree(name, tree, obs))

    # Summary table
    header = (
        f"{'Log':<34} {'class':<18} {'obs':>5} {'allowed':>16} "
        f"{'ratio':>10} {'root':>5} {'AND-blk':>8}"
    )
    print(f"\nIMf variant capacity  (noise_threshold={noise})")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for a in sorted(analyses, key=lambda x: x.log_name):
        ratio = a.n_obs_variants / a.allowed_variants if a.allowed_variants else float("nan")
        allowed = _fmt_int(a.allowed_variants) + ("+" if a.unbounded else "")
        flag = "" if a.labels_unique else " *ub"
        print(
            f"{a.log_name:<34} {a.structuredness:<18} {a.n_obs_variants:>5} "
            f"{allowed:>16} {ratio:>10.2e} {str(a.root_op):>5} "
            f"{len(a.and_blocks):>8}{flag}"
        )
    print("-" * len(header))
    print("obs = observed distinct variants | allowed = trace variants the tree admits")
    print("ratio = obs / allowed (smaller = more over-generalisation) | * = label not unique (upper bound)")

    # Per-AND-block deep dive
    for a in sorted(analyses, key=lambda x: x.log_name):
        if not a.and_blocks:
            continue
        print(f"\n--- AND-blocks in {a.log_name} ({a.structuredness}) ---")
        obs = observed_stats(load_log(os.path.join(log_dir, a.log_name + ".xes")))
        for i, blk in enumerate(a.and_blocks, 1):
            obs_ord = observed_orderings_for(blk.activities, obs)
            over = blk.allowed_orderings / obs_ord if obs_ord else float("nan")
            print(
                f"  block {i}: {blk.n_branches} branches over {{{', '.join(blk.activities)}}}\n"
                f"    allowed orderings = {_fmt_int(blk.allowed_orderings)} | "
                f"observed distinct orderings = {obs_ord} | "
                f"over-generalisation factor = {over:.2e}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log-dir", default=DEFAULT_LOG_DIR)
    ap.add_argument("--log", default=None, help="substring filter, e.g. Log06")
    ap.add_argument("--noise", type=float, default=0.0, help="IMf noise_threshold (locked default 0.0)")
    args = ap.parse_args()
    run(args.log_dir, args.log, args.noise)


if __name__ == "__main__":
    main()
