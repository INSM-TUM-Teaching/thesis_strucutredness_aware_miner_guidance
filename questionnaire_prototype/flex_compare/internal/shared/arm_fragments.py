"""Existential fragment / choice / periphery decomposition from an ARM.

This is the *existential* counterpart to the *temporal* parallel-segment
detection in :mod:`miners.shared.parallel_segments`. Where a parallel segment is
an interleaving (AND-over-sequences) block, a **fragment** is Andree et al.'s
structured segment: a set of activities that *always co-occur* (existential
equivalence ``⇔``) and thus form the obligatory core of a (semi-)structured
process [Andree, Kuzmin, Pufahl 2025, "Automated Process Classification"; Andree,
Bano, Weske 2025, "A closer look at activity relationships"].

The decomposition reads three existential signatures off the ARM:

* **Fragment** — a maximal clique under existential **Equivalence** (``⇔``);
  "if a fragment is executed, all contained activities must occur". Carries its
  internal temporal order (Direct/Eventual) where defined.
* **Choice block** — a component under **Negated Equivalence** (``⇎``, XOR):
  exactly one of the activities occurs. A *strong, deterministic* rule that is
  nonetheless typically *optional* relative to a fragment.
* **Optional periphery** — activities tied to the rest only by existential
  **Implication** (``⇒``): present conditionally, "flexibly combined" — the
  signature that separates semi- from structured logs.

Pure / importable (no Dash). Reuses the direction-normalised relation parsing
from :mod:`miners.shared.arm_coverage`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from flex_compare.internal.shared.parallel_segments import _ORDER_KINDS, _norm, _topological_order

Pair = tuple[str, str]
Edge = tuple[str, str]


@dataclass
class Fragment:
    """A maximal existential-equivalence (``⇔``) clique with internal order."""

    activities: list[str]              # sorted union
    order_edges: list[Edge]            # forward (source -> target) within the clique
    branches: list[list[str]]          # weakly-connected order chains, each topo-sorted

    def to_dict(self) -> dict:
        return {
            "activities": list(self.activities),
            "order_edges": [list(e) for e in self.order_edges],
            "branches": [list(b) for b in self.branches],
        }


@dataclass
class FragmentDecomposition:
    activities: list[str]
    fragments: list[Fragment] = field(default_factory=list)
    choice_blocks: list[list[str]] = field(default_factory=list)   # ⇎ components (size >= 2)
    periphery: list[str] = field(default_factory=list)             # only ⇒-attached / unrelated
    roles: dict[str, str] = field(default_factory=dict)            # act -> fragment|choice|periphery

    def to_dict(self) -> dict:
        return {
            "activities": list(self.activities),
            "fragments": [f.to_dict() for f in self.fragments],
            "choice_blocks": [list(b) for b in self.choice_blocks],
            "periphery": list(self.periphery),
            "roles": dict(self.roles),
        }


def _components(nodes: set[str], pairs: Iterable[Pair]) -> list[set[str]]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in pairs:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    out: list[set[str]] = []
    for start in sorted(nodes):
        if start in seen:
            continue
        comp: set[str] = set()
        stack = [start]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(adj[x] - comp)
        seen |= comp
        out.append(comp)
    return out


def decompose_fragments(arm: dict) -> FragmentDecomposition:
    """Split an ARM into existential fragments, choice blocks and periphery."""
    from flex_compare.internal.shared.arm_coverage import build_expected_relations

    activities = sorted(arm.get("activities", []))
    equiv_pairs: set[Pair] = set()
    xor_pairs: set[Pair] = set()
    order_edges: set[Edge] = set()

    for rel in build_expected_relations(arm):
        et = rel.existential_type
        if et == "Equivalence":
            equiv_pairs.add(_norm(rel.source, rel.target))
        elif et == "NegatedEquivalence":
            xor_pairs.add(_norm(rel.source, rel.target))
        if rel.kind in _ORDER_KINDS:
            order_edges.add((rel.source, rel.target))

    equiv_nodes = {a for p in equiv_pairs for a in p}
    fragments: list[Fragment] = []
    fragment_acts: set[str] = set()
    for comp in _components(equiv_nodes, equiv_pairs):
        if len(comp) < 2:
            continue
        inner = [(a, b) for a, b in order_edges if a in comp and b in comp]
        branches = [
            _topological_order(bset, inner)
            for bset in _components(comp, [(a, b) for a, b in inner])
        ]
        branches.sort(key=tuple)
        fragments.append(
            Fragment(activities=sorted(comp), order_edges=sorted(inner), branches=branches)
        )
        fragment_acts |= comp
    fragments.sort(key=lambda f: (-len(f.activities), tuple(f.activities)))

    choice_blocks = [
        sorted(comp)
        for comp in _components({a for p in xor_pairs for a in p}, xor_pairs)
        if len(comp) >= 2
    ]
    choice_blocks.sort(key=tuple)
    choice_acts = {a for b in choice_blocks for a in b}

    roles: dict[str, str] = {}
    for a in activities:
        if a in fragment_acts:
            roles[a] = "fragment"
        elif a in choice_acts:
            roles[a] = "choice"
        else:
            roles[a] = "periphery"
    periphery = [a for a in activities if roles[a] == "periphery"]

    return FragmentDecomposition(
        activities=activities,
        fragments=fragments,
        choice_blocks=choice_blocks,
        periphery=periphery,
        roles=roles,
    )
