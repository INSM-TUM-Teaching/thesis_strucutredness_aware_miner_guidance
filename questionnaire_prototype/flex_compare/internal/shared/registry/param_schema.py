"""``ParamSpec`` — declarative description of a single miner parameter.

A miner's full UI is generated from a tuple of ``ParamSpec``s on its
``MinerSpec.config_schema``: sliders, dropdowns, toggles, checkbox groups,
optional sub-section grouping, and conditional visibility (e.g. a pm4py
``dependency_threshold`` field that should only render when
``algorithm == "heuristics"``).

The schema is data, not Dash code — both the new flex_compare app and the
future fit-tool render from the same source of truth. The existing
``comparison_app`` keeps its hand-rolled cards (its ``MinerSpec`` entries
default to an empty schema), so the additive change here is backwards-compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Tuple

ParamKind = Literal["slider", "dropdown", "toggle", "checkbox_group", "number", "text"]


@dataclass(frozen=True)
class ParamSpec:
    """One configurable parameter for a miner.

    Fields beyond ``key``/``label``/``kind``/``default`` are widget-kind-specific
    and ignored by the renderer where they do not apply.
    """

    key: str
    label: str
    kind: ParamKind
    default: Any

    # Slider / number ranges.
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    marks: Optional[dict] = None

    # Dropdown / checkbox_group choices: tuples of ``(display_label, value)``.
    options: Optional[Tuple[Tuple[str, Any], ...]] = None

    # Sub-section header in the rendered config form (e.g. "Heuristics Net",
    # "Fusion Parameters"). All specs with the same ``group`` cluster together.
    group: Optional[str] = None

    # Conditional visibility: render this field only if every ``(other_key, value)``
    # pair matches the live config. ``None`` = always visible.
    visible_when: Optional[Tuple[Tuple[str, Any], ...]] = None

    # If set, the runner bundles every schema entry sharing the same
    # ``kwarg_bundle`` into a single nested dict and passes it under that kwarg
    # to the adapter. E.g. ``kwarg_bundle="heuristics"`` causes ``heuristics``,
    # ``depend``, ``l1l`` etc. to arrive at the adapter as
    # ``heuristics={"noise": …, "depend": …, "l1l": …}`` — matches the bundled-
    # dict shape some adapters expect (Fusion). ``None`` keeps the flat
    # ``key=value`` kwarg shape every other built-in uses.
    kwarg_bundle: Optional[str] = None

    help: Optional[str] = None
