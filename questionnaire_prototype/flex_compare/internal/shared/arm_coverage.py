"""SF-2 (ARM native/forced evidence) — "ARM-Coverage-Mapper".

In the consolidated questionnaire (characteristics_config.yaml,
e2-measurement-spec §2) the native/forced question is **SF-2**; there is no
SF-3 item anymore. The historical "SF-3" name survives only in the internal
``compute_sf3_score`` symbol (kept for import/test stability) — it is *not* a
separate dimension.

Classifies, per ARM relation of a log, how a discovered model represents that
relation:

  * ``native``           - the relation is expressed idiomatically by a
                           paradigm-native construct.
  * ``forced``           - the relation is expressed only via a workaround /
                           non-idiomatic construct.
  * ``missing``          - the ARM relation is present (above threshold) but the
                           model has no corresponding construct.
  * ``correctly_absent`` - ARM has no relation and the model has none either.
  * ``not_applicable``   - the relation is paradigmatically impossible to express
                           for this miner (excluded from the score; reported
                           separately so a paradigm is never penalised for what
                           it structurally cannot say).
  * ``spurious``         - ARM has no relation but the model relates the pair
                           anyway (over-structure; feeds ``absence_precision``,
                           not ``coverage_score``).

Works for three paradigms: imperative (IMf / process tree + Petri net),
declarative (MINERful Declare constraints) and hybrid (FusionMINERful,
procedural net + declarative overlay).

Design
------
All three model sources are normalised into the SAME directed tag vocabulary
(see ``Tag``), so the translation table (:data:`TRANSLATION`) is largely
paradigm-independent. The paradigm asymmetry is captured by a single set,
:data:`PARADIGM_IMPOSSIBLE`.

Hard constraint R1: no visual parsing of PNGs. Every model fact is derived from
JSON / text structures:
  * IMf  <- ``metrics.process_tree_structure`` (operator tree); recomputed from
            the log on demand if the cached field is absent (stale caches).
  * MINERful <- native constraints JSON at ``metrics.json_path``.
  * Fusion   <- ``pnwa_model.json`` (the Petri net: places/transitions/arcs) when
                present, else ``hybrid_model.json`` (flat procedural graph). The
                net is read as JSON, never as an image, so R1 still holds.

The translation tables are the research core. Each ARM relation kind maps to the
normalised constructs that express it natively vs. via a workaround. The mapping
is derived from construct semantics:
  * Declare / MINERful templates: Di Ciccio & Mecella (MINERful), Pesic & van der
    Aalst (Declare) - each template placed on the (temporal-order,
    existential-implication) axes.
  * Process-tree operators: Leemans (Inductive Miner) - ``->`` sequence (order),
    ``X`` exclusive choice (mutual exclusion), ``+`` concurrency (co-occurrence
    without order), ``*`` loop, ``O`` optional (tau).
  * FusionMINERful: PNWA Petri net behavioural footprint (order via reachability,
    XOR -> exclusive, AND -> parallel) + declarative overlay (existential /
    negative). Falls back to the flat procedural graph when no usable net exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

ParadigmKind = Literal["imperative", "declarative", "fusion"]

Verdict = Literal[
    "native",
    "forced",
    "missing",
    "correctly_absent",
    "not_applicable",
    "spurious",
]

# Canonical ARM relation kind derived from a direction-normalised cell.
ArmRelationKind = Literal[
    "direct_equivalence",
    "direct_implication",
    "direct_none",
    "eventual_equivalence",
    "eventual_implication",
    "eventual_none",
    "none_equivalence",
    "none_implication",
    "none_negated_equivalence",
    "none_none",
]

# Normalised model tags. Directed unless noted "symmetric" (stored both ways).
TAG_CHAIN = "chain_order"  # immediate / direct succession  x -> y
TAG_ORDER = "order"  # eventual order                 x ... y
TAG_PARALLEL = "parallel"  # concurrency (symmetric)
TAG_COEXIST = "coexist"  # co-occurrence  (symmetric)
TAG_EXCLUSIVE = "exclusive"  # mutual exclusion (symmetric)
TAG_RESP_EXIST = "responded_existence"  # x present => y present, no order
TAG_NEG_ORDER = "neg_order"  # reverse-order evidence from a Not* constraint

# Maps each ARM relation kind to the model tags that satisfy it natively vs. via
# a workaround. Paradigm-independent; the asymmetry lives in PARADIGM_IMPOSSIBLE.
#
# Rationale per kind (see module docstring for the literature anchors):
RelationRule = dict  # {"native": frozenset[str], "forced": frozenset[str]}

TRANSLATION: dict[str, RelationRule] = {
    # a immediately & always together with b  -> strict chain
    "direct_equivalence": {
        "native": frozenset({TAG_CHAIN}),
        "forced": frozenset({TAG_ORDER, TAG_COEXIST, TAG_PARALLEL}),
    },
    # a immediately before b, one-way existence implication
    "direct_implication": {
        "native": frozenset({TAG_CHAIN}),
        "forced": frozenset({TAG_ORDER, TAG_RESP_EXIST}),
    },
    # immediate order, no existential tie (rare)
    "direct_none": {
        "native": frozenset({TAG_CHAIN}),
        "forced": frozenset({TAG_ORDER}),
    },
    # eventual order, both always occur
    "eventual_equivalence": {
        "native": frozenset({TAG_ORDER, TAG_CHAIN}),
        "forced": frozenset({TAG_COEXIST, TAG_PARALLEL, TAG_NEG_ORDER}),
    },
    # eventual order, one-way implication (dominant bucket in structured logs)
    "eventual_implication": {
        "native": frozenset({TAG_ORDER, TAG_CHAIN}),
        "forced": frozenset({TAG_RESP_EXIST, TAG_NEG_ORDER, TAG_COEXIST}),
    },
    # eventual order, no existential tie
    "eventual_none": {
        "native": frozenset({TAG_ORDER, TAG_CHAIN}),
        "forced": frozenset({TAG_NEG_ORDER, TAG_COEXIST, TAG_PARALLEL}),
    },
    # always together, no order  -> concurrency / co-existence
    "none_equivalence": {
        "native": frozenset({TAG_PARALLEL, TAG_COEXIST}),
        "forced": frozenset({TAG_ORDER, TAG_CHAIN}),
    },
    # order-free existence implication  -> RespondedExistence
    "none_implication": {
        "native": frozenset({TAG_RESP_EXIST, TAG_COEXIST}),
        "forced": frozenset({TAG_ORDER, TAG_CHAIN, TAG_PARALLEL}),
    },
    # mutually exclusive  -> XOR / NotCoExistence
    "none_negated_equivalence": {
        "native": frozenset({TAG_EXCLUSIVE}),
        "forced": frozenset({TAG_NEG_ORDER}),
    },
    # no relation expected
    "none_none": {"native": frozenset(), "forced": frozenset()},
}

# Relation kinds a paradigm structurally cannot express -> not_applicable
# (excluded from the score denominator; Decision 3).
#   imperative: process trees cannot express an order-free existential
#               implication (implication without sequence/choice/parallel).
#   declarative / fusion: can express every ARM kind (order via Response/
#               Precedence, co-occurrence via CoExistence, exclusion via
#               NotCoExistence, implication via RespondedExistence).
PARADIGM_IMPOSSIBLE: dict[ParadigmKind, frozenset[str]] = {
    "imperative": frozenset({"none_implication"}),
    "declarative": frozenset(),
    "fusion": frozenset(),
}

_MINER_TO_PARADIGM: dict[str, ParadigmKind] = {
    "imp": "imperative",
    "decl": "declarative",
    "fus": "fusion",
}


# --------------------------------------------------------------------------- #
# Data interfaces
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ExpectedRelation:
    """One ARM relation, direction-normalised to a single ``source -> target``."""

    source: str
    target: str
    kind: ArmRelationKind
    temporal_type: Optional[str]
    temporal_direction: Optional[str]
    existential_type: Optional[str]
    existential_direction: Optional[str]
    is_present: bool  # False  =>  none_none  =>  correctly_absent expected


@dataclass(frozen=True)
class ModelRelationIndex:
    """Normalised model assertions, keyed by *directed* activity pair."""

    by_pair: dict[tuple[str, str], frozenset[str]]
    activities: frozenset[str]
    paradigm: ParadigmKind

    def tags(self, source: str, target: str) -> frozenset[str]:
        return self.by_pair.get((source, target), frozenset())


@dataclass(frozen=True)
class RelationVerdict:
    relation: ExpectedRelation
    verdict: Verdict
    matched_construct: Optional[str]
    rationale: str


@dataclass
class CoverageReport:
    log_id: str
    miner: ParadigmKind
    verdicts: list[RelationVerdict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    coverage_score: Optional[float] = None
    absence_precision: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "miner": self.miner,
            "coverage_score": self.coverage_score,
            "absence_precision": self.absence_precision,
            "counts": self.counts,
            "verdicts": [
                {
                    "source": v.relation.source,
                    "target": v.relation.target,
                    "kind": v.relation.kind,
                    "verdict": v.verdict,
                    "matched_construct": v.matched_construct,
                    "rationale": v.rationale,
                }
                for v in self.verdicts
            ],
        }


# --------------------------------------------------------------------------- #
# ARM side: build the expected relations (direction normalisation)
# --------------------------------------------------------------------------- #

def _relation_kind(temporal_type: Optional[str], existential_type: Optional[str]) -> ArmRelationKind:
    """Map an ARM cell's (temporal, existential) pair to a canonical kind.

    NegatedEquivalence / Nand (mutual exclusion) dominate any temporal value:
    two mutually exclusive activities cannot share a temporal order.
    """
    et = existential_type
    if et in ("NegatedEquivalence", "Nand"):
        return "none_negated_equivalence"

    # Treat the rare "Or" as an implication-flavoured tie.
    existential = "Implication" if et == "Or" else et

    tt = temporal_type
    if tt == "Direct":
        if existential == "Equivalence":
            return "direct_equivalence"
        if existential == "Implication":
            return "direct_implication"
        return "direct_none"
    if tt == "Eventual":
        if existential == "Equivalence":
            return "eventual_equivalence"
        if existential == "Implication":
            return "eventual_implication"
        return "eventual_none"
    # temporal None
    if existential == "Equivalence":
        return "none_equivalence"
    if existential == "Implication":
        return "none_implication"
    return "none_none"


def _orient(cell_fwd: dict, cell_bwd: dict) -> tuple[dict, str, str]:
    """Pick the canonical orientation for an unordered pair.

    Returns ``(canonical_cell, source, target)``. ``cell_fwd`` is the ``a->b``
    cell, ``cell_bwd`` the ``b->a`` cell (a, b in sorted order).
    """
    a, b = cell_fwd["from"], cell_fwd["to"]

    # 1) Temporal order, if any, fixes the direction (Forward => source before).
    for cell in (cell_fwd, cell_bwd):
        if cell.get("temporal_type"):
            if cell.get("temporal_direction") == "Forward":
                return cell, cell["from"], cell["to"]
            # Backward: the order runs the other way; use the mirror cell so
            # source is the earlier activity.
            return cell, cell["to"], cell["from"]

    # 2) No temporal order: orient by existential implication direction.
    for cell in (cell_fwd, cell_bwd):
        et = cell.get("existential_type")
        ed = cell.get("existential_direction")
        if et in ("Implication", "Or"):
            if ed == "Forward":
                return cell, cell["from"], cell["to"]
            if ed == "Backward":
                return cell, cell["to"], cell["from"]

    # 3) Symmetric (Equivalence / NegatedEquivalence / None): deterministic order.
    return cell_fwd, a, b


def build_expected_relations(arm: dict) -> list[ExpectedRelation]:
    """Direction-normalise the ARM ``cells`` into one relation per unordered pair.

    The ARM matrix stores both ``a->b`` and ``b->a``; this collapses each pair to
    a single :class:`ExpectedRelation` (no double counting). ``none_none`` pairs
    are kept with ``is_present=False`` as ``correctly_absent`` candidates.
    """
    cells = arm.get("cells", [])
    by_pair: dict[tuple[str, str], dict[str, dict]] = {}
    for cell in cells:
        a, b = cell["from"], cell["to"]
        key = tuple(sorted((a, b)))
        by_pair.setdefault(key, {})[(a, b)] = cell

    relations: list[ExpectedRelation] = []
    for (a, b), pair in sorted(by_pair.items()):
        cell_fwd = pair.get((a, b))
        cell_bwd = pair.get((b, a))
        if cell_fwd is None or cell_bwd is None:
            # Defensive: a matrix should always carry both directions.
            only = cell_fwd or cell_bwd
            cell_fwd = cell_bwd = only

        canonical, source, target = _orient(cell_fwd, cell_bwd)
        kind = _relation_kind(canonical.get("temporal_type"), canonical.get("existential_type"))
        relations.append(
            ExpectedRelation(
                source=source,
                target=target,
                kind=kind,
                temporal_type=canonical.get("temporal_type"),
                temporal_direction=canonical.get("temporal_direction"),
                existential_type=canonical.get("existential_type"),
                existential_direction=canonical.get("existential_direction"),
                is_present=(kind != "none_none"),
            )
        )
    return relations


# --------------------------------------------------------------------------- #
# Model extractor: imperative (process tree footprint)
# --------------------------------------------------------------------------- #

@dataclass
class _Footprint:
    """Structural relations within a process-tree subtree."""

    activities: set[str]
    starts: set[str]
    ends: set[str]
    directly: set[tuple[str, str]]
    eventually: set[tuple[str, str]]
    parallel: set[tuple[str, str]]
    exclusive: set[tuple[str, str]]


def _leaf_footprint(label: str) -> _Footprint:
    return _Footprint(
        activities={label},
        starts={label},
        ends={label},
        directly=set(),
        eventually=set(),
        parallel=set(),
        exclusive=set(),
    )


def _merge_children(children: list[_Footprint]) -> _Footprint:
    fp = _Footprint(set(), set(), set(), set(), set(), set(), set())
    for c in children:
        fp.activities |= c.activities
        fp.directly |= c.directly
        fp.eventually |= c.eventually
        fp.parallel |= c.parallel
        fp.exclusive |= c.exclusive
    return fp


def _tree_footprint(node: dict) -> _Footprint:
    """Compute the footprint (directly/eventually-follows, parallel, exclusive)
    of a process-tree node. tau leaves (label is None) are ignored.

    Operator symbols: ``->`` sequence, ``X`` xor, ``+`` parallel, ``*`` loop,
    ``O`` optional. ``operator`` is None for leaves.
    """
    operator = node.get("operator")
    children = node.get("children") or []

    if not children:
        label = node.get("label")
        if label is None:
            return _Footprint(set(), set(), set(), set(), set(), set(), set())
        return _leaf_footprint(label)

    child_fps = [_tree_footprint(c) for c in children]
    # Drop empty (all-tau) children but keep positions for sequence/loop logic.
    fp = _merge_children(child_fps)

    if operator == "->":  # SEQUENCE
        for i, ci in enumerate(child_fps):
            for cj in child_fps[i + 1:]:
                # eventually: every activity of ci before every activity of cj
                for x in ci.activities:
                    for y in cj.activities:
                        fp.eventually.add((x, y))
            if i + 1 < len(child_fps):
                nxt = child_fps[i + 1]
                for x in ci.ends:
                    for y in nxt.starts:
                        fp.directly.add((x, y))
        fp.starts = _first_nonempty(child_fps, "starts")
        fp.ends = _last_nonempty(child_fps, "ends")

    elif operator == "X":  # XOR (exclusive choice)
        for i, ci in enumerate(child_fps):
            for cj in child_fps[i + 1:]:
                for x in ci.activities:
                    for y in cj.activities:
                        fp.exclusive.add((x, y))
                        fp.exclusive.add((y, x))
        fp.starts = set().union(*[c.starts for c in child_fps]) if child_fps else set()
        fp.ends = set().union(*[c.ends for c in child_fps]) if child_fps else set()

    elif operator == "+":  # PARALLEL (concurrency)
        for i, ci in enumerate(child_fps):
            for cj in child_fps[i + 1:]:
                for x in ci.activities:
                    for y in cj.activities:
                        fp.parallel.add((x, y))
                        fp.parallel.add((y, x))
        fp.starts = set().union(*[c.starts for c in child_fps]) if child_fps else set()
        fp.ends = set().union(*[c.ends for c in child_fps]) if child_fps else set()

    elif operator == "*":  # LOOP(do, redo, ...)
        do = child_fps[0]
        redo = child_fps[1] if len(child_fps) > 1 else None
        fp.starts = set(do.starts)
        fp.ends = set(do.ends)
        if redo is not None:
            for x in do.ends:
                for y in redo.starts:
                    fp.directly.add((x, y))
            for x in redo.ends:
                for y in do.starts:
                    fp.directly.add((x, y))
            for x in do.activities:
                for y in redo.activities:
                    fp.eventually.add((x, y))
                    fp.eventually.add((y, x))

    else:  # "O" optional or unknown: treat children as alternatives w/o order
        fp.starts = set().union(*[c.starts for c in child_fps]) if child_fps else set()
        fp.ends = set().union(*[c.ends for c in child_fps]) if child_fps else set()

    # eventually is a superset of directly
    fp.eventually |= fp.directly
    return fp


def _first_nonempty(child_fps: list[_Footprint], attr: str) -> set[str]:
    for c in child_fps:
        if c.activities:
            return set(getattr(c, attr))
    return set()


def _last_nonempty(child_fps: list[_Footprint], attr: str) -> set[str]:
    for c in reversed(child_fps):
        if c.activities:
            return set(getattr(c, attr))
    return set()


def extract_relations_imperative(result_data: dict) -> ModelRelationIndex:
    """Build a :class:`ModelRelationIndex` from an IMf result.

    Reads ``metrics.process_tree_structure``; if absent (stale cache) the caller
    should backfill it first (see :func:`load_model_index`).
    """
    metrics = result_data.get("metrics") or {}
    structure = metrics.get("process_tree_structure")
    if not structure:
        raise ValueError(
            "process_tree_structure missing from IMf result; backfill the cache "
            "or pass a result produced by the current evaluation.py."
        )
    fp = _tree_footprint(structure)

    by_pair: dict[tuple[str, str], set[str]] = {}

    def add(pair: tuple[str, str], tag: str) -> None:
        by_pair.setdefault(pair, set()).add(tag)

    for pair in fp.directly:
        add(pair, TAG_CHAIN)
        add(pair, TAG_ORDER)
    for pair in fp.eventually:
        add(pair, TAG_ORDER)
    for pair in fp.parallel:
        add(pair, TAG_PARALLEL)
    for pair in fp.exclusive:
        add(pair, TAG_EXCLUSIVE)

    return ModelRelationIndex(
        by_pair={k: frozenset(v) for k, v in by_pair.items()},
        activities=frozenset(fp.activities),
        paradigm="imperative",
    )


# --------------------------------------------------------------------------- #
# Model extractor: declarative (MINERful Declare constraints)
# --------------------------------------------------------------------------- #

def _declare_tags(template: str, acts: list[str]) -> list[tuple[tuple[str, str], str]]:
    """Map one Declare constraint to (directed pair, tag) entries.

    ``acts`` is ``[A]`` for unary or ``[A, B]`` for binary templates, where A is
    the activation and B the target. Ordering semantics: Response / Precedence /
    Succession all place A before B (order A->B). Chain variants add immediacy.
    """
    if len(acts) < 2:
        return []  # unary (Init/End/Participation/AtMost/AtLeast/Absence): no pair
    a, b = acts[0], acts[1]
    t = template

    if t in ("ChainSuccession", "ChainResponse", "ChainPrecedence"):
        return [((a, b), TAG_CHAIN), ((a, b), TAG_ORDER)]
    if t in ("Succession", "Response", "Precedence",
             "AlternateSuccession", "AlternateResponse", "AlternatePrecedence"):
        return [((a, b), TAG_ORDER)]
    if t == "CoExistence":
        return [((a, b), TAG_COEXIST), ((b, a), TAG_COEXIST)]
    if t == "RespondedExistence":
        return [((a, b), TAG_RESP_EXIST)]
    if t == "NotCoExistence":
        return [((a, b), TAG_EXCLUSIVE), ((b, a), TAG_EXCLUSIVE)]
    if t in ("NotSuccession", "NotChainSuccession", "NotResponse", "NotChainResponse",
             "NotPrecedence", "NotChainPrecedence"):
        # Every MINERful negative ordering template forbids the A->B order, so
        # each is reverse-order evidence for B->A (only ever yields "forced").
        # NotSuccession(base, implied) decomposes into its forward half
        # NotResponse(base, implied) AND its backward half NotPrecedence(base,
        # implied) — both on the SAME (base, implied) pair (MINERful
        # NotSuccession.java: getPossibleForward/BackwardConstraint). Hence
        # NotPrecedence(A,B) forbids A->B exactly like NotResponse(A,B); both map
        # to (B, A). (Chain variants are the directly-follows version.)
        return [((b, a), TAG_NEG_ORDER)]
    return []  # unknown template -> contributes nothing


def _index_from_tagged(
    entries: Iterable[tuple[tuple[str, str], str]],
    activities: Iterable[str],
    paradigm: ParadigmKind,
) -> ModelRelationIndex:
    by_pair: dict[tuple[str, str], set[str]] = {}
    for pair, tag in entries:
        by_pair.setdefault(pair, set()).add(tag)
    return ModelRelationIndex(
        by_pair={k: frozenset(v) for k, v in by_pair.items()},
        activities=frozenset(activities),
        paradigm=paradigm,
    )


def extract_relations_declarative(spec_json: dict) -> ModelRelationIndex:
    """Build a :class:`ModelRelationIndex` from a MINERful specification JSON."""
    entries: list[tuple[tuple[str, str], str]] = []
    for con in spec_json.get("constraints", []):
        params = con.get("parameters", [])
        acts = [p[0] for p in params if p]  # each param is a single-activity list
        entries.extend(_declare_tags(con.get("template", ""), acts))
    return _index_from_tagged(entries, spec_json.get("tasks", []), "declarative")


# --------------------------------------------------------------------------- #
# Model extractor: fusion (procedural net + declarative overlay)
# --------------------------------------------------------------------------- #

def _normalise_label(label: str) -> str:
    """Strip the FusionMINERful transition suffix (e.g. ``a+`` -> ``a``)."""
    return label.rstrip("+").strip() if isinstance(label, str) else label


def extract_relations_fusion(hybrid: dict, pnwa: Optional[dict] = None) -> ModelRelationIndex:
    """Build a :class:`ModelRelationIndex` from a Fusion hybrid (+ optional PNWA).

    Control-flow source, in order of preference:

    * **PNWA Petri net** (``pnwa`` carries ``places``/``transitions``/``arcs``):
      the structurally faithful representation. Its behavioural footprint
      (directly-/eventually-follows, parallel, exclusive) is derived by marking
      reachability — XOR (a place with several output transitions) and AND
      (a tau split/join) are recovered correctly. This is reading JSON, not a
      net image, so it honours the no-PNG-parsing rule (R1).
    * **Flat procedural graph** (``hybrid['procedural']`` nodes/edges): a lossy
      projection that cannot distinguish XOR/AND from sequence. Used only as a
      fallback when no usable PNWA net is present, or when the net is unsafe /
      cyclic / too large to profile.

    The declarative overlay (existential / negative constraints from the hybrid,
    plus any binary PNWA constraints) is merged on top in **both** paths.
    """
    entries: list[tuple[tuple[str, str], str]] = []
    activities: set[str] = set()

    decl_entries, decl_acts = _fusion_declarative_entries(hybrid, pnwa)
    activities |= decl_acts

    net = _fusion_net_entries(pnwa) if pnwa else None
    if net is not None:
        net_entries, net_acts = net
        entries.extend(net_entries)
        activities |= net_acts
    else:
        proc_entries, proc_acts = _fusion_procedural_entries(hybrid)
        entries.extend(proc_entries)
        activities |= proc_acts

    entries.extend(decl_entries)
    return _index_from_tagged(entries, activities, "fusion")


def _fusion_procedural_entries(
    hybrid: dict,
) -> tuple[list[tuple[tuple[str, str], str]], set[str]]:
    """Legacy fallback: tags from the flat procedural node/edge graph.

    Edges -> direct order (chain); transitive closure -> eventual order. Cannot
    express XOR/AND (that is why the PNWA net path is preferred when available).
    """
    entries: list[tuple[tuple[str, str], str]] = []
    activities: set[str] = set()

    proc = hybrid.get("procedural") or {}
    nodes = [n.get("label") for n in proc.get("nodes", []) if n.get("label")]
    activities.update(nodes)

    adj: dict[str, set[str]] = {}
    for edge in proc.get("edges", []):
        s, t = edge.get("source"), edge.get("target")
        if s is None or t is None:
            continue
        activities.update((s, t))
        adj.setdefault(s, set()).add(t)
        entries.append(((s, t), TAG_CHAIN))
        entries.append(((s, t), TAG_ORDER))
    for s, t in _reachable_pairs(adj):
        entries.append(((s, t), TAG_ORDER))
    return entries, activities


def _fusion_declarative_entries(
    hybrid: dict, pnwa: Optional[dict]
) -> tuple[list[tuple[tuple[str, str], str]], set[str]]:
    """Existential / negative overlay: hybrid declarative + PNWA binary constraints."""
    entries: list[tuple[tuple[str, str], str]] = []
    activities: set[str] = set()

    for con in (hybrid.get("declarative") or {}).get("constraints", []):
        acts = list(con.get("activities", []))
        activities.update(acts)
        template = con.get("template") or con.get("type") or ""
        entries.extend(_declare_tags(template, acts))

    if pnwa:
        for con in pnwa.get("constraints", []):
            if con.get("arity") != "binary":
                continue
            srcs = [_normalise_label(x) for x in con.get("source_labels", [])]
            tgts = [_normalise_label(x) for x in con.get("target_labels", [])]
            if srcs and tgts:
                acts = [srcs[0], tgts[0]]
                activities.update(acts)
                entries.extend(_declare_tags(con.get("type", ""), acts))
    return entries, activities


# --------------------------------------------------------------------------- #
# Fusion: PNWA Petri-net behavioural footprint (preferred control-flow source)
# --------------------------------------------------------------------------- #

_NET_MARKING_CAP = 20000  # bail to the legacy fallback above this state count


def _fusion_net_entries(
    pnwa: dict,
) -> Optional[tuple[list[tuple[tuple[str, str], str]], set[str]]]:
    """Control-flow tags from the PNWA Petri net, or ``None`` to fall back.

    Returns ``None`` (caller uses the flat procedural graph) when the PNWA has no
    net, or the net is unsafe / cyclic (loops) / too large to profile. Defensive:
    never raises — any structural surprise yields ``None``.
    """
    try:
        net = _pnwa_net(pnwa)
        if net is None:
            return None
        return _net_footprint(net)
    except Exception:  # malformed net -> fall back rather than crash
        return None


def _pnwa_net(pnwa: dict) -> Optional[dict]:
    """Parse a PNWA dict into a Petri net (preset/postset/markings/labels).

    Returns ``None`` if it does not carry a usable ``places``/``transitions``/
    ``arcs`` net with an initial marking.
    """
    places = pnwa.get("places") or []
    transitions = pnwa.get("transitions") or []
    arcs = pnwa.get("arcs") or []
    if not places or not transitions or not arcs:
        return None
    place_ids = {p["id"] for p in places if "id" in p}
    trans_ids = {t["id"] for t in transitions if "id" in t}
    if not place_ids or not trans_ids:
        return None

    preset: dict[str, set[str]] = {t: set() for t in trans_ids}
    postset: dict[str, set[str]] = {t: set() for t in trans_ids}
    for a in arcs:
        s, d = a.get("source_id"), a.get("target_id")
        if s in place_ids and d in trans_ids:
            preset[d].add(s)
        elif s in trans_ids and d in place_ids:
            postset[s].add(d)

    init = frozenset(p["id"] for p in places if p.get("in_initial_marking"))
    if not init:
        return None

    label: dict[str, Optional[str]] = {}
    for t in transitions:
        tid = t.get("id")
        if tid is None:
            continue
        label[tid] = None if t.get("invisible") else _normalise_label(t.get("label") or "")

    # Transitions with an empty preset would fire unboundedly; drop them.
    fireable_transitions = [t for t in trans_ids if preset[t]]
    return {
        "preset": preset,
        "postset": postset,
        "init": init,
        "label": label,
        "transitions": fireable_transitions,
    }


def _net_reachability(
    net: dict,
) -> Optional[tuple[set[frozenset], list[tuple[frozenset, str, frozenset]]]]:
    """BFS over safe-net markings (place-id frozensets).

    Returns ``(markings, edges)`` or ``None`` if the net is 1-unsafe (a produced
    place is already marked) or exceeds :data:`_NET_MARKING_CAP`.
    """
    preset, postset = net["preset"], net["postset"]
    init = net["init"]
    seen: set[frozenset] = {init}
    edges: list[tuple[frozenset, str, frozenset]] = []
    queue: list[frozenset] = [init]
    while queue:
        m = queue.pop()
        for t in net["transitions"]:
            pre = preset[t]
            if pre <= m:
                post = postset[t]
                if (post - pre) & m:
                    return None  # 1-unsafe -> not profilable this way
                m2 = frozenset((m - pre) | post)
                edges.append((m, t, m2))
                if m2 not in seen:
                    seen.add(m2)
                    if len(seen) > _NET_MARKING_CAP:
                        return None
                    queue.append(m2)
    return seen, edges


def _has_cycle(adj: dict[frozenset, set[frozenset]]) -> bool:
    """True if the marking-reachability graph has a cycle (i.e. the net loops)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[frozenset, int] = {}

    def visit(start: frozenset) -> bool:
        stack = [(start, iter(adj.get(start, ())))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                c = color.get(nxt, WHITE)
                if c == GRAY:
                    return True
                if c == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(adj.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
        return False

    for n in list(adj.keys()):
        if color.get(n, WHITE) == WHITE and visit(n):
            return True
    return False


def _visible_after_only_taus(net: dict, marking: frozenset) -> set[str]:
    """Visible transitions fireable from ``marking`` after firing only taus.

    This is the directly-follows frontier: an activity reachable without any
    intervening *visible* transition.
    """
    preset, postset, label = net["preset"], net["postset"], net["label"]
    seen = {marking}
    stack = [marking]
    visible: set[str] = set()
    while stack:
        m = stack.pop()
        for t in net["transitions"]:
            pre = preset[t]
            if not pre <= m:
                continue
            lab = label.get(t)
            if lab is not None:
                visible.add(lab)
            else:  # tau: traverse it (only taus allowed between)
                post = postset[t]
                if (post - pre) & m:
                    continue
                m2 = frozenset((m - pre) | post)
                if m2 not in seen:
                    seen.add(m2)
                    stack.append(m2)
    return visible


def _net_footprint(
    net: dict,
) -> Optional[tuple[list[tuple[tuple[str, str], str]], set[str]]]:
    """Behavioural footprint of a safe, acyclic Petri net via reachability.

    Derives, between visible transitions (activities):
      * ``chain``     - directly-follows (only taus between)  -> CHAIN + ORDER
      * ``order``     - strict weak order (x before y, never y before x) -> ORDER
      * ``parallel``  - interleaving both ways                -> PARALLEL
      * ``exclusive`` - never co-occur (different choice arms) -> EXCLUSIVE

    Returns ``None`` for unsafe / cyclic / oversized nets so the caller falls
    back to the flat procedural graph (loops would conflate repetition with
    concurrency in this profile).
    """
    reach = _net_reachability(net)
    if reach is None:
        return None
    _markings, edges = reach

    adj: dict[frozenset, set[frozenset]] = {}
    fireable: dict[frozenset, set[str]] = {}
    for m, t, m2 in edges:
        adj.setdefault(m, set()).add(m2)
        fireable.setdefault(m, set()).add(t)
    if _has_cycle(adj):
        return None

    label = net["label"]

    # reach_fire(m): transitions fireable at m or any successor (DAG -> memoise).
    rf_memo: dict[frozenset, set[str]] = {}

    def reach_fire(m: frozenset) -> set[str]:
        cached = rf_memo.get(m)
        if cached is not None:
            return cached
        acc = set(fireable.get(m, ()))
        for m2 in adj.get(m, ()):
            acc |= reach_fire(m2)
        rf_memo[m] = acc
        return acc

    acts = {lbl for lbl in label.values() if lbl is not None}
    # Only transitions that ACTUALLY fire somewhere carry behavioural evidence.
    # A dead / orphaned transition (no arcs, e.g. an entropy-abstracted activity)
    # must NOT be inferred exclusive-with-everything — the net simply says
    # nothing about it, so it gets no tag (-> "missing" downstream).
    fired = {label[t] for (_m, t, _m2) in edges if label.get(t) is not None}
    weak: set[tuple[str, str]] = set()   # (x, y): y can occur after x
    chain: set[tuple[str, str]] = set()  # (x, y): y directly follows x

    for m, t, m2 in edges:
        x = label.get(t)
        if x is None:
            continue
        for u in reach_fire(m2):
            y = label.get(u)
            if y is not None and y != x:
                weak.add((x, y))
        for y in _visible_after_only_taus(net, m2):
            if y != x:
                chain.add((x, y))

    entries: list[tuple[tuple[str, str], str]] = []
    for x, y in chain:
        entries.append(((x, y), TAG_CHAIN))
        entries.append(((x, y), TAG_ORDER))
    for x in fired:
        for y in fired:
            if x == y:
                continue
            xy = (x, y) in weak
            yx = (y, x) in weak
            if xy and yx:
                entries.append(((x, y), TAG_PARALLEL))
            elif xy:
                entries.append(((x, y), TAG_ORDER))
            elif not xy and not yx:
                # Both fire but never co-occur in any execution -> genuine XOR.
                entries.append(((x, y), TAG_EXCLUSIVE))
    return entries, acts


def _reachable_pairs(adj: dict[str, set[str]]) -> set[tuple[str, str]]:
    """All (x, y) with a directed path x -> ... -> y (length >= 1)."""
    pairs: set[tuple[str, str]] = set()
    for start in adj:
        stack = list(adj.get(start, ()))
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            pairs.add((start, cur))
            stack.extend(adj.get(cur, ()))
    return pairs


# --------------------------------------------------------------------------- #
# Classification & aggregation
# --------------------------------------------------------------------------- #

def classify_relation(
    rel: ExpectedRelation, idx: ModelRelationIndex, paradigm: ParadigmKind
) -> RelationVerdict:
    tags = idx.tags(rel.source, rel.target)

    if not rel.is_present:  # none_none
        if tags:
            return RelationVerdict(
                rel, "spurious", _first(tags),
                f"ARM has no relation but model asserts {sorted(tags)}",
            )
        return RelationVerdict(rel, "correctly_absent", None, "ARM none, model none")

    if rel.kind in PARADIGM_IMPOSSIBLE.get(paradigm, frozenset()):
        return RelationVerdict(
            rel, "not_applicable", None,
            f"{rel.kind} is not expressible in the {paradigm} paradigm",
        )

    rule = TRANSLATION[rel.kind]
    native_hit = tags & rule["native"]
    if native_hit:
        return RelationVerdict(rel, "native", _first(native_hit), f"native via {sorted(native_hit)}")
    forced_hit = tags & rule["forced"]
    if forced_hit:
        return RelationVerdict(rel, "forced", _first(forced_hit), f"forced via {sorted(forced_hit)}")
    return RelationVerdict(rel, "missing", None, f"no construct for {rel.kind}")


def _first(tags: Iterable[str]) -> Optional[str]:
    items = sorted(tags)
    return items[0] if items else None


def compute_sf3_score(counts: dict[str, int]) -> tuple[Optional[float], Optional[float]]:
    """Return ``(coverage_score, absence_precision)`` — SF-2 evidence aggregates.

    Name kept as ``compute_sf3_score`` for import/test stability; the dimension
    is SF-2 (see module docstring), not a separate SF-3 item.

    coverage_score   = (native + 0.5*forced + correctly_absent)
                       / (native + forced + missing + correctly_absent + spurious)
                       over *every* ARM relation — present **and** absent. The
                       ``(—,—)`` pairs are graded too: ``correctly_absent`` (model
                       rightly says nothing) earns full credit, ``spurious`` (model
                       invents a relation) is penalised. ``not_applicable`` is the
                       only verdict excluded from the denominator (a paradigm is
                       never scored for what it structurally cannot express).
    absence_precision = correctly_absent / (correctly_absent + spurious).
    Either is ``None`` when its denominator is zero.
    """
    native = counts.get("native", 0)
    forced = counts.get("forced", 0)
    missing = counts.get("missing", 0)
    correct = counts.get("correctly_absent", 0)
    spurious = counts.get("spurious", 0)
    denom = native + forced + missing + correct + spurious
    coverage = (native + 0.5 * forced + correct) / denom if denom else None

    abs_denom = correct + spurious
    absence = correct / abs_denom if abs_denom else None
    return coverage, absence


def _is_dominant(rel: ExpectedRelation, min_support: Optional[float]) -> bool:
    """Whether an ARM relation counts as *dominant* for the SF-2 evidence view.

    A relation is dominant iff it is present above the ARM thresholds
    (``is_present``). The matrix tool already applies the temporal/existential
    thresholds before emitting a cell, so those thresholds *are* the dominance
    dial — there is no separate support/frequency field on an ARM cell
    (verified against the real ``matrix_classifier`` output). ``min_support`` is
    therefore honoured only if the relation actually carries a ``support``
    attribute; it is a no-op otherwise (we never invent a frequency).
    """
    if not rel.is_present:
        return False
    if min_support is not None:
        support = getattr(rel, "support", None)
        if support is not None and support < min_support:
            return False
    return True


def map_coverage(
    arm: dict,
    idx: ModelRelationIndex,
    paradigm: ParadigmKind,
    log_id: str,
    *,
    dominant_only: bool = False,
    min_support: Optional[float] = None,
) -> CoverageReport:
    """Classify every ARM relation of a log against a discovered model.

    ``counts`` and the derived ``coverage_score`` always span **every** ARM
    relation — present *and* absent — so the ``none_none`` ``(—,—)`` pairs are
    graded too (``correctly_absent`` rewarded, ``spurious`` penalised; see
    :func:`compute_sf3_score`).

    ``dominant_only=True`` is now purely a **display** filter: ``verdicts`` lists
    only the log's *dominant* (present) relations (see :func:`_is_dominant`) so
    the per-relation table is not swamped by the O(n²) ``correctly_absent`` pairs.
    The score is unaffected by this flag — the absent pairs still count. The
    default (``False``) lists every relation in ``verdicts``.
    """
    relations = build_expected_relations(arm)
    all_verdicts = [classify_relation(rel, idx, paradigm) for rel in relations]

    # Score over every relation (present + absent): correctly_absent/spurious are
    # graded, not dropped.
    counts: dict[str, int] = {}
    for v in all_verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    coverage, absence = compute_sf3_score(counts)

    # dominant_only only trims the displayed verdict table, never the score.
    if dominant_only:
        verdicts = [v for v in all_verdicts if _is_dominant(v.relation, min_support)]
    else:
        verdicts = all_verdicts

    return CoverageReport(
        log_id=log_id,
        miner=paradigm,
        verdicts=verdicts,
        counts=counts,
        coverage_score=coverage,
        absence_precision=absence,
    )


# --------------------------------------------------------------------------- #
# Loaders (wire ArmResult + cached model JSONs)
# --------------------------------------------------------------------------- #

def load_model_index(miner: str, result_data: dict, *, log_path: Optional[Path] = None) -> ModelRelationIndex:
    """Build a model index from a rehydrated result dict for ``miner`` in
    {"imp", "decl", "fus"}.

    For IMf, if ``process_tree_structure`` is missing (stale cache) and
    ``log_path`` is given, the process tree is recomputed from the log.
    """
    if miner == "imp":
        metrics = result_data.get("metrics") or {}
        if not metrics.get("process_tree_structure") and log_path is not None:
            result_data = _backfill_process_tree(result_data, log_path)
        return extract_relations_imperative(result_data)

    if miner == "decl":
        spec_path = (result_data.get("metrics") or {}).get("json_path")
        if not spec_path or not Path(spec_path).is_file():
            raise FileNotFoundError(f"MINERful spec JSON not found: {spec_path}")
        return extract_relations_declarative(_load_json(spec_path))

    if miner == "fus":
        run_data = result_data.get("run_data") or {}
        hybrid_path = run_data.get("hybrid_model_path")
        pnwa_path = run_data.get("pnwa_model_path")
        if not hybrid_path or not Path(hybrid_path).is_file():
            raise FileNotFoundError(f"Fusion hybrid_model.json not found: {hybrid_path}")
        pnwa = _load_json(pnwa_path) if pnwa_path and Path(pnwa_path).is_file() else None
        return extract_relations_fusion(_load_json(hybrid_path), pnwa)

    raise ValueError(f"unknown miner {miner!r}")


def _backfill_process_tree(result_data: dict, log_path: Path) -> dict:
    """Recompute the process tree from the log and inject the structure fields.

    Imported lazily so the module stays usable without pm4py when only the
    declarative / fusion paths are needed.
    """
    import warnings

    warnings.filterwarnings("ignore")
    from pm4py.objects.log.importer.xes import importer as xes_importer

    from flex_compare.internal.imperative_miner.evaluation import (  # type: ignore
        _extract_process_tree,
        _serialize_process_tree_node,  # noqa: F401  (kept for clarity of source)
    )
    import pm4py

    log = xes_importer.apply(str(log_path))
    tree = pm4py.discover_process_tree_inductive(log)
    metrics = dict(result_data.get("metrics") or {})
    metrics.update(_extract_process_tree(tree))
    out = dict(result_data)
    out["metrics"] = metrics
    return out


def _load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def arm_coverage_for_log(
    log_path: Path, miner: str, *, temporal: float = 1.0, existential: float = 1.0
) -> CoverageReport:
    """End-to-end: ARM(log) + cached model(miner, log) -> CoverageReport."""
    from flex_compare.internal.shared.cache import result_cache
    from flex_compare.internal.shared.arm_runner import run_arm

    log_path = Path(log_path)
    arm = run_arm(log_path, temporal_threshold=temporal, existential_threshold=existential)
    log_id = result_cache.compute_log_id(log_path)
    entry = result_cache.lookup(miner, log_id)
    if entry is None:
        raise FileNotFoundError(f"no cached {miner} result for {log_id}")
    result_data = result_cache.rehydrate(entry)
    idx = load_model_index(miner, result_data, log_path=log_path)
    return map_coverage(arm, idx, _MINER_TO_PARADIGM[miner], log_id)


# --------------------------------------------------------------------------- #
# Debug CLI
# --------------------------------------------------------------------------- #

def _resolve_log_path(stem_or_path: str) -> Path:
    p = Path(stem_or_path)
    if p.is_file():
        return p
    from flex_compare.internal.shared.arm_runner import _REPO_ROOT  # type: ignore

    candidate = _REPO_ROOT / "data" / "with-case-ids" / f"{p.stem}.xes"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"could not resolve log: {stem_or_path}")


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="SF-2 (ARM native/forced evidence) — ARM-Coverage-Mapper (debug)")
    parser.add_argument("--log", required=True, help="log stem or path (e.g. Log01_structured)")
    parser.add_argument("--miner", required=True, choices=["imp", "decl", "fus"])
    parser.add_argument("--verbose", action="store_true", help="print per-relation verdicts")
    args = parser.parse_args(argv)

    log_path = _resolve_log_path(args.log)
    report = arm_coverage_for_log(log_path, args.miner)
    out = report.to_dict()
    if not args.verbose:
        out.pop("verdicts", None)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
