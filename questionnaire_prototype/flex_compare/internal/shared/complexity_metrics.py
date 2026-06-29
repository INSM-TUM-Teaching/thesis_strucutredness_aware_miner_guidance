"""Structural complexity metrics for discovered Petri nets.

Currently exposes Cardoso's Control-Flow Complexity (CFC) in the Petri-net
variant from Mendling 2008 ("Metrics for Process Models", LNBIP 6):

    CFC = Σ |p•| over places p with |p•| > 1   (XOR-split contribution)
        + Σ 1   over transitions t with |t•| > 1  (AND-split contribution)

Standard Petri nets have no OR-splits, so the 2^n − 1 term from Cardoso's
original BPMN/EPC formulation does not apply. τ-transitions are counted
structurally, consistent with Inductive-Miner output that introduces silent
splits to encode branching.

The metric is meaningful for imperative (Petri-net) and the procedural part
of fusion models. It is **not defined** for declarative DECLARE constraint
models — those do not have explicit gateways.
"""
from __future__ import annotations


def compute_cfc(net) -> int:
    """Cardoso CFC for a Petri net (Mendling 2008 variant)."""
    cfc = 0
    for place in net.places:
        out_deg = len(place.out_arcs)
        if out_deg > 1:
            cfc += out_deg
    for transition in net.transitions:
        if len(transition.out_arcs) > 1:
            cfc += 1
    return cfc
