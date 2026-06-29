"""Render a finished result-dict + metric strip for one miner instance."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from dash import dcc, html

from flex_compare.state import MinerInstance
from flex_compare.runner import extract_metrics


# Display labels for the metric strip. Ordered so BQ → IN → SF cluster visually.
_METRIC_DISPLAY = (
    ("replay_fitness", "Replay fitness"),
    ("etc_precision", "ETC precision"),
    ("non_vacuous_satisfaction_rate", "Non-vac. sat. rate"),
    ("vacuity_rate", "Vacuity rate"),
    ("constraint_density", "Constraint density"),
    ("constraint_variability", "Constraint variability"),
    ("process_tree_depth", "Tree depth"),
    ("mean_fan_out", "Mean fan-out"),
    ("extended_cardoso_cfc", "CFC"),
    ("tau_ratio", "τ-ratio"),
    ("flower_detected", "Flower detected"),
    ("soundness_passed", "Sound"),
)


def _fmt(value: object, imported: bool) -> str:
    if value is None:
        return "n/a — imported model" if imported else "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_pill(label: str, value: object, imported: bool) -> html.Div:
    is_unavailable = value is None
    classes = ["fc-metric"]
    if is_unavailable and imported:
        classes.append("fc-metric-imported")
    elif is_unavailable:
        classes.append("fc-metric-missing")
    return html.Div(
        className=" ".join(classes),
        style={
            "display": "inline-flex",
            "flexDirection": "column",
            "padding": "6px 10px",
            "marginRight": "8px",
            "marginBottom": "6px",
            "background": "var(--bg-elevated, #f6f7fa)",
            "borderRadius": "6px",
            "fontSize": "11px",
            "minWidth": "92px",
        },
        children=[
            html.Span(label, style={"color": "var(--text-muted, #666)"}),
            html.Span(_fmt(value, imported), style={"fontWeight": "600"}),
        ],
    )


def _resolve_artifact(result: dict, *keys) -> Optional[str]:
    """First-present check for nested artifact paths."""
    for key in keys:
        if isinstance(key, str):
            value = result.get(key)
        else:
            cursor: object = result
            for sub in key:
                if not isinstance(cursor, dict):
                    cursor = None
                    break
                cursor = cursor.get(sub)
            value = cursor
        if isinstance(value, str) and value and Path(value).is_file():
            return value
    return None


_DECLARE_HIDE_OVERRIDE = (
    "<script>(function(){"
    "function hideCtrls(){try{"
    "var btns=document.querySelectorAll('[data-action]');"
    "var parents=new Set();"
    "btns.forEach(function(b){"
    "b.style.setProperty('display','none','important');"
    "if(b.parentElement)parents.add(b.parentElement);"
    "});"
    "var root=document.getElementById('declareContainer')||document.body;"
    "parents.forEach(function(p){"
    "if(p===root)return;"
    "if(p.querySelector('svg,canvas,g[class*=\"node\"],g[class*=\"link\"]'))return;"
    "p.style.setProperty('display','none','important');"
    "});"
    "document.querySelectorAll("
    "'.editorContainer,.editor-container,"
    "[class*=\"editor\"][class*=\"Container\"],"
    ".constraintList,.sidebar,.rightPanel,.right-panel,"
    "input[type=\"file\"],label.file-input'"
    ").forEach(function(el){"
    "if(el.querySelector('svg,canvas'))return;"
    "el.style.setProperty('display','none','important');"
    "});"
    "}catch(e){}}"
    "[400,1000,2200,4500].forEach(function(d){setTimeout(hideCtrls,d);});"
    "})();</script></body>"
)
_DECLARE_SHOW_OVERRIDE = (
    "<script>(function(){"
    "function showCtrls(){"
    "document.querySelectorAll("
    "'[data-action],.editorContainer,.editor-container,"
    ".constraintList,.sidebar,.rightPanel,.right-panel,"
    "input[type=\"file\"],label.file-input'"
    ").forEach(function(el){el.style.removeProperty('display');});"
    "}"
    "window.__declareFullscreen=true;"
    "[400,1000,2200,4500].forEach(function(d){setTimeout(showCtrls,d);});"
    "})();</script></body>"
)


# Each spec: (label, key-lookups, kind). The first key that resolves to an
# existing file wins. Order here is the stacking order in the rendered view.
_ARTIFACT_SPECS = (
    ("Petri net",      ("petri_net_path",),                                 "png"),
    ("Process tree",   ("process_tree_path",),                              "png"),
    ("BPMN",           ("bpmn_path",),                                      "png"),
    ("Hybrid model",   (("run_data", "hybrid_rendered_png_path"),),         "png"),
    ("PNwA model",     (("run_data", "pnwa_rendered_png_path"),),           "png"),
    ("Declare model",  ("declare_visualization_path",),                     "html"),
)


def _render_png_artifact(path: str, *, large: bool) -> html.Img:
    import base64
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    if large:
        # Per artifact: cap height to roughly half the viewport so multiple
        # artifacts (e.g. IM: petri + tree + bpmn) all fit stacked, while
        # individual ones can still grow nicely. Card overflow scrolls.
        style = {"display": "block",
                 "maxWidth": "calc(92vw - 32px)",
                 "maxHeight": "70vh",
                 "width": "auto", "height": "auto",
                 "objectFit": "contain", "borderRadius": "4px"}
    else:
        style = {"maxWidth": "100%", "borderRadius": "4px"}
    return html.Img(src=f"data:image/png;base64,{data}", style=style)


def _render_html_artifact(path: str, *, large: bool) -> html.Iframe:
    src_doc = Path(path).read_text(encoding="utf-8")
    override = _DECLARE_SHOW_OVERRIDE if large else _DECLARE_HIDE_OVERRIDE
    if "</body>" in src_doc:
        src_doc = src_doc.replace("</body>", override, 1)
    else:
        src_doc = src_doc + override
    if large:
        iframe_style = {"display": "block",
                        "width": "min(88vw, 1400px)", "height": "70vh",
                        "border": "1px solid var(--border-default,#ddd)",
                        "borderRadius": "4px", "background": "white"}
    else:
        iframe_style = {"width": "100%", "height": "320px",
                        "border": "1px solid var(--border-default,#ddd)",
                        "borderRadius": "4px", "background": "white"}
    return html.Iframe(srcDoc=src_doc, style=iframe_style)


def _render_one_artifact(label: str, path: str, kind: str, *,
                         large: bool) -> html.Div:
    label_div = html.Div(
        label,
        style={"fontSize": "10px", "fontWeight": "600",
               "letterSpacing": "0.04em", "textTransform": "uppercase",
               "color": "var(--text-muted, #888)",
               "marginBottom": "4px"},
    )
    body = _render_png_artifact(path, large=large) if kind == "png" \
        else _render_html_artifact(path, large=large)
    return html.Div(
        style={"display": "flex", "flexDirection": "column"},
        children=[label_div, body],
    )


def _render_model_view(result: dict, *, large: bool = False) -> html.Div:
    """Render every available model artifact for the miner.

    Each miner can produce more than one rendering (IM: Petri net + process
    tree + BPMN; Fusion: hybrid net + PNwA). We enumerate the spec list and
    stack each available artifact under a small label. ``large=True`` is the
    fullscreen-modal version: bigger sizes per artifact, all visible at once.
    """
    sections: list[html.Div] = []
    for label, keys, kind in _ARTIFACT_SPECS:
        path = _resolve_artifact(result, *keys)
        if not path:
            continue
        sections.append(_render_one_artifact(label, path, kind, large=large))

    if not sections:
        return html.Div("(no rendered artifact available)",
                        style={"fontSize": "12px",
                               "color": "var(--text-muted, #666)"})
    return html.Div(
        style={"display": "flex", "flexDirection": "column", "gap": "14px"},
        children=sections,
    )


def _zoom_modal(instance_id: str, result: dict) -> html.Div:
    """Per-instance modal that pops up the model artifact in a large overlay.

    Backdrop click closes; clicks on the card itself do not bubble to the
    backdrop (the card sits on a higher z-index, the backdrop is a sibling
    that fills the viewport and carries the close ``n_clicks``).
    """
    return html.Div(
        id={"type": "fc-zoom-modal", "instance": instance_id},
        style={"display": "none"},  # toggled by zoom_modal_callbacks
        children=[
            # Backdrop = the close target. Sits behind the card; clicking
            # anywhere outside the card increments n_clicks.
            html.Div(
                id={"type": "fc-zoom-close", "instance": instance_id},
                n_clicks=0,
                style={"position": "fixed", "top": 0, "left": 0,
                       "right": 0, "bottom": 0,
                       "background": "rgba(0,0,0,0.55)",
                       "cursor": "zoom-out", "zIndex": 300},
            ),
            # Card sits above the backdrop; clicks inside don't reach it.
            # ``display: inline-block`` lets the card shrink to its child's
            # natural size — small Petri nets get a small popup. Caps keep
            # very large images within the viewport.
            html.Div(
                className="pm-card pm-card-elevated",
                style={"position": "fixed", "top": "50%", "left": "50%",
                       "transform": "translate(-50%, -50%)",
                       "maxWidth": "92vw", "maxHeight": "90vh",
                       "overflow": "auto",
                       "padding": "16px",
                       "display": "inline-block",
                       "boxShadow": "var(--shadow-2)", "zIndex": 301},
                children=[
                    _render_model_view(result, large=True),
                ],
            ),
        ],
    )


def render_result_view(instance: MinerInstance, result: dict, cache_hit: bool) -> html.Div:
    metrics = extract_metrics(instance, result)
    imported = bool(metrics.pop("_imported", False))
    pills = [
        _metric_pill(label, metrics.get(key), imported)
        for key, label in _METRIC_DISPLAY
        if key in metrics
    ]
    # Wrap the model in a relative container + transparent click-overlay so
    # a click anywhere on the model (image OR declare-js iframe) opens the
    # zoom modal. The overlay sits on top of the iframe whose own clicks
    # would otherwise not escape its document.
    model_wrapper = html.Div(
        style={"position": "relative"},
        children=[
            _render_model_view(result),
            html.Div(
                id={"type": "fc-zoom-open", "instance": instance.id},
                n_clicks=0,
                style={"position": "absolute", "top": 0, "left": 0,
                       "right": 0, "bottom": 0,
                       "cursor": "zoom-in"},
                title="Click to enlarge",
            ),
        ],
    )
    return html.Div(children=[
        html.Div(
            style={"display": "flex", "justifyContent": "space-between",
                   "alignItems": "center", "marginBottom": "8px"},
            children=[
                html.Div("Model", style={"fontWeight": "600", "fontSize": "12px",
                                          "textTransform": "uppercase",
                                          "color": "var(--text-muted, #666)"}),
                html.Div(
                    "from cache" if cache_hit else "fresh run",
                    style={"fontSize": "11px",
                           "color": "var(--text-muted, #888)",
                           "fontStyle": "italic"},
                ),
            ],
        ),
        model_wrapper,
        html.Div(style={"marginTop": "12px"}, children=pills),
        _zoom_modal(instance.id, result),
    ])


def render_error_view(error_summary: str, exec_log_path: Optional[Path],
                      command: Optional[list]) -> html.Div:
    children: list = [
        html.Div("Run failed", style={
            "fontWeight": "600", "color": "var(--color-error,#c00)",
            "marginBottom": "6px", "fontSize": "13px",
        }),
        html.Div(error_summary, style={"fontSize": "12px", "marginBottom": "8px"}),
    ]
    if command:
        children.append(html.Details([
            html.Summary("Command", style={"fontSize": "12px", "cursor": "pointer"}),
            html.Pre(" ".join(command), style={"fontSize": "11px", "marginTop": "4px"}),
        ]))
    if exec_log_path and Path(exec_log_path).is_file():
        try:
            text = Path(exec_log_path).read_text(encoding="utf-8")
        except OSError:
            text = "(could not read _exec.log)"
        # Last 200 lines.
        lines = text.splitlines()
        snippet = "\n".join(lines[-200:])
        children.append(html.Details([
            html.Summary("Last 200 lines of _exec.log",
                         style={"fontSize": "12px", "cursor": "pointer"}),
            html.Pre(snippet, style={"fontSize": "10px", "maxHeight": "260px",
                                     "overflow": "auto", "marginTop": "4px",
                                     "background": "var(--bg-elevated,#f6f7fa)",
                                     "padding": "8px"}),
        ]))
    return html.Div(children=children)
