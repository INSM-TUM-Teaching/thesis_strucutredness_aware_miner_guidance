"""Single source of truth for the set of miners the workspace knows about.

Historically the miner set was hardcoded as the literal ``("imp", "decl", "fus")``
in three independent places — ``result_cache.MINERS``,
``batch_runner._DEFAULT_MINERS`` and ``dimensions.MINERS``. Adding a fourth miner
meant editing each of them (plus a dozen further wiring points: Dash component
IDs, per-miner callbacks, config cards, tab renderers, survey state).

This module centralises the *registration* of a miner — the paradigm-agnostic
identity metadata — so the miner set lives in one place. It also carries the
optional ``config_schema``/``runner_kind`` fields the new ``flex_compare`` app
consumes to render its configuration cards data-driven; ``comparison_app``
ignores those fields and stays on its hand-rolled cards.

To add a miner here, append a :class:`MinerSpec`. The membership-style consumers
(``result_cache``, ``batch_runner``, ``dimensions``) pick it up automatically;
the per-miner UI/callback wiring in ``comparison_app`` still has to be threaded
through by hand (see the ``pm4``-key wiring as the worked example).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Tuple

from flex_compare.internal.shared.registry.param_schema import ParamSpec


RunnerKind = Literal["module", "executable"]


@dataclass(frozen=True)
class MinerSpec:
    """Paradigm-agnostic registration metadata for one miner.

    Attributes mirror the dict shape that ``dimensions.MINERS`` used to carry,
    plus fields that prepare the ground for registry-driven wiring:

    * ``entry_point`` — dotted ``"module:function"`` path to the miner's
      ``run_evaluation`` adapter. ``None`` for the legacy three miners, whose
      run wiring predates the registry (they dispatch via ``run_miners._run_<id>``).
    * ``artifact_keys`` — result-dict keys (or nested-key tuples) holding
      artifact file paths the cache must copy. Empty tuple means "fall back to
      the legacy ``result_cache.ARTIFACT_PATH_KEYS`` table".
    * ``config_schema`` — declarative parameter list driving the
      ``flex_compare`` config UI. Empty for miners that keep their hand-rolled
      config cards (the legacy comparison_app miners).
    * ``runner_kind`` — ``"module"`` (default) for ``entry_point``-dispatched
      Python adapters; ``"executable"`` reserved for user-deployed binaries
      registered ad-hoc via flex_compare's inline-spec path.
    """

    id: str
    label: str
    short: str
    paradigm: str
    anchor_class: Optional[str]
    entry_point: Optional[str] = None
    artifact_keys: Tuple[Any, ...] = field(default_factory=tuple)
    config_schema: Tuple[ParamSpec, ...] = field(default_factory=tuple)
    runner_kind: RunnerKind = "module"
    # Kwargs the runner injects unconditionally on every adapter call. Use to
    # pre-bind algorithm switches (e.g. ``(("algorithm", "heuristics"),)``) so
    # one shared adapter can back N registry entries — one per algorithm —
    # without N wrapper functions. Tuple-of-pairs so MinerSpec stays hashable.
    fixed_kwargs: Tuple[Tuple[str, Any], ...] = field(default_factory=tuple)


# Thesis Phase-B locked defaults (single source — comparison_app reads via the
# legacy configuration.py module which is hand-rolled; flex_compare reads from
# the schemas below). Keep both in sync if the locked values ever change.
_IMP_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("noise_threshold", "Noise threshold", "slider", 0.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Inductive Miner — noise filtering ω. 0.0 = pure IM (no filtering)."),
    ParamSpec("conformance_method", "Conformance method", "dropdown", "token_replay",
              options=(("Token replay", "token_replay"), ("Alignments", "alignments"))),
)

_DECL_SCHEMA: Tuple[ParamSpec, ...] = (
    # MINERful Reloaded — event-based thresholds. All six apply conjunctively.
    ParamSpec("support", "Support", "slider", 0.04,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Event-based thresholds"),
    ParamSpec("confidence", "Confidence", "slider", 0.85,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Event-based thresholds"),
    ParamSpec("coverage", "Interest factor (coverage)", "slider", 0.04,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Event-based thresholds"),
    ParamSpec("trace_support", "Trace support", "slider", 0.125,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Trace-based thresholds"),
    ParamSpec("trace_confidence", "Trace confidence", "slider", 0.85,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Trace-based thresholds"),
    ParamSpec("trace_coverage", "Trace coverage", "slider", 0.125,
              min=0.0, max=1.0, step=0.005,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Trace-based thresholds"),
    ParamSpec("prune", "Declarative prune", "dropdown",
              "hierarchyconflictredundancydouble",
              options=(("none", "none"),
                       ("hierarchy", "hierarchy"),
                       ("hierarchyconflict", "hierarchyconflict"),
                       ("hierarchyconflictredundancy", "hierarchyconflictredundancy"),
                       ("hierarchyconflictredundancydouble",
                        "hierarchyconflictredundancydouble"))),
)

_FUS_SCHEMA: Tuple[ParamSpec, ...] = (
    # Heuristics Net block.
    ParamSpec("noise", "Relative-to-best threshold", "slider", 0.05,
              min=0.0, max=1.0, step=0.01,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("depend", "Dependency threshold", "slider", 0.9,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("l1l", "Length-one-loops threshold", "slider", 0.9,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("l2l", "Length-two-loops threshold", "slider", 0.9,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("long_dist", "Long-distance threshold", "slider", 0.9,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("all_connected", "All tasks connected", "toggle", ["on"],
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("long_dist_dep", "Long-distance dependencies", "toggle", [],
              group="Heuristics Net", kwarg_bundle="heuristics"),
    ParamSpec("unique_se", "Unique start/end tasks", "toggle", [],
              group="Heuristics Net", kwarg_bundle="heuristics"),
    # Fusion parameters block.
    ParamSpec("alpha", "Fusion weight (alpha)", "slider", 1.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("decl_support", "Constraint support", "slider", 1.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("entropy", "Activity entropy", "slider", 0.50,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("resilience", "Checking resilience", "slider", 0.1,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("im_fitness", "IM fitness threshold", "slider", 0.2,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("size", "Constraint limit (size mult.)", "number", 1,
              min=1, max=10, step=1,
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("cut", "Enhance (else cut)", "toggle", ["on"],
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("prune", "Prune constraints", "toggle", ["on"],
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("negative", "Include neg. constraints", "toggle", ["on"],
              group="Fusion Parameters", kwarg_bundle="fusion"),
    ParamSpec("check_model", "Check model after mining", "toggle", [],
              group="Fusion Parameters", kwarg_bundle="fusion"),
)

# Each pm4py algorithm gets its own per-spec schema so the UI only shows the
# params that actually apply. The shared adapter receives the algorithm string
# via the spec's ``fixed_kwargs``.
_PM4_CONFORMANCE = ParamSpec(
    "conformance_method", "Conformance method", "dropdown", "token_replay",
    options=(("Token replay", "token_replay"), ("Alignments", "alignments")),
)

_PM4_HEURISTICS_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("dependency_threshold", "Dependency threshold", "slider", 0.5,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Heuristics Miner — dependency-relation strength cutoff."),
    ParamSpec("and_threshold", "AND threshold", "slider", 0.65,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Heuristics Miner — AND-split detection threshold."),
    ParamSpec("loop_two_threshold", "Loop-2 threshold", "slider", 0.5,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Heuristics Miner — length-two loop detection threshold."),
    _PM4_CONFORMANCE,
)

_PM4_ALPHA_SCHEMA: Tuple[ParamSpec, ...] = (_PM4_CONFORMANCE,)
_PM4_ALPHA_PLUS_SCHEMA: Tuple[ParamSpec, ...] = (_PM4_CONFORMANCE,)

_PM4_INDUCTIVE_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("noise_threshold", "Noise threshold", "slider", 0.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Inductive Miner — filtering threshold (0.0 = no filtering)."),
    ParamSpec("disable_fallthroughs", "Disable fallthroughs", "toggle", [],
              help="Inductive Miner — verbiete tau-loop / flower fallthroughs (strenger)."),
    _PM4_CONFORMANCE,
)

_PM4_ILP_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("ilp_alpha", "ILP alpha", "slider", 1.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="ILP Miner — solver α (1.0 = strict; lower allows more)."),
    _PM4_CONFORMANCE,
)

_PM4_GENETIC_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("population_size", "Population size", "number", 500,
              min=10, max=2000, step=10,
              help="Genetic Miner — population size per generation."),
    ParamSpec("generations", "Generations", "number", 100,
              min=1, max=1000, step=1,
              help="Genetic Miner — number of generations."),
    ParamSpec("crossover_rate", "Crossover rate", "slider", 1.0,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Genetic Miner — Crossover-Wahrscheinlichkeit."),
    ParamSpec("mutation_rate", "Mutation rate", "slider", 0.01,
              min=0.0, max=1.0, step=0.01,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="Genetic Miner — Mutationsrate."),
    _PM4_CONFORMANCE,
)

# Declarative pm4py algorithms produce a constraint set, not a Petri net.
# No conformance / fitness path, but pm4py does expose discovery thresholds.
_PM4_DECLARE_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("min_support_ratio", "Min support ratio", "slider", 0.10,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="pm4py Declare — minimaler Support, damit ein Constraint gehalten wird."),
    ParamSpec("min_confidence_ratio", "Min confidence ratio", "slider", 0.75,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.75: "0.75", 1: "1"},
              help="pm4py Declare — minimale Konfidenz."),
)
_PM4_LOG_SKELETON_SCHEMA: Tuple[ParamSpec, ...] = (
    ParamSpec("noise_threshold", "Noise threshold", "slider", 0.10,
              min=0.0, max=1.0, step=0.05,
              marks={0: "0", 0.5: "0.5", 1: "1"},
              help="pm4py Log Skeleton — toleriertes Rauschen pro Relation."),
)

_PM4_ENTRY_POINT = (
    "flex_compare.internal.pm4py_miner.ui_app.adapters.evaluation_runner:run_evaluation"
)
_PM4_PETRI_ARTIFACT_KEYS: Tuple[Any, ...] = (
    "markdown_path", "data_path", "pdf_path", "petri_net_path",
)
_PM4_DECLARATIVE_ARTIFACT_KEYS: Tuple[Any, ...] = (
    "markdown_path", "data_path", "pdf_path", "declare_model_json_path",
    "declare_visualization_path", "declare_visualization_png_path",
)


# Canonical order matches the legacy ``result_cache.MINERS`` tuple so deriving
# ``miner_ids()`` from this registry is a no-op rename, not a reordering.
REGISTRY: Tuple[MinerSpec, ...] = (
    MinerSpec(id="imp", label="Inductive Miner", short="IM",
              paradigm="imperativ", anchor_class="structured",
              entry_point="flex_compare.internal.imperative_miner.ui_app.adapters.evaluation_runner:run_evaluation",
              artifact_keys=("markdown_path", "data_path", "pdf_path",
                             "petri_net_path", "petri_net_pnml_path",
                             "process_tree_path", "bpmn_path"),
              config_schema=_IMP_SCHEMA),
    MinerSpec(id="decl", label="MINERful", short="MINERful",
              paradigm="deklarativ", anchor_class="loosely",
              entry_point="flex_compare.internal.declarative_miner.ui_app.adapters.evaluation_runner:run_evaluation",
              artifact_keys=("markdown_path", "data_path", "pdf_path",
                             "declare_visualization_path",
                             "declare_visualization_png_path"),
              config_schema=_DECL_SCHEMA),
    MinerSpec(id="fus", label="FusionMINERful", short="Fusion",
              paradigm="hybrid", anchor_class="semi",
              entry_point="flex_compare.internal.fusion_miner.ui_app.adapters.evaluation_runner:run_evaluation",
              artifact_keys=(("run_data", "hybrid_rendered_png_path"),
                             ("run_data", "pnwa_rendered_png_path")),
              config_schema=_FUS_SCHEMA),
    # ─── pm4py algorithms — one registry entry per algorithm. ────────────────
    # All entries share one adapter; the ``fixed_kwargs`` field pre-binds
    # ``algorithm=<…>`` so the user never has to pick from a sub-dropdown.
    MinerSpec(id="pm4-heuristics", label="pm4py · Heuristics Miner",
              short="pm4py-H", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_HEURISTICS_SCHEMA,
              fixed_kwargs=(("algorithm", "heuristics"),)),
    MinerSpec(id="pm4-alpha", label="pm4py · Alpha Miner",
              short="pm4py-A", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_ALPHA_SCHEMA,
              fixed_kwargs=(("algorithm", "alpha"),)),
    MinerSpec(id="pm4-alpha_plus", label="pm4py · Alpha+ Miner",
              short="pm4py-A+", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_ALPHA_PLUS_SCHEMA,
              fixed_kwargs=(("algorithm", "alpha_plus"),)),
    MinerSpec(id="pm4-inductive", label="pm4py · Inductive Miner",
              short="pm4py-IM", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_INDUCTIVE_SCHEMA,
              fixed_kwargs=(("algorithm", "inductive"),)),
    MinerSpec(id="pm4-ilp", label="pm4py · ILP Miner",
              short="pm4py-ILP", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_ILP_SCHEMA,
              fixed_kwargs=(("algorithm", "ilp"),)),
    MinerSpec(id="pm4-genetic", label="pm4py · Genetic Miner (slow)",
              short="pm4py-GA", paradigm="imperativ", anchor_class="structured",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_PETRI_ARTIFACT_KEYS,
              config_schema=_PM4_GENETIC_SCHEMA,
              fixed_kwargs=(("algorithm", "genetic"),)),
    MinerSpec(id="pm4-declare", label="pm4py · Declare Miner",
              short="pm4py-D", paradigm="deklarativ", anchor_class="loosely",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_DECLARATIVE_ARTIFACT_KEYS,
              config_schema=_PM4_DECLARE_SCHEMA,
              fixed_kwargs=(("algorithm", "declare"),)),
    MinerSpec(id="pm4-log_skeleton", label="pm4py · Log Skeleton",
              short="pm4py-LS", paradigm="deklarativ", anchor_class="loosely",
              entry_point=_PM4_ENTRY_POINT,
              artifact_keys=_PM4_DECLARATIVE_ARTIFACT_KEYS,
              config_schema=_PM4_LOG_SKELETON_SCHEMA,
              fixed_kwargs=(("algorithm", "log_skeleton"),)),
)


def miner_ids() -> Tuple[str, ...]:
    """The registered miner ids, in canonical (registry) order."""
    return tuple(spec.id for spec in REGISTRY)


def miner_specs() -> Tuple[MinerSpec, ...]:
    return REGISTRY


def get(miner_id: str) -> Optional[MinerSpec]:
    for spec in REGISTRY:
        if spec.id == miner_id:
            return spec
    return None


def as_dict(miner_id: str) -> Optional[dict[str, str]]:
    """Return the ``dimensions.MINERS``-style dict for one miner, or ``None``.

    Keys: ``id``, ``label``, ``short``, ``paradigm``, ``anchor_class`` — the
    exact shape ``dimensions.py`` consumed before the registry existed.
    """
    spec = get(miner_id)
    if spec is None:
        return None
    return {
        "id": spec.id,
        "label": spec.label,
        "short": spec.short,
        "paradigm": spec.paradigm,
        "anchor_class": spec.anchor_class or "",
    }


def dicts_in_order(order: Tuple[str, ...]) -> list[dict[str, str]]:
    """Return ``as_dict`` entries for the given ids, skipping unknown ids.

    Lets a consumer impose its own display order (e.g. structured→semi→loosely)
    over the canonical registry order without re-hardcoding the metadata.
    """
    out: list[dict[str, str]] = []
    for mid in order:
        d = as_dict(mid)
        if d is not None:
            out.append(d)
    return out
