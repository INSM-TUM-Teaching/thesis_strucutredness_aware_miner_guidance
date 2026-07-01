"""Rich ARM (Activity Relationship Matrix) renderer for flex_compare.

Ported from ``miners.comparison_app.ui.components.tabs.arm`` with the color
scheme stripped: cell-codes, Andree percentages, classification, explainer are
kept. Verdict matrix and SF-2 coverage panels are deliberately not ported —
they hang on the comparison_app's fixed ``imp/decl/fus`` miner anchors, which
flex_compare's bring-your-own-miner architecture does not have.

The heatmap stays a Plotly figure (so the cell-code text + hover stay intact)
but its colorscale is a single neutral fill: the user reads the Andree code
from each cell, not a color.
"""
from __future__ import annotations

from typing import Any, Optional

import plotly.graph_objects as go
from dash import dcc, html

from flex_compare.internal.shared.arm_runner import ArmResult


# --------------------------------------------------------------------------- #
# Classification badge — plain text, no pill colors.
# --------------------------------------------------------------------------- #

def classification_badge(arm_result: dict | None) -> html.Div:
    """Compact badge for the right-hand classification card.

    No colored pill — just the class name in bold plus the matched-rule list.
    """
    if not arm_result:
        return html.Div(
            "(Run the classifier to see the ARM-derived class.)",
            className="pm-info", style={"fontSize": "12px"},
        )
    classification = arm_result.get("classification") or "—"
    matched = arm_result.get("matched_rules") or []
    return html.Div(children=[
        html.Div(classification,
                 style={"fontWeight": "600", "fontSize": "14px"}),
        html.Div(
            f"matched: {', '.join(matched) if matched else 'no rules matched'}",
            className="pm-info",
            style={"fontSize": "11px", "marginTop": "4px"},
        ),
    ])


def _body_classification_badge(classification: str, matched_rules: list[str]) -> html.Div:
    """Inline badge for the body header — same content, slightly larger."""
    return html.Div(
        style={"display": "flex", "alignItems": "baseline", "gap": "12px",
               "flexWrap": "wrap"},
        children=[
            html.Span(classification,
                      style={"fontWeight": "600", "fontSize": "14px"}),
            html.Span(
                f"matched rules: {', '.join(matched_rules) if matched_rules else '—'}",
                className="pm-info", style={"fontSize": "12px"},
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# Percentages table — Andree's nine pair classes.
# --------------------------------------------------------------------------- #

_PERCENTAGE_LABELS: list[tuple[str, str]] = [
    ("none_none",                  "(—,  —)"),
    ("none_implication",           "(—,  ⇒/⇐)"),
    ("none_equivalence",           "(—,  ⇔)"),
    ("none_negated_equivalence",   "(—,  ⇎)"),
    ("direct_none",                "(≺d, —)"),
    ("direct_any_existential",     "(≺d, *)"),
    ("eventual_implication",       "(≺e, ⇒/⇐)"),
    ("eventual_equivalence",       "(≺e, ⇔)"),
    ("eventual_any_existential",   "(≺e, *)"),
]


def _percentages_table(percentages: dict[str, float]) -> html.Div:
    rows = []
    for key, label in _PERCENTAGE_LABELS:
        value = percentages.get(key)
        pct = "—" if value is None else f"{value * 100:.1f} %"
        rows.append(html.Tr([
            html.Td(label, style={"fontFamily": "monospace"}),
            html.Td(pct, style={"textAlign": "right"}),
            html.Td(key, className="pm-info",
                    style={"fontSize": "11px"}),
        ]))
    return html.Div(
        className="pm-table-wrap",
        children=[
            html.Div("Andree percentages", className="pm-subheading"),
            html.Table(
                className="pm-table",
                children=[
                    html.Thead(html.Tr([
                        html.Th("Pair class", style={"width": "120px"}),
                        html.Th("Share", style={"width": "100px",
                                                "textAlign": "right"}),
                        html.Th("Field"),
                    ])),
                    html.Tbody(rows),
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# Explainer (collapsible).
# --------------------------------------------------------------------------- #

def _explainer() -> html.Details:
    relationship_rows = [
        ("(≺d, ⇔)", "B comes directly after A, both always co-occur",
         "Core path — belongs in the same sequence in the model."),
        ("(≺e, ⇔)", "B eventually follows A, both co-occur",
         "Tightly coupled, but ordering with intermediate steps."),
        ("(≺d, ⇒)", "B comes directly after A; A implies B, but not vice versa",
         "B is a mandatory follow-up to A; A itself is optional."),
        ("(≺,  ⇒)", "B eventually follows A; A implies B",
         "Optional predecessor with an unambiguous successor."),
        ("(—,  ⇒)", "If A happens, B also happens — order is free",
         "Parallel mandatory task."),
        ("(—,  ⇔)", "Both always co-occur, order is free",
         "Classic parallelization (AND-split)."),
        ("(—,  ⇎)", "Exactly one of the two occurs",
         "Exclusive choice (XOR)."),
        ("(≺d, —)", "B follows A directly, but existence-independent",
         "Pure ordering — rare."),
        ("(—,  —)", "A and B are fully independent",
         'Maximum flexibility — indicator for "unstructured".'),
    ]
    rel_table = html.Table(
        className="pm-table",
        style={"fontSize": "12px"},
        children=[
            html.Thead(html.Tr([
                html.Th("Code", style={"width": "90px",
                                        "fontFamily": '"STIX Two Math", serif'}),
                html.Th("Meaning", style={"width": "55%"}),
                html.Th("What it means in the model"),
            ])),
            html.Tbody([
                html.Tr([
                    html.Td(code, style={"fontFamily": '"STIX Two Math", serif',
                                          "whiteSpace": "nowrap"}),
                    html.Td(meaning),
                    html.Td(implication, className="pm-info"),
                ])
                for code, meaning, implication in relationship_rows
            ]),
        ],
    )

    struct_hints = html.Ul(
        style={"margin": "0", "paddingLeft": "20px", "fontSize": "13px"},
        children=[
            html.Li([
                html.B("Structured "),
                "→ Inductive Miner (Petri net).",
                html.Br(),
                "Many (≺, ⇔), (≺d, ⇔), (≺, ⇒); barely any (—, —). "
                "Activities have a clear order ", html.B("and"),
                " reliably co-occur — the core path is tightly "
                "wired.",
            ]),
            html.Li([
                html.B("Semi-structured "),
                "→ FusionMINERful (hybrid).",
                html.Br(),
                "Mix: locally sequential fragments (≺d, ⇔) ",
                html.B("and"),
                " temporally independent (—, ⇒) between fragments. "
                "Predefined blocks are flexibly combined.",
            ]),
            html.Li([
                html.B("Loosely Structured "),
                "→ MINERful (Declare).",
                html.Br(),
                'Little sequence, lots of (—, ⇒) and (—, ⇎). "Normal paths" '
                "are described via constraints, much is left to the "
                "knowledge worker.",
            ]),
            html.Li([
                html.B("Unstructured "),
                "→ no suitable discovery method.",
                html.Br(),
                "Dominated by (—, —) > 80 % or (—, ⇔) > 80 %. "
                "No reproducible dependencies — modeling "
                "is not worthwhile.",
            ]),
        ],
    )

    coupling_hint = html.Div(
        className="pm-alert pm-alert-info",
        style={"marginTop": "12px", "fontSize": "13px"},
        children=[
            html.B("Rule of thumb for reading the matrix: "),
            html.Br(),
            html.Span("• Tightly coupled → "),
            html.Code("(≺d, ⇔), (≺, ⇔), (≺d, ⇒)",
                      style={"fontFamily": '"STIX Two Math", serif'}),
            ". These pairs belong in an ",
            html.B("imperative sequence"),
            " (Inductive-Miner candidate).",
            html.Br(),
            html.Span("• Flexible → "),
            html.Code("(—, ⇒), (—, ⇎), (—, —)",
                      style={"fontFamily": '"STIX Two Math", serif'}),
            ". These pairs are better expressed via ",
            html.B("constraints (Declare)"),
            " — do not force them into an order.",
            html.Br(),
            html.Span("• Co-occurrence without ordering → "),
            html.Code("(—, ⇔)",
                      style={"fontFamily": '"STIX Two Math", serif'}),
            ". Classic ",
            html.B("AND-split / parallel block"),
            " — hybrid models benefit the most.",
        ],
    )

    return html.Details(
        open=False,
        className="pm-details",
        style={"marginTop": "16px", "padding": "10px 14px",
               "border": "1px solid var(--border-default, #E4E7ED)",
               "borderRadius": "8px"},
        children=[
            html.Summary(
                "How to read the matrix? — Activity Relationships explained",
                style={"fontWeight": "600", "cursor": "pointer",
                       "fontSize": "13px"},
            ),
            html.Div(
                style={"marginTop": "10px"},
                children=[
                    html.Div("What the individual codes mean",
                             className="pm-subheading",
                             style={"marginBottom": "6px"}),
                    html.Div(
                        "Each cell is a pair ",
                        className="pm-info",
                        style={"fontSize": "12px", "marginBottom": "6px"},
                    ),
                    html.Div([
                        html.Span("(", style={"fontFamily": '"STIX Two Math", serif'}),
                        html.B("temporal"),
                        html.Span(", ", style={"fontFamily": '"STIX Two Math", serif'}),
                        html.B("existential"),
                        html.Span(")", style={"fontFamily": '"STIX Two Math", serif'}),
                        html.Span(' — i.e. "in what order?" × "'
                                  'must they co-occur?"',
                                  className="pm-info",
                                  style={"fontSize": "12px",
                                         "marginLeft": "6px"}),
                    ], style={"marginBottom": "10px"}),
                    rel_table,
                    html.Div("What implies which structuredness?",
                             className="pm-subheading",
                             style={"marginTop": "16px",
                                    "marginBottom": "6px"}),
                    struct_hints,
                    coupling_hint,
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# Symbol legend.
# --------------------------------------------------------------------------- #

def _legend() -> html.Div:
    items = [
        ("≺d / ≻d", "Direct (forward / backward)"),
        ("≺e / ≻e", "Eventual (forward / backward)"),
        ("⇒ / ⇐",   "Implication (forward / backward)"),
        ("⇔",       "Equivalence"),
        ("⇎",       "Negated Equivalence"),
        ("—",       "No dependency in that dimension"),
    ]
    return html.Div(
        className="pm-info",
        style={"fontSize": "11px", "marginTop": "6px"},
        children=[
            html.Span("Legend: ", style={"fontWeight": "600"}),
            *[
                html.Span(
                    [html.Code(code, style={"marginRight": "4px"}),
                     html.Span(f"{desc}", style={"marginRight": "12px"})],
                )
                for code, desc in items
            ],
        ],
    )


# --------------------------------------------------------------------------- #
# N×N heatmap. Color scheme stripped — single neutral fill, cell text carries
# the actual Andree code.
# --------------------------------------------------------------------------- #

_NEUTRAL_FILL = "#FFFFFF"
_DIAGONAL_FILL = "#E5E7EB"


def _heatmap(result: ArmResult) -> dcc.Graph:
    activities = result["activities"]
    n = len(activities)
    if n == 0:
        return dcc.Graph(figure=go.Figure())

    cell_lookup: dict[tuple[str, str], dict[str, Any]] = {
        (c["from"], c["to"]): c for c in result["cells"]
    }

    z = [[0 for _ in range(n)] for _ in range(n)]
    text = [["" for _ in range(n)] for _ in range(n)]
    hover = [["" for _ in range(n)] for _ in range(n)]

    for i, from_act in enumerate(activities):
        for j, to_act in enumerate(activities):
            if from_act == to_act:
                z[i][j] = 1  # diagonal — distinct neutral grey
                text[i][j] = "·"
                hover[i][j] = f"<b>{from_act}</b> (self)"
                continue
            cell = cell_lookup.get((from_act, to_act))
            if cell is None:
                text[i][j] = ""
                hover[i][j] = f"{from_act} → {to_act}: (missing)"
                continue
            t_type = cell.get("temporal_type")
            t_dir = cell.get("temporal_direction")
            e_type = cell.get("existential_type")
            e_dir = cell.get("existential_direction")
            z[i][j] = 0
            text[i][j] = cell.get("code", "")
            hover[i][j] = (
                f"<b>{from_act} → {to_act}</b><br>"
                f"temporal: {t_type or '—'}"
                f"{' (' + t_dir + ')' if t_dir else ''}<br>"
                f"existential: {e_type or '—'}"
                f"{' (' + e_dir + ')' if e_dir else ''}<br>"
                f"<i>code:</i> {cell.get('code', '')}"
            )

    # Two-step neutral colorscale: 0 = white (off-diagonal cells), 1 = grey
    # (diagonal). No information lives in the color.
    colorscale = [
        [0.0, _NEUTRAL_FILL],
        [0.5, _NEUTRAL_FILL],
        [0.5, _DIAGONAL_FILL],
        [1.0, _DIAGONAL_FILL],
    ]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=activities,
            y=activities,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 14,
                      "family": '"STIX Two Math", "Cambria Math", '
                                '"Apple Symbols", "DejaVu Sans", '
                                '"Segoe UI Symbol", serif'},
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=colorscale,
            zmin=0,
            zmax=1,
            showscale=False,
            xgap=1,
            ygap=1,
        )
    )
    cell_size = max(28, min(56, 600 // max(n, 1)))
    fig.update_layout(
        height=cell_size * n + 80,
        margin=dict(l=80, r=20, t=30, b=80),
        xaxis=dict(side="top", tickangle=0,
                   tickfont=dict(size=11),
                   title="to"),
        yaxis=dict(autorange="reversed",
                   tickfont=dict(size=11),
                   title="from"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return dcc.Graph(
        figure=fig,
        config={"displayModeBar": False, "responsive": True},
        style={"width": "100%"},
    )


# --------------------------------------------------------------------------- #
# Top-level body renderer.
# --------------------------------------------------------------------------- #

def render_arm_body(arm_result: Optional[dict]) -> html.Div:
    """Render the full ARM body for the given (cached) ARM result.

    Returns a placeholder div when ``arm_result`` is missing or carries an
    ``"error"`` key (set by the ARM run callback on subprocess failure).
    """
    if not arm_result:
        return html.Div("Run the classifier to see the ARM heatmap.",
                        className="pm-card-sub")
    if "error" in arm_result:
        return html.Div(
            [html.Div("ARM computation failed.",
                      style={"fontWeight": "600", "marginBottom": "6px"}),
             html.Pre(str(arm_result["error"]),
                      style={"whiteSpace": "pre-wrap", "fontSize": "12px",
                             "padding": "10px", "borderRadius": "6px"})],
            className="pm-alert pm-alert-error",
        )

    activities = arm_result.get("activities") or []
    cells = arm_result.get("cells") or []
    n = len(activities)
    return html.Div([
        html.Div(
            style={"display": "flex", "alignItems": "baseline",
                   "justifyContent": "space-between", "gap": "16px",
                   "flexWrap": "wrap"},
            children=[
                html.Div([
                    html.Span("Activities: ", className="pm-info"),
                    html.Span(f"{n}", style={"fontWeight": "600"}),
                    html.Span(f"  ·  {len(cells)} pairs",
                              className="pm-info",
                              style={"fontSize": "12px", "marginLeft": "8px"}),
                ]),
                _body_classification_badge(
                    arm_result.get("classification") or "—",
                    arm_result.get("matched_rules") or [],
                ),
            ],
        ),
        _explainer(),
        html.Div(style={"marginTop": "12px"}, children=_heatmap(arm_result)),
        html.Div(style={"marginTop": "20px"},
                 children=_percentages_table(arm_result.get("percentages") or {})),
        html.Div(style={"marginTop": "16px"}, children=_legend()),
    ])
