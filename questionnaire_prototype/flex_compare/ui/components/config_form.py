"""Render a ``ParamSpec`` tuple as Dash components.

Widget styling mirrors ``miners/comparison_app/ui/components/configuration.py``:
``pm-label`` for field labels, ``pm-slider`` for sliders, ``pm-input`` for
text/number inputs, ``pm-toggle``/``pm-toggle-group`` for checklists,
``pm-card-section-title`` for ``group`` sub-section headers. ``visible_when``
is enforced by a callback in :mod:`ui.callbacks.config_callbacks`.
"""
from __future__ import annotations

from typing import Iterable

from dash import dcc, html

from flex_compare.internal.shared.registry.param_schema import ParamSpec

from flex_compare.ui.ids import fc_id


def _label(text: str) -> html.Span:
    return html.Span(text, className="pm-label")


def _slider(spec: ParamSpec, instance: str, value) -> dcc.Slider:
    marks = spec.marks
    if marks is None and spec.min is not None and spec.max is not None:
        mid = (spec.min + spec.max) / 2
        marks = {spec.min: str(spec.min), mid: str(mid), spec.max: str(spec.max)}
    return dcc.Slider(
        id=fc_id("config", instance, key=spec.key),
        value=value,
        min=spec.min,
        max=spec.max,
        step=spec.step,
        marks=marks,
        # Fire the change once on release, not on every drag tick — keeps
        # state.json writes (and ARM/runner recomputes) one-per-change.
        updatemode="mouseup",
        tooltip={"placement": "bottom", "always_visible": True},
        className="pm-slider",
    )


def _dropdown(spec: ParamSpec, instance: str, value) -> dcc.Dropdown:
    options = [{"label": lab, "value": val} for lab, val in (spec.options or ())]
    return dcc.Dropdown(
        id=fc_id("config", instance, key=spec.key),
        options=options,
        value=value,
        clearable=False,
        style={"fontSize": "13px"},
    )


def _toggle(spec: ParamSpec, instance: str, value) -> dcc.Checklist:
    return dcc.Checklist(
        id=fc_id("config", instance, key=spec.key),
        options=[{"label": f"  {spec.label}", "value": "on"}],
        value=value or [],
        className="pm-toggle",
    )


def _checkbox_group(spec: ParamSpec, instance: str, value) -> dcc.Checklist:
    options = [{"label": f"  {lab}", "value": val} for lab, val in (spec.options or ())]
    return dcc.Checklist(
        id=fc_id("config", instance, key=spec.key),
        options=options,
        value=value or [],
        className="pm-toggle",
    )


def _number(spec: ParamSpec, instance: str, value) -> dcc.Input:
    return dcc.Input(
        id=fc_id("config", instance, key=spec.key),
        type="number",
        min=spec.min,
        max=spec.max,
        step=spec.step,
        value=value,
        className="pm-input",
        style={"width": "100%"},
    )


def _text(spec: ParamSpec, instance: str, value) -> dcc.Input:
    return dcc.Input(
        id=fc_id("config", instance, key=spec.key),
        type="text",
        value=value or "",
        className="pm-input",
        style={"width": "100%"},
    )


_WIDGETS = {
    "slider": _slider,
    "dropdown": _dropdown,
    "toggle": _toggle,
    "checkbox_group": _checkbox_group,
    "number": _number,
    "text": _text,
}


def _widget(spec: ParamSpec, instance: str, value) -> html.Div:
    factory = _WIDGETS.get(spec.kind)
    if factory is None:
        return html.Div(f"unsupported widget kind: {spec.kind}",
                        style={"color": "var(--color-error)"})
    body = factory(spec, instance, value)
    # Always set ``style={}`` on the wrapper so callers (visible_when) can
    # mutate it without triggering ``'Div' object has no attribute 'style'``.
    # Toggles carry their label in the Checklist; skip the duplicate label.
    if spec.kind in ("toggle",):
        return html.Div(body, style={})
    return html.Div([_label(spec.label), body], style={})


def render_config_form(schema: Iterable[ParamSpec], instance: str, values: dict) -> html.Div:
    """Render ``schema`` as a Dash form keyed to ``instance``.

    ``values`` provides the current value for each :attr:`ParamSpec.key`;
    missing keys fall back to ``ParamSpec.default``. Specs sharing a ``group``
    are clustered under a ``pm-card-section-title`` sub-section header.
    Adjacent toggles within a group are wrapped in a ``pm-toggle-group``
    container so they stack the way comparison_app's Fusion card does.
    """
    schema = list(schema)
    if not schema:
        return html.Div("(no configurable parameters)",
                        className="pm-card-sub",
                        style={"marginTop": "6px"})

    # Group preserving declaration order.
    sections: list[tuple[str | None, list[ParamSpec]]] = []
    by_group: dict[str | None, list[ParamSpec]] = {}
    for spec in schema:
        if spec.group not in by_group:
            by_group[spec.group] = []
            sections.append((spec.group, by_group[spec.group]))
        by_group[spec.group].append(spec)

    children: list = []
    for group_name, specs in sections:
        if group_name:
            children.append(
                html.Div(group_name, className="pm-card-section-title")
            )

        # Cluster runs of consecutive toggles inside a pm-toggle-group so they
        # render as a single block (matches Fusion card's checkbox stack).
        i = 0
        while i < len(specs):
            spec = specs[i]
            if spec.kind in ("toggle", "checkbox_group"):
                run: list[ParamSpec] = []
                while i < len(specs) and specs[i].kind in ("toggle", "checkbox_group"):
                    run.append(specs[i])
                    i += 1
                toggle_children = []
                for s in run:
                    value = values.get(s.key, s.default)
                    wrapper = _widget(s, instance, value)
                    if s.visible_when:
                        wrapper.id = fc_id("config-wrapper", instance, key=s.key)
                        wrapper.style = dict(wrapper.style or {})
                        is_visible = all(values.get(k) == v for k, v in s.visible_when)
                        if not is_visible:
                            wrapper.style["display"] = "none"
                    toggle_children.append(wrapper)
                children.append(html.Div(toggle_children, className="pm-toggle-group"))
                continue

            value = values.get(spec.key, spec.default)
            wrapper = _widget(spec, instance, value)
            if spec.visible_when:
                wrapper.id = fc_id("config-wrapper", instance, key=spec.key)
                wrapper.style = dict(wrapper.style or {})
                is_visible = all(values.get(k) == v for k, v in spec.visible_when)
                if not is_visible:
                    wrapper.style["display"] = "none"
            children.append(wrapper)
            i += 1

    return html.Div(children)
