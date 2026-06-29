"""Per-instance miner card, styled like comparison_app's configuration cards.

Same visual language as ``miners/comparison_app/ui/components/configuration.py``
(pm-card, pm-accent-{imp,decl,fus}, pm-card-header, pm-card-params,
pm-card-details, pm-card-configure-row, pm-btn-primary) — only the per-card
content is dynamic because flex_compare's miner list is user-built rather
than the three hand-rolled cards.
"""
from __future__ import annotations

from dash import dcc, html

from flex_compare.internal.shared.registry import miner_registry
from flex_compare.internal.shared.registry.param_schema import ParamSpec

from flex_compare.state import MinerInstance
from flex_compare.ui.components.config_form import render_config_form
from flex_compare.ui.ids import fc_id


# Paradigm → accent CSS class. Mirrors the colour mapping comparison_app
# uses for its three hardcoded cards.
_ACCENT_BY_PARADIGM = {
    "imperativ":  "pm-accent-imp",
    "deklarativ": "pm-accent-decl",
    "hybrid":     "pm-accent-fus",
}

_TITLE_COLOR_BY_PARADIGM = {
    "imperativ":  "var(--color-imp)",
    "deklarativ": "var(--color-decl)",
    "hybrid":     "var(--color-fus)",
}

_PARADIGM_LABEL = {
    "imperativ":  "Imperative",
    "deklarativ": "Declarative",
    "hybrid":     "Hybrid",
}

_PARADIGM_MODEL = {
    "imperativ":  "Petri Net",
    "deklarativ": "Declare Model",
    "hybrid":     "Petri Net + Declare",
}


def _resolve_schema(instance: MinerInstance) -> tuple[ParamSpec, ...]:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.config_schema if spec else ()
    if instance.inline_spec:
        return instance.inline_spec.config_schema
    return ()


def _resolve_paradigm(instance: MinerInstance) -> str:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.paradigm if spec else ""
    if instance.inline_spec:
        return instance.inline_spec.paradigm
    return ""


def _tool_text(instance: MinerInstance) -> str:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.short if spec else "?"
    if instance.inline_spec:
        kind = instance.inline_spec.runner_kind
        if kind == "module":
            return f"custom ({instance.inline_spec.entry_point or '?'})"
        if kind == "executable":
            return f"custom exec ({instance.inline_spec.output_format or '?'})"
    return "?"


def _param_row(label: str, value: str) -> html.Div:
    return html.Div(
        className="pm-param-row",
        children=[
            html.Span(label, className="pm-param-lbl"),
            html.Span(value, className="pm-param-val"),
        ],
    )


def render_miner_card(instance: MinerInstance) -> html.Div:
    paradigm = _resolve_paradigm(instance)
    accent = _ACCENT_BY_PARADIGM.get(paradigm, "")
    title_color = _TITLE_COLOR_BY_PARADIGM.get(paradigm)
    schema = _resolve_schema(instance)

    title_style = {"color": title_color} if title_color else {}

    return html.Div(
        id=fc_id("miner-card", instance.id),
        className=f"pm-card {accent}".strip(),
        children=[
            # Header: title + sub + status pill + remove button
            html.Div(
                className="pm-card-header",
                children=[
                    html.Div([
                        html.Div(
                            instance.label or "Unnamed miner",
                            className="pm-card-title",
                            style=title_style,
                        ),
                        html.Div(
                            f"{_PARADIGM_LABEL.get(paradigm, paradigm or '?')} · "
                            f"{_PARADIGM_MODEL.get(paradigm, 'Model')}",
                            className="pm-card-sub",
                        ),
                    ]),
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "8px"},
                        children=[
                            html.Span(
                                "● Ready",
                                id=fc_id("status", instance.id),
                                className="pm-pill pm-pill-idle",
                            ),
                            html.Button(
                                "×",
                                id=fc_id("remove-btn", instance.id),
                                n_clicks=0,
                                title="Remove this miner",
                                className="pm-btn pm-btn-icon",
                            ),
                        ],
                    ),
                ],
            ),

            # Read-only param summary (paradigm / model / tool)
            html.Div(
                className="pm-card-params",
                children=[
                    _param_row("Paradigm", _PARADIGM_LABEL.get(paradigm, paradigm or "?")),
                    _param_row("Model",    _PARADIGM_MODEL.get(paradigm, "Model")),
                    _param_row("Tool",     _tool_text(instance)),
                ],
            ),

            html.Button(
                "▶  Run",
                id=fc_id("run-btn", instance.id),
                className="pm-btn pm-btn-primary pm-btn-sm",
                n_clicks=0,
                style={"width": "100%", "marginBottom": "8px"},
            ),

            # Configure (expanded params) — same look as comparison_app's
            # html.Details/pm-card-details/pm-card-configure-row pattern.
            html.Details(
                open=False,
                className="pm-card-details",
                children=[
                    html.Summary(
                        className="pm-card-configure-row",
                        children=html.Span("Configure",
                                            className="pm-card-configure-text"),
                    ),
                    render_config_form(schema, instance.id, instance.config),
                ],
            ),

            # Per-instance running banner — visible while a job is queued
            # or running so the user always sees a clear "Running…" state.
            html.Div(
                id=fc_id("running-banner", instance.id),
                style={"display": "none"},
            ),

            # Per-instance result store + view container
            dcc.Store(id=fc_id("result-store", instance.id), data=None),
            html.Div(
                id=fc_id("result-view", instance.id),
                style={"marginTop": "12px", "minHeight": "40px"},
            ),
        ],
    )
