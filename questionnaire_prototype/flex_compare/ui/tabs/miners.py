"""Tab 2 — dynamic miner cards + add-miner modal + comparison strip.

Visually mirrors ``miners/comparison_app/ui/components/configuration.py``:
the cards container is a ``pm-config-grid`` (responsive auto-fit, same as
comparison_app's IM / MINERful / Fusion / pm4py row), the section is
wrapped in a ``pm-section`` + ``pm-section-title``, and every button uses
``pm-btn`` / ``pm-btn-primary`` / ``pm-btn-ghost``.
"""
from __future__ import annotations

from pathlib import Path

from dash import dcc, html

from flex_compare.internal.shared.registry import miner_registry

from flex_compare.state import FlexState
from flex_compare.ui import ids
from flex_compare.ui.components.miner_card import render_miner_card


def _log_options(log_dir: Path) -> list[dict]:
    if not log_dir.is_dir():
        return []
    return [
        {"label": p.name, "value": str(p)}
        for p in sorted(log_dir.glob("*.xes"))
    ]


def render_layout(state: FlexState, log_dir: Path) -> html.Div:
    return html.Div(
        className="pm-page",
        children=[
            html.Div(
                className="pm-section",
                children=[
                    _toolbar(state, log_dir),
                    html.Div(id=ids.MINER_CARDS_CONTAINER,
                             className="pm-config-grid",
                             # Override the fixed 4-column grid so dynamic
                             # miner counts (1, 5, 12) all lay out cleanly.
                             style={"gridTemplateColumns":
                                    "repeat(auto-fit, minmax(280px, 1fr))"},
                             children=[render_miner_card(i) for i in state.instances]),
                ],
            ),
            html.Div(id=ids.COMPARISON_STRIP, style={"marginTop": "28px"}),
            _add_miner_modal(),
        ],
    )


def _toolbar(state: FlexState, log_dir: Path) -> html.Div:
    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "10px",
               "marginBottom": "14px", "flexWrap": "wrap"},
        children=[
            html.Div("Miners", className="pm-section-title",
                     style={"margin": 0}),
            html.Div(
                style={"flex": "1", "minWidth": "220px",
                       "display": "flex", "alignItems": "center", "gap": "8px"},
                children=[
                    html.Span("Log:", className="pm-label",
                              style={"margin": 0, "whiteSpace": "nowrap"}),
                    dcc.Dropdown(
                        id=ids.MINER_TAB_LOG_SELECT,
                        options=_log_options(log_dir),
                        value=state.selected_log,
                        clearable=False,
                        style={"flex": "1", "fontSize": "13px",
                               "minWidth": "240px"},
                    ),
                ],
            ),
            html.Div(id="fc-toolbar-log-label",
                     style={"fontSize": "12px",
                            "color": "var(--text-muted)",
                            "marginRight": "8px"}),
            html.Button("⊘ Cancel all", id=ids.CANCEL_ALL_BTN, n_clicks=0,
                        title="Terminate every queued or running miner (best-effort).",
                        className="pm-btn pm-btn-ghost"),
            html.Button("▶ Run all", id=ids.RUN_ALL_BTN, n_clicks=0,
                        className="pm-btn pm-btn-primary"),
            html.Button("+ Add Miner", id=ids.ADD_MINER_BTN, n_clicks=0,
                        className="pm-btn"),
        ],
    )


# ── Add-Miner modal ─────────────────────────────────────────────────────────
def _add_miner_modal() -> html.Div:
    return html.Div(
        id=ids.ADD_MODAL,
        style={"display": "none"},  # toggled by callback
        children=[
            html.Div(
                style={"position": "fixed", "top": 0, "left": 0, "right": 0,
                       "bottom": 0, "background": "rgba(0,0,0,0.45)",
                       "zIndex": 200},
                children=html.Div(
                    className="pm-card pm-card-elevated",
                    style={"position": "absolute", "top": "8%", "left": "50%",
                           "transform": "translateX(-50%)", "width": "580px",
                           "maxHeight": "84vh", "overflow": "auto",
                           "boxShadow": "var(--shadow-2)"},
                    children=_add_modal_body(),
                ),
            ),
        ],
    )


def _registry_type_options() -> list[dict]:
    options = [
        {"label": f"{spec.label} ({spec.paradigm})", "value": f"registry:{spec.id}"}
        for spec in miner_registry.miner_specs()
    ]
    options.append({"label": "Custom (Python module)", "value": "inline:module"})
    options.append({"label": "Custom (executable)", "value": "inline:executable"})
    return options


def _add_modal_body() -> list:
    return [
        html.Div("Add Miner", className="pm-card-title",
                 style={"marginBottom": "12px"}),

        html.Span("Type", className="pm-label"),
        dcc.Dropdown(id=ids.ADD_MODAL_TYPE, options=_registry_type_options(),
                     clearable=False, value="registry:imp",
                     style={"fontSize": "13px"}),

        html.Span("Display label", className="pm-label",
                  style={"marginTop": "10px"}),
        dcc.Input(id=ids.ADD_MODAL_LABEL, type="text", value="",
                  className="pm-input", style={"width": "100%"}),

        html.Div(id="fc-add-modal-inline-fields", style={"display": "none"},
                 children=_inline_fields()),

        html.Div(id=ids.ADD_MODAL_FEEDBACK,
                 className="pm-alert pm-alert-error",
                 style={"marginTop": "10px", "display": "none"}),

        html.Div(style={"display": "flex", "justifyContent": "flex-end",
                        "gap": "8px", "marginTop": "16px"},
                 children=[
                     html.Button("Cancel", id=ids.ADD_MODAL_CANCEL, n_clicks=0,
                                 className="pm-btn pm-btn-ghost"),
                     html.Button("Add", id=ids.ADD_MODAL_CONFIRM, n_clicks=0,
                                 className="pm-btn pm-btn-primary"),
                 ]),
    ]


def _inline_fields() -> list:
    """Custom-module / custom-exec extras — only visible for inline:* types."""
    return [
        html.Div(
            style={"marginTop": "14px", "padding": "14px",
                   "background": "var(--bg-subtle)",
                   "borderRadius": "8px",
                   "border": "1px solid var(--border-default)"},
            children=[
                html.Div("Inline spec", className="pm-card-section-title",
                         style={"marginTop": 0}),

                html.Span("Paradigm", className="pm-label"),
                dcc.Dropdown(id=ids.ADD_MODAL_INLINE_PARADIGM,
                             options=[{"label": "imperativ", "value": "imperativ"},
                                      {"label": "deklarativ", "value": "deklarativ"},
                                      {"label": "hybrid", "value": "hybrid"}],
                             value="imperativ", clearable=False,
                             style={"fontSize": "13px"}),

                html.Span("Entry point (module:function) — required for Python module type",
                          className="pm-label", style={"marginTop": "8px"}),
                dcc.Input(id=ids.ADD_MODAL_INLINE_ENTRY_POINT, type="text",
                          placeholder="my_pkg.discovery:run",
                          className="pm-input", style={"width": "100%"}),

                html.Span("Command template — required for executable type",
                          className="pm-label", style={"marginTop": "8px"}),
                dcc.Input(id=ids.ADD_MODAL_INLINE_COMMAND, type="text",
                          placeholder="java -jar miner.jar --log {log} --out {outdir}",
                          className="pm-input", style={"width": "100%"}),

                html.Span("Output format", className="pm-label",
                          style={"marginTop": "8px"}),
                dcc.Dropdown(id=ids.ADD_MODAL_INLINE_OUTPUT_FORMAT,
                             options=[{"label": "PNML", "value": "pnml"},
                                      {"label": "Declare-JSON (MINERful)",
                                       "value": "declare-json"},
                                      {"label": "BPMN", "value": "bpmn"}],
                             value="pnml", clearable=False,
                             style={"fontSize": "13px"}),

                html.Span("Output file pattern (under {outdir})",
                          className="pm-label", style={"marginTop": "8px"}),
                dcc.Input(id=ids.ADD_MODAL_INLINE_OUTPUT_PATTERN, type="text",
                          value="model.pnml",
                          className="pm-input", style={"width": "100%"}),

                html.Span("Config parameters (JSON)", className="pm-label",
                          style={"marginTop": "8px"}),
                dcc.Textarea(id=ids.ADD_MODAL_INLINE_CONFIG, value="{}",
                             style={"width": "100%", "height": "62px",
                                    "fontFamily": "'IBM Plex Mono', monospace",
                                    "fontSize": "12px",
                                    "padding": "6px 10px",
                                    "border": "1px solid var(--border-default)",
                                    "borderRadius": "6px"}),
            ],
        ),
    ]
