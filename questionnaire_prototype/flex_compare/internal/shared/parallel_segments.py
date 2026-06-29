"""Parallel-composed stable-sequence segment detection + log filtering.

Mechanism under test
--------------------
IMf's AND-cut turns parallel-composed *stable sequences* in the DFG into a wide
PARALLEL block. A PARALLEL block over branches of lengths l_1..l_k admits the
multinomial(Σ l_i; l_1,..,l_k) interleavings, while a semi-structured log shows
only a handful -> over-generalisation -> precision loss. Loosely-structured logs
do not contain such parallel-composed sequences, so the effect is absent.

This module makes the mechanism measurable. It

  1. identifies the segments (Step 1) from the ARM (Source A, preferred) or, as a
     fallback, from the log's directly-follows relations (Source B), and
  2. produces filtered log variants (Step 2): ``project_log`` keeps only the
     segment activities; ``serialize_segment`` collapses the interleaving to a
     single canonical ordering (the causal ablation).

The reruns (Step 3) and the UI (Step 4) live in the comparison app; this module
is pure / importable (no Dash, no app state) so the detection can be unit-tested
in isolation. It reuses the observed-orderings counting from
``imperative_miner.variant_capacity`` and the ARM relation parsing from
``shared.arm_coverage``.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Optional

# Unordered activity pair, always stored sorted so (a, b) == (b, a).
Pair = tuple[str, str]
# Directed "source occurs before target" edge.
Edge = tuple[str, str]

# ARM relation kinds (see shared.arm_coverage._relation_kind) that express a
# temporal order between two co-occurring activities (within a branch).
_ORDER_KINDS = frozenset(
    {
        "direct_equivalence",
        "direct_implication",
        "direct_none",
        "eventual_equivalence",
        "eventual_implication",
        "eventual_none",
    }
)
# ARM kinds for concurrency: no temporal order between two existentially linked
# activities. Two readings of "linked":
#   * none_equivalence  (—,⇔): always together, no order — textbook concurrency.
#   * none_implication  (—,⇐/⇒): one-way existence implication, no order — the
#     two interleave whenever they co-occur, but one branch is optional/contains
#     a choice (e.g. a branch ``c -> (d XOR e)``: the c–d existence tie is an
#     implication, not an equivalence).
#
# The strict ``none_equivalence``-only reading misses every AND-block whose
# branches contain an optional or choice activity, which collapses long
# ground-truth parallel sequences down to their always-present spine (on the
# semi-structured logs this washed out branch lengths to 1, hiding the very
# mechanism under test). Including ``none_implication`` recovers the full
# interleaving group from the ground-truth ARM without any mining. XOR
# (``none_negated_equivalence``) and unrelated (``none_none``) pairs are
# deliberately excluded — they do not interleave.
_PARALLEL_KINDS = frozenset({"none_equivalence", "none_implication"})


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Segment:
    """One parallel-composed segment: ``k`` branches interleaved concurrently."""

    branches: list[list[str]]        # each branch an ordered activity list (canonical)
    activities: list[str]            # sorted union over all branches
    branch_lengths: list[int]
    interleaving_cardinality: int    # multinomial(Σ l_i; l_1..l_k)
    is_stable_sequence: bool         # True iff at least one branch has length >= 2

    def to_dict(self) -> dict:
        return {
            "branches": [list(b) for b in self.branches],
            "activities": list(self.activities),
            "branch_lengths": list(self.branch_lengths),
            "interleaving_cardinality": self.interleaving_cardinality,
            "is_stable_sequence": self.is_stable_sequence,
        }


def interleaving_cardinality(lengths: Iterable[int]) -> int:
    """Number of distinct interleavings of branches with the given lengths.

    For two branches m, n this is C(m+n, m); for k branches it is the
    multinomial coefficient (Σ l_i)! / Π l_i! — exact under unique labels.
    """
    lengths = [int(n) for n in lengths if int(n) > 0]
    total = sum(lengths)
    if total == 0:
        return 1
    result = math.factorial(total)
    for n in lengths:
        result //= math.factorial(n)
    return result


# --------------------------------------------------------------------------- #
# Graph helpers (no third-party deps — keeps the module import-light)
# --------------------------------------------------------------------------- #

def _connected_components(nodes: set[str], edges: Iterable[Pair]) -> list[set[str]]:
    """Connected components of an undirected graph over ``nodes``."""
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    comps: list[set[str]] = []
    for start in sorted(nodes):
        if start in seen:
            continue
        comp: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in comp:
                continue
            comp.add(node)
            stack.extend(adj[node] - comp)
        seen |= comp
        comps.append(comp)
    return comps


def _topological_order(nodes: set[str], edges: Iterable[Edge]) -> list[str]:
    """Deterministic topological order (Kahn) with alphabetical tie-break.

    Falls back to alphabetical order on a cycle so the result stays defined and
    reproducible even if the relations are noisy.
    """
    nodes = set(nodes)
    succ: dict[str, set[str]] = {n: set() for n in nodes}
    indeg: dict[str, int] = {n: 0 for n in nodes}
    for a, b in edges:
        if a in nodes and b in nodes and b not in succ[a]:
            succ[a].add(b)
            indeg[b] += 1
    ready = sorted(n for n in nodes if indeg[n] == 0)
    out: list[str] = []
    while ready:
        node = ready.pop(0)
        out.append(node)
        for nxt in sorted(succ[node]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort()
    if len(out) != len(nodes):  # cycle — deterministic fallback
        return sorted(nodes)
    return out


# --------------------------------------------------------------------------- #
# Step 1 — segment identification (shared core)
# --------------------------------------------------------------------------- #

def find_segments(
    parallel_pairs: Iterable[Pair],
    order_edges: Iterable[Edge],
) -> list[Segment]:
    """Identify parallel-composed segments from concurrency + order relations.

    ``parallel_pairs``: unordered activity pairs that interleave (concurrency).
    ``order_edges``: directed (source -> target) "source occurs before target".

    Algorithm:
      1. Concurrency graph over ``parallel_pairs`` -> connected components are the
         concurrency groups (mutually interleaving activities).
      2. Within a group, drop parallel edges and keep only the order edges; their
         weakly-connected components are the *branches* (stable sequences). Each
         branch is ordered by a topological sort of its order edges (alphabetical
         tie-break -> deterministic).
      3. Keep a group as a Segment iff it splits into >= 2 branches.
    """
    par_pairs = {_norm(a, b) for a, b in parallel_pairs}
    par_pairs = {p for p in par_pairs if p[0] != p[1]}
    order = [(a, b) for a, b in order_edges if a != b]

    nodes = {a for p in par_pairs for a in p}
    groups = _connected_components(nodes, par_pairs)

    segments: list[Segment] = []
    for group in groups:
        if len(group) < 2:
            continue
        # Order edges fully inside this group define within-branch sequencing.
        inner_edges = [(a, b) for a, b in order if a in group and b in group]
        undirected = [(a, b) for a, b in inner_edges]
        branch_sets = _connected_components(group, undirected)
        if len(branch_sets) < 2:
            continue  # one chain -> a plain sequence, not an AND over sequences

        branches: list[list[str]] = []
        for bset in branch_sets:
            ordered = _topological_order(bset, inner_edges)
            branches.append(ordered)
        # Canonical branch order: by the branch's activity tuple.
        branches.sort(key=lambda b: tuple(b))

        lengths = [len(b) for b in branches]
        segments.append(
            Segment(
                branches=branches,
                activities=sorted(group),
                branch_lengths=lengths,
                interleaving_cardinality=interleaving_cardinality(lengths),
                is_stable_sequence=any(n >= 2 for n in lengths),
            )
        )
    # Stable order for reproducible UI: largest / most-interleaved first.
    segments.sort(key=lambda s: (-s.interleaving_cardinality, tuple(s.activities)))
    return segments


def _norm(a: str, b: str) -> Pair:
    return (a, b) if a <= b else (b, a)


# --------------------------------------------------------------------------- #
# Step 1 — Source M: the discovered IMf process tree's PARALLEL nodes
# --------------------------------------------------------------------------- #
#
# This is the locus of the mechanism: the AND-cut *is* a PARALLEL node in the
# discovered tree, and its children are the interleaved (stable-sequence)
# branches. In real semi-structured logs the ARM/DFG concurrency signature is
# washed out by thresholds, so the discovered tree is the reliable source; the
# ablation then asks whether collapsing that very interleaving recovers
# precision. Branches are read directly off the child subtrees (leaf order),
# which guarantees they line up with what ``serialize_segment`` collapses.

_OP_PARALLEL = "+"


def _leaves_in_order(node: dict) -> list[str]:
    """Visible activity labels under ``node`` in left-to-right (sequence) order."""
    children = node.get("children") or []
    label = node.get("label")
    if not children:
        return [str(label)] if label is not None else []
    out: list[str] = []
    for child in children:
        out.extend(_leaves_in_order(child))
    return out


def segments_from_tree(tree: dict) -> list[Segment]:
    """Build segments from every PARALLEL node of a serialized process tree.

    Each PARALLEL node with >= 2 non-empty children yields one Segment; a child
    subtree becomes a branch (its leaves in sequence order). Interleaving
    cardinality is the multinomial over branch lengths (the task's definition —
    the number of interleavings of the branches, taus aside).
    """
    segments: list[Segment] = []

    def walk(node: dict) -> None:
        if node.get("operator") == _OP_PARALLEL:
            branches = [_leaves_in_order(c) for c in (node.get("children") or [])]
            branches = [b for b in branches if b]
            if len(branches) >= 2:
                branches.sort(key=tuple)
                lengths = [len(b) for b in branches]
                activities = sorted({a for b in branches for a in b})
                segments.append(
                    Segment(
                        branches=branches,
                        activities=activities,
                        branch_lengths=lengths,
                        interleaving_cardinality=interleaving_cardinality(lengths),
                        is_stable_sequence=any(n >= 2 for n in lengths),
                    )
                )
        for child in node.get("children") or []:
            walk(child)

    if tree:
        walk(tree)
    segments.sort(key=lambda s: (-s.interleaving_cardinality, tuple(s.activities)))
    return segments


def block_is_unique_label(log, activities: Iterable[str]) -> bool:
    """True iff no segment activity occurs more than once in any single trace.

    The serialize ablation is only well-defined under this unique-label property
    (the same property that makes ``variant_capacity`` counts exact): with
    repeats, forcing a canonical order would scramble loops rather than merely
    collapse an interleaving, so the ablation result is not trustworthy.
    """
    acts = set(activities)
    for trace in log:
        seen: dict[str, int] = {}
        for event in trace:
            name = _activity(event)
            if name in acts:
                seen[name] = seen.get(name, 0) + 1
                if seen[name] > 1:
                    return False
    return True


# --------------------------------------------------------------------------- #
# Step 1 — Source A: relations from the ARM
# --------------------------------------------------------------------------- #

def relations_from_arm(arm: dict) -> tuple[set[Pair], set[Edge]]:
    """Concurrency pairs + order edges from an ARM result dict (Source A).

    Concurrency = any ``_PARALLEL_KINDS`` cell (no temporal order between two
    existentially linked activities: ``none_equivalence`` or ``none_implication``
    — see the constant for why the implication case is needed).
    Order = any Direct/Eventual temporal kind, oriented source -> target by the
    ARM's own direction normalisation (``build_expected_relations``).
    """
    from flex_compare.internal.shared.arm_coverage import build_expected_relations

    parallel_pairs: set[Pair] = set()
    order_edges: set[Edge] = set()
    for rel in build_expected_relations(arm):
        if rel.kind in _PARALLEL_KINDS:
            parallel_pairs.add(_norm(rel.source, rel.target))
        elif rel.kind in _ORDER_KINDS:
            order_edges.add((rel.source, rel.target))
    return parallel_pairs, order_edges


# --------------------------------------------------------------------------- #
# Step 1 — Source B: relations from the log's directly-follows graph
# --------------------------------------------------------------------------- #

def _activity(event) -> Optional[str]:
    name = event.get("concept:name") if hasattr(event, "get") else None
    return str(name) if name is not None else None


def log_activities(log) -> list[str]:
    """Sorted distinct activity names (``concept:name``) occurring in the log."""
    acts: set[str] = set()
    for trace in log:
        for event in trace:
            name = _activity(event)
            if name is not None:
                acts.add(name)
    return sorted(acts)


def directly_follows_counts(log) -> dict[Edge, int]:
    """Count directly-follows occurrences a -> b over consecutive events."""
    counts: dict[Edge, int] = defaultdict(int)
    for trace in log:
        prev: Optional[str] = None
        for event in trace:
            name = _activity(event)
            if name is None:
                continue
            if prev is not None:
                counts[(prev, name)] += 1
            prev = name
    return dict(counts)


def relations_from_log(log, min_support_ratio: float = 0.0) -> tuple[set[Pair], set[Edge]]:
    """Concurrency pairs + order edges from the log's DFG (Source B).

    A pair is concurrent iff it is observed in *both* directions (a->b and b->a)
    — the bidirectional directly-follows signature the AND-cut keys on.
    A pair seen in only one direction yields a single order edge. With
    ``min_support_ratio > 0`` the minority direction must reach that fraction of
    the pair's total directly-follows mass to count as bidirectional (noise
    guard); the default 0.0 treats any observed reverse edge as concurrency.
    """
    counts = directly_follows_counts(log)
    pairs: dict[Pair, dict[str, int]] = defaultdict(lambda: {"fwd": 0, "bwd": 0})
    for (a, b), n in counts.items():
        key = _norm(a, b)
        direction = "fwd" if (a, b) == key else "bwd"
        pairs[key][direction] += n

    parallel_pairs: set[Pair] = set()
    order_edges: set[Edge] = set()
    for (a, b), c in pairs.items():  # a <= b by construction
        fwd, bwd = c["fwd"], c["bwd"]  # fwd = a->b, bwd = b->a
        total = fwd + bwd
        if total == 0:
            continue
        minority = min(fwd, bwd)
        if minority > 0 and minority >= min_support_ratio * total:
            parallel_pairs.add((a, b))
        elif fwd >= bwd:
            order_edges.add((a, b))
        else:
            order_edges.add((b, a))
    return parallel_pairs, order_edges


def detect_segments(
    log,
    tree: Optional[dict] = None,
    arm: Optional[dict] = None,
    min_support_ratio: float = 0.0,
) -> tuple[list[Segment], str]:
    """Identify segments, preferring the discovered tree, then ARM, then the log.

    Returns ``(segments, source)`` where source is ``"model"`` (the discovered
    IMf tree's PARALLEL nodes — the mechanism's locus and the reliable signal),
    ``"arm"`` (Source A), or ``"log"`` (Source B). Each later source is only
    consulted when the earlier one yields no segments.
    """
    if tree:
        segs = segments_from_tree(tree)
        if segs:
            return segs, "model"
    if arm is not None:
        par, order = relations_from_arm(arm)
        if par:
            segs = find_segments(par, order)
            if segs:
                return segs, "arm"
    par, order = relations_from_log(log, min_support_ratio=min_support_ratio)
    return find_segments(par, order), "log"


# --------------------------------------------------------------------------- #
# Observed interleaving coverage
# --------------------------------------------------------------------------- #

def observed_coverage(log, segment: Segment) -> tuple[int, float]:
    """Distinct interleavings of the segment seen in the log, and coverage ratio.

    Reuses ``variant_capacity.observed_orderings_for`` so the "observed distinct
    orderings" definition matches the existing capacity analysis.
    """
    from flex_compare.internal.imperative_miner.variant_capacity import (
        observed_orderings_for,
        observed_stats,
    )

    obs = observed_stats(log)
    distinct = observed_orderings_for(segment.activities, obs)
    card = segment.interleaving_cardinality
    ratio = distinct / card if card else float("nan")
    return distinct, ratio


# --------------------------------------------------------------------------- #
# Step 2 — log filtering
# --------------------------------------------------------------------------- #

def _new_log(source_log):
    """Empty EventLog carrying the source log's attributes."""
    from pm4py.objects.log.obj import EventLog

    try:
        return EventLog(attributes=dict(getattr(source_log, "attributes", {}) or {}))
    except Exception:
        return EventLog()


def _copy_trace_shell(trace):
    from pm4py.objects.log.obj import Trace

    try:
        return Trace(attributes=dict(getattr(trace, "attributes", {}) or {}))
    except Exception:
        return Trace()


def _copy_event(event):
    from pm4py.objects.log.obj import Event

    return Event(dict(event))


def project_log(log, activities: Iterable[str]):
    """Project every trace onto ``activities`` (order preserved)."""
    keep = set(activities)
    out = _new_log(log)
    for trace in log:
        new_trace = _copy_trace_shell(trace)
        for event in trace:
            if _activity(event) in keep:
                new_trace.append(_copy_event(event))
        out.append(new_trace)
    return out


def serialize_segment(log, segment: Segment):
    """Collapse the segment's interleaving to one canonical ordering (ablation).

    For every trace, the segment-activity events are reordered into the canonical
    branch order (branches in canonical order, each branch in its intra-branch
    order) and written back into the *same* slot positions; non-segment events
    are untouched, so trace length and all other behaviour are preserved. This
    removes the interleaving variety the AND-cut feeds on without otherwise
    changing the log. Deterministic: a stable sort on a fixed canonical key.
    """
    # activity -> (branch index, position within branch)
    rank: dict[str, tuple[int, int]] = {}
    for bi, branch in enumerate(segment.branches):
        for pi, act in enumerate(branch):
            rank.setdefault(act, (bi, pi))
    seg_acts = set(rank)

    out = _new_log(log)
    for trace in log:
        new_trace = _copy_trace_shell(trace)
        events = [_copy_event(e) for e in trace]
        positions = [i for i, e in enumerate(events) if _activity(e) in seg_acts]
        seg_events = [events[i] for i in positions]
        # Stable sort by canonical rank: repeated activities keep relative order.
        seg_events.sort(key=lambda e: rank[_activity(e)])
        for slot, event in zip(positions, seg_events):
            events[slot] = event
        for event in events:
            new_trace.append(event)
        out.append(new_trace)
    return out
