"""Tab 1 — Log selection + ARM heatmap + structuredness classification.

Styled with the same pm-* design system as comparison_app: ``pm-card`` cards,
``pm-section`` / ``pm-section-title`` wrappers, ``pm-btn`` / ``pm-btn-primary``
buttons, ``pm-slider`` sliders, ``pm-upload`` for the drag-and-drop zone.
"""
from __future__ import annotations

from pathlib import Path

from dash import dcc, html

from flex_compare.ui import ids


def _log_options(log_dir: Path) -> list[dict]:
    if not log_dir.is_dir():
        return []
    return [
        {"label": p.name, "value": str(p)}
        for p in sorted(log_dir.glob("*.xes"))
    ]


def render_layout(default_log_dir: Path, selected_log: str | None) -> html.Div:
    return html.Div(
        className="pm-page",
        children=[
            html.Div(
                className="pm-section",
                children=[
                    html.Div("Log & ARM", className="pm-section-title"),
                    html.Div(
                        className="pm-config-grid",
                        style={"gridTemplateColumns": "repeat(auto-fit, minmax(280px, 1fr))"},
                        children=[
                            _log_source_card(default_log_dir, selected_log),
                            _classification_card(),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="pm-section",
                children=[
                    _arm_heatmap_card(),
                ],
            ),
        ],
    )


def _log_source_card(default_log_dir: Path, selected_log: str | None) -> html.Div:
    return html.Div(
        className="pm-card",
        children=[
            html.Div(
                className="pm-card-header",
                children=html.Div([
                    html.Div("Event Log", className="pm-card-title"),
                    html.Div("Shared input across all miners",
                             className="pm-card-sub"),
                ]),
            ),
            html.Div(
                className="pm-folder-row",
                children=[
                    html.Span("📁", style={"fontSize": "12px"}),
                    html.Span(str(default_log_dir),
                              className="pm-folder-path"),
                ],
            ),

            html.Span("Select log file", className="pm-label"),
            dcc.Dropdown(
                id=ids.LOG_SELECT,
                options=_log_options(default_log_dir),
                value=selected_log,
                clearable=False,
                style={"fontSize": "13px", "marginBottom": "12px"},
            ),

            html.Span("Or upload .xes", className="pm-label"),
            dcc.Upload(
                id=ids.LOG_UPLOAD,
                accept=".xes",
                multiple=False,
                children=html.Div(
                    ["Drag & Drop or ", html.A("select a file")],
                    className="pm-upload",
                ),
            ),

            html.Div(id=ids.LOG_STATS,
                     style={"marginTop": "12px", "fontSize": "12px",
                            "color": "var(--text-muted)"}),
        ],
    )


def _classification_card() -> html.Div:
    return html.Div(
        className="pm-card",
        children=[
            html.Div(
                className="pm-card-header",
                children=html.Div([
                    html.Div("Structuredness Classification",
                             className="pm-card-title"),
                    html.Div("ARM (Andree et al. 2025)",
                             className="pm-card-sub"),
                ]),
            ),
            html.Div(id=ids.CLASSIFICATION_BADGE,
                     style={"marginBottom": "12px"}),

            html.Span("Temporal threshold", className="pm-label"),
            dcc.Slider(
                id=ids.ARM_TEMPORAL_SLIDER,
                min=0.0, max=1.0, step=0.05, value=1.0,
                marks={0: "0", 0.5: "0.5", 1: "1"},
                updatemode="mouseup",
                tooltip={"placement": "bottom", "always_visible": True},
                className="pm-slider",
            ),

            html.Span("Existential threshold", className="pm-label",
                      style={"marginTop": "8px"}),
            dcc.Slider(
                id=ids.ARM_EXISTENTIAL_SLIDER,
                min=0.0, max=1.0, step=0.05, value=1.0,
                marks={0: "0", 0.5: "0.5", 1: "1"},
                updatemode="mouseup",
                tooltip={"placement": "bottom", "always_visible": True},
                className="pm-slider",
            ),

            html.Button(
                "▶  Run ARM Classifier",
                id=ids.ARM_RUN_BTN, n_clicks=0,
                className="pm-btn pm-btn-primary pm-btn-sm",
                style={"width": "100%", "marginTop": "12px"},
            ),
        ],
    )


def _arm_heatmap_card() -> html.Div:
    return html.Div(
        className="pm-card",
        children=[
            html.Div(
                className="pm-card-header",
                children=html.Div([
                    html.Div("Activity-Relation Matrix",
                             className="pm-card-title"),
                    html.Div("Temporal score per (source → target) pair",
                             className="pm-card-sub"),
                ]),
            ),
            html.Div(id=ids.ARM_OUTPUT,
                     children="Run the classifier to see the ARM heatmap.",
                     className="pm-card-sub"),
        ],
    )
