"""Tab 3 — Phase-2 questionnaire scoring.

Single-focus survey wizard inspired by ``miners/qualitative_eval/survey_app``:

* **Start** — pick exactly one configured miner and one structuredness class.
* **Phase A** — rate the *selected* miner against each Phase-A item (theory).
* **Phase A done** — score donut + transitions.
* **Phase B** — for each of three class logs, rate the discovered model.
* **Phase B done** — score donut + transition to overview.
* **Overview** — clean Miner × Class matrix with mini donuts for each cell.

The body is re-rendered by ``ui.callbacks.fragebogen_callbacks.render_body``;
this module only declares the layout and view functions. Persistence layers
(Phase-A answers, per-cell scores) are unchanged — only the rendering shifts
to a calmer single-focus layout.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Optional

from dash import dcc, html

from flex_compare.fragebogen import annotations as fb_annotations
from flex_compare.fragebogen import combine as fb_combine
from flex_compare.fragebogen import items as fb_items
from flex_compare.fragebogen import phase_a_answers as fb_phase_a_answers
from flex_compare.fragebogen import phase_b as fb_phase_b
from flex_compare.fragebogen import phase_e as fb_phase_e
from flex_compare.fragebogen import phase_t as fb_phase_t
from flex_compare.fragebogen import scores as fb_scores
from flex_compare.fragebogen.items import (
    items_for_class,
    items_phase_b_for_class,
    meta_for_class,
)
from flex_compare.fragebogen.log_discovery import logs_for_class
from flex_compare.internal.shared.cache import result_cache
from flex_compare.internal.shared.paths import PROJECT_ROOT
from flex_compare.internal.shared.registry import miner_registry
from flex_compare.runner import (
    _resolve_schema_for,
    _type_id,
    extract_metrics,
    slot_id,
)
from flex_compare.state import FlexState, MinerInstance
from flex_compare.ui import ids
from flex_compare.ui.components.config_form import render_config_form
from flex_compare.ui.components.result_view import _render_model_view


logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "with-case-ids"

_CLASS_LABEL = {
    "structured": "Structured",
    "semi": "Semi-structured",
    "loosely": "Loosely structured",
}

_CLASS_PILL_CLASS = {
    "structured": "fc-survey-badge-cls-structured",
    "semi": "fc-survey-badge-cls-semi",
    "loosely": "fc-survey-badge-cls-loosely",
}

_PARADIGM_LABEL = {
    "imperativ": "Imperative",
    "deklarativ": "Declarative",
    "hybrid": "Hybrid",
}


# ── Layout shell ────────────────────────────────────────────────────────────

def render_layout(state: FlexState) -> html.Div:
    return html.Div(
        children=[
            dcc.Store(id=ids.FB_SESSION_STORE,
                      data={"miner_id": None, "class": None,
                            "view": "overview", "nonce": 0}),
            dcc.Store(id=ids.FB_PHASE_A_NAV_STORE,
                      data={"item_idx": 0, "nonce": 0}),
            dcc.Store(id=ids.FB_PHASE_B_NAV_STORE,
                      data={"log_idx": 0, "nonce": 0}),
            html.Div(id=ids.FB_PHASE_A_SAVE_FEEDBACK,
                     style={"position": "fixed", "right": "20px",
                            "bottom": "16px", "fontSize": "11px",
                            "color": "var(--text-muted, #888)",
                            "pointerEvents": "none"}),
            html.Div(id=ids.FB_PHASE_B_SAVE_FEEDBACK,
                     style={"position": "fixed", "right": "20px",
                            "bottom": "32px", "fontSize": "11px",
                            "color": "var(--text-muted, #888)",
                            "pointerEvents": "none"}),
            html.Div(id=ids.FB_BODY,
                     children=render_body(
                         {"miner_id": None, "class": None,
                          "view": "overview", "nonce": 0}, state)),
        ],
    )


# ── Dispatch ────────────────────────────────────────────────────────────────

def render_body(session: Optional[dict], state: FlexState,
                pa_nav: Optional[dict] = None,
                pb_nav: Optional[dict] = None) -> html.Div:
    session = session or {}
    # Tab 3 is driven by the miner registry, not by Tab-2 instances, so it works
    # even before any miner is configured in Tab 2.
    if not miner_registry.miner_specs():
        return _shell([_empty_card(
            "No miners registered",
            "The miner registry is empty — Phase 2 has nothing to score.")])

    # Overview is the default landing page for Tab 3 when no evaluation is
    # active; the start picker is reached explicitly via "+ New rating".
    view = session.get("view") or "overview"
    miner_id = session.get("miner_id")
    cls = session.get("class")

    if view == "overview":
        return _shell([_topbar("Overview", "Miner × class"),
                       _overview_view(state, session.get("ov_open"))])

    if view == "start":
        return _shell([_topbar("Phase 2", "Start"),
                       _start_view(state)])

    # Wizard/result views need a (miner, class) pair; without one, fall back to
    # the start picker rather than erroring.
    if not miner_id or not cls:
        return _shell([_topbar("Phase 2", "Start"),
                       _start_view(state)])

    inst = _resolve_miner(state, miner_id)
    if inst is None:
        return _shell([_topbar("Phase 2", "Start"),
                       _start_view(state,
                                    warn=f'Miner "{miner_id}" not found in the registry.')])
    if cls not in _CLASS_LABEL:
        return _shell([_topbar("Phase 2", "Start"),
                       _start_view(state, warn=f'Unknown class "{cls}".')])

    # All three wizard views share the wide shell so the page width — and with
    # it the topbar/tab/nav buttons — stays put when switching between
    # Theoretical, Empirical and Result.
    if view == "phase_a":
        return _shell(_phase_a_survey_view(inst, cls, pa_nav or {}), wide=True)
    if view == "phase_b":
        inst = _with_config_override(inst, session.get("pb_cfg"))
        return _shell(_phase_b_survey_view(inst, cls, pb_nav or {}),
                      wide=True)
    if view in ("result", "phase_a_done", "phase_b_done"):
        return _shell(_result_view(inst, cls, state), wide=True)

    # Unknown view with a valid selection → Overview (safe default; never
    # silently drop into the Phase-A wizard).
    return _shell([_topbar("Overview", "Miner × class"),
                   _overview_view(state, session.get("ov_open"))])


# ── Common chrome (topbar / shell / empty) ─────────────────────────────────

def _shell(children: list, *, wide: bool = False) -> html.Div:
    cls = "fc-survey-shell" + (" fc-survey-shell-wide" if wide else "")
    return html.Div(className=cls, children=children)


def _with_config_override(inst: MinerInstance,
                          override: Optional[dict]) -> MinerInstance:
    """Apply a session-scoped Phase-B config override onto ``inst``.

    The Phase-B miner is frequently an *ephemeral* registry instance (see
    ``_ephemeral_instance_for_spec``) that is absent from ``state.instances``,
    so edits cannot round-trip through the shared ``_persist_config`` callback.
    Instead the edits live in the session store and are merged here before the
    cache slot / run lookup is derived.
    """
    if not override:
        return inst
    merged = {**(inst.config or {}), **override}
    if merged == inst.config:
        return inst
    return dataclasses.replace(inst, config=merged)


def _topbar(title: str, sub: str, *,
             progress: Optional[tuple[int, int]] = None,
             progress_label: str = "",
             actions: Optional[list] = None) -> html.Div:
    children: list = [
        html.Div(className="fc-survey-topbar-brand", children=[
            html.Div(title, className="fc-survey-topbar-title"),
            html.Div(sub, className="fc-survey-topbar-sub"),
        ]),
    ]
    if progress is not None:
        cur, total = progress
        pct = round(cur / max(1, total) * 100)
        children.append(html.Div(className="fc-survey-progress", children=[
            html.Div(progress_label or f"{cur}/{total}",
                     className="fc-survey-progress-label"),
            html.Div(className="fc-survey-progress-track", children=[
                html.Div(className="fc-survey-progress-fill",
                         style={"width": f"{pct}%"}),
            ]),
        ]))
    # Always keep a flexible spacer between the middle and the actions so the
    # action buttons sit at the far right in every view (with or without a
    # progress bar) — keeps them from shifting when switching tabs.
    children.append(html.Div(className="fc-survey-topbar-spacer"))
    if actions:
        children.append(html.Div(actions, style={"display": "flex",
                                                   "gap": "8px"}))
    return html.Div(className="fc-survey-topbar", children=children)


def _nav_strip(active: str, has_selection: bool) -> html.Div:
    """Persistent navigation rendered on *every* Tab-3 view.

    Left segment (Overview · New rating) is always live; the right segment
    (Theoretical · Empirical · Result) only makes sense once a (miner, class)
    pair is selected, so those tabs are disabled on the Overview / Start views.
    Button ids reuse the existing callbacks (``open_overview``,
    ``close_overview``, ``switch_phase_tab``), so no new wiring is needed.
    """
    def _tab(label: str, btn_id: str, key: str, *,
             disabled: bool = False) -> html.Button:
        cls = "fc-survey-tab" + (" is-active" if active == key else "")
        return html.Button(label, id=btn_id, n_clicks=0, className=cls,
                           disabled=disabled)

    return html.Div(className="fc-survey-tabs", children=[
        _tab("Overview", ids.FB_OVERVIEW_BTN, "overview"),
        _tab("New rating", ids.FB_OVERVIEW_BACK_BTN, "start"),
        html.Span(className="fc-survey-nav-divider"),
        _tab("Theoretical", ids.FB_TAB_PA_BTN, "phase_a",
             disabled=not has_selection),
        _tab("Empirical", ids.FB_TAB_PB_BTN, "phase_b",
             disabled=not has_selection),
        _tab("Result", ids.FB_TAB_RESULT_BTN, "result",
             disabled=not has_selection),
    ])


def _empty_card(title: str, lede: str = "") -> html.Div:
    return html.Div(className="fc-survey-card", children=[
        html.Div(className="fc-survey-card-head", children=[
            html.Div("Notice", className="fc-survey-card-eyebrow"),
            html.Div(title, className="fc-survey-card-title"),
            (html.Div(lede, className="fc-survey-card-lede")
             if lede else html.Div()),
        ]),
    ])


def _cls_badge(cls: str) -> html.Span:
    css = _CLASS_PILL_CLASS.get(cls, "")
    return html.Span(_CLASS_LABEL.get(cls, cls),
                      className=f"fc-survey-badge {css}")


# ── Start view ──────────────────────────────────────────────────────────────

def _start_view(state: FlexState, warn: str = "") -> html.Div:
    class_options = [
        {"label": _tile_label(v, ""), "value": k}
        for k, v in _CLASS_LABEL.items()
    ]

    warn_block = (html.Div(warn, style={
        "padding": "10px 12px", "marginBottom": "16px",
        "background": "rgba(220, 80, 60, 0.08)",
        "border": "1px solid rgba(220, 80, 60, 0.5)",
        "borderRadius": "8px", "fontSize": "12px",
        "color": "var(--color-error, #c00)"}) if warn else html.Div())

    specs = miner_registry.miner_specs()
    miner_options = [
        {"label": _spec_dropdown_label(spec), "value": spec.id}
        for spec in specs
    ]
    default_miner = specs[0].id if specs else None

    return html.Div([
        _nav_strip("start", has_selection=False),
        warn_block,
        html.Div(className="fc-survey-card", children=[
            html.Div(className="fc-survey-card-head", children=[
                html.Div("Start", className="fc-survey-card-eyebrow"),
                html.Div("Pick a miner and a class",
                         className="fc-survey-card-title"),
                html.Div(
                    "Each session scores exactly one miner against one "
                    "structuredness class. Theoretical Evaluation delivers the "
                    "a-priori score, Empirical Evaluation the empirical one, "
                    "and at the end the overview of every miner × class "
                    "combination.",
                    className="fc-survey-card-lede"),
            ]),
            html.Div(className="fc-survey-card-body", children=[
                html.Div("1 · Miner",
                         className="fc-survey-section-label"),
                dcc.Dropdown(
                    id=ids.FB_MINER_SELECT,
                    options=miner_options,
                    value=default_miner,
                    clearable=False,
                    className="fc-survey-dropdown",
                    style={"fontSize": "13px"},
                ),

                html.Div("2 · Class",
                         className="fc-survey-section-label",
                         style={"marginTop": "20px"}),
                dcc.RadioItems(
                    id=ids.FB_CLASS_SELECT,
                    options=class_options,
                    value="structured",
                    className="fc-survey-tiles",
                    labelClassName="fc-survey-tile-label",
                ),
            ]),
            html.Div(className="fc-survey-card-footer", children=[
                html.Div(),
                html.Button("▶ Start Theoretical Evaluation",
                            id=ids.FB_START_BTN, n_clicks=0,
                            className="fc-survey-btn fc-survey-btn-primary"),
            ]),
        ]),
    ])


def _tile_label(title: str, sub: str):
    """Two-line label rendered inside the radio-tile."""
    return html.Span([
        html.Span(title, className="fc-survey-tile-title"),
        (html.Span(sub, className="fc-survey-tile-sub")
         if sub else html.Span()),
    ], style={"display": "flex", "flexDirection": "column", "gap": "2px"})


def _likert_tiles(role: str, scale_rows: list[dict],
                  current_score: Optional[int], instance: str,
                  *, nz_selected: bool = False,
                  **extra) -> html.Div:
    """Clickable answer tiles (one per scale row) plus a "nicht beantwortbar"
    tile.

    Replaces ``dcc.RadioItems`` so a click saves immediately and a second click
    on the selected tile deselects it (handled in the option callbacks). The
    tile whose ``score`` equals ``current_score`` carries ``is-selected``.

    The trailing "nicht beantwortbar" tile (score sentinel ``"nz"``) is offered
    on every item. Picking it stores ``n.z.`` = 0 markiert: the item counts as 0
    points and stays in the denominator (Doc §5), the same point-wise as the
    lowest rating but tracked separately so the rater can flag an item they
    cannot assess.
    """
    tiles = []
    for row in scale_rows:
        score = row.get("score")
        selected = (not nz_selected
                    and current_score is not None and score == current_score)
        tiles.append(html.Button(
            id=ids.fc_id(role, instance, score=score, **extra),
            n_clicks=0,
            className="fc-survey-likert-cell"
                      + (" is-selected" if selected else ""),
            children=[
                html.Span(str(score), className="fc-survey-likert-cell-num"),
                html.Span(row.get("label", ""),
                          className="fc-survey-likert-cell-label"),
            ],
        ))
    tiles.append(html.Button(
        id=ids.fc_id(role, instance, score="nz", **extra),
        n_clicks=0,
        className="fc-survey-likert-cell fc-survey-likert-cell-nz"
                  + (" is-selected" if nz_selected else ""),
        children=[
            html.Span("n/a", className="fc-survey-likert-cell-num"),
            html.Span("Not answerable — counts as 0 points",
                      className="fc-survey-likert-cell-label"),
        ],
    ))
    return html.Div(tiles, className="fc-survey-likert")


# ── Phase A wizard (SINGLE miner) ──────────────────────────────────────────

def _phase_a_survey_view(inst: MinerInstance, cls: str,
                          nav: dict) -> html.Div:
    items = items_for_class(cls)
    selected_miner = _miner_id_of(inst)

    if not items:
        return [_topbar("Theoretical Evaluation", _CLASS_LABEL.get(cls, cls)),
                _empty_card(
                    f"Theoretical Evaluation for {_CLASS_LABEL.get(cls, cls)} "
                    "is not configured yet.")]

    item_idx = max(0, min(int((nav or {}).get("item_idx") or 0),
                            len(items) - 1))
    item = items[item_idx]
    all_answers = fb_phase_a_answers.load_all_answers(cls)
    answered = sum(1 for (miner_id, _item_id) in all_answers
                   if miner_id == selected_miner)

    topbar = _topbar(
        "Theoretical Evaluation",
        f"{inst.label or inst.id} · {_CLASS_LABEL.get(cls, cls)}",
        # Progress bar tracks answered items (monotonic), not the cursor —
        # navigating prev/next must not make the bar jump back and forth.
        progress=(answered, len(items)),
        progress_label=f"Item {item_idx + 1}/{len(items)} · "
                       f"{answered}/{len(items)} answered",
        actions=[
            html.Button("← Change selection",
                        id=ids.FB_PHASE_A_EXIT_BTN,
                        n_clicks=0,
                        className="fc-survey-btn fc-survey-btn-ghost"),
        ],
    )

    tabs = _nav_strip("phase_a", has_selection=True)
    toc = _phase_a_toc(items, item_idx, cls, selected_miner)
    body = _phase_a_item_card(item, cls, selected_miner, inst)
    nav_bar = _phase_a_nav_bar(item_idx, len(items))

    return [topbar, tabs, toc, body, nav_bar]


def _phase_a_toc(items: list[dict], item_idx: int, cls: str,
                  selected_miner: Optional[str]) -> html.Div:
    answers = fb_phase_a_answers.load_all_answers(cls)
    chips = []
    for i, item in enumerate(items):
        has_answer = (selected_miner is not None and
                       (selected_miner, item["id"]) in answers)
        status = "is-done" if has_answer else ""
        if i == item_idx:
            status += " is-current"
        chips.append(html.Button(
            id=ids.fc_id("fb-pa-toc", item["id"]),
            n_clicks=0,
            className=f"fc-survey-toc-cell {status}".strip(),
            children=item["id"],
        ))
    return html.Div(chips, className="fc-survey-toc")


def _phase_a_item_card(item: dict, cls: str,
                        selected_miner: Optional[str],
                        inst: MinerInstance) -> html.Div:
    if selected_miner is None:
        body = html.Div([
            html.Div("n/a — inline miner without YAML profile.",
                     style={"fontSize": "13px",
                            "color": "var(--text-muted, #666)"}),
        ])
        return html.Div(className="fc-survey-card", children=[
            html.Div(className="fc-survey-card-body", children=[body])])

    persisted = fb_phase_a_answers.load_answer(cls, selected_miner, item["id"])
    seed = (item.get("phase_a") or {}).get(selected_miner) or {}
    if persisted is not None:
        current_score = persisted.get("score")
        current_note = persisted.get("note") or ""
        nz_selected = persisted.get("value") == "nz"
        source_label = "✎ manual"
    else:
        current_score = seed.get("score")
        current_note = seed.get("note") or ""
        nz_selected = False
        source_label = ("Seed [AI DRAFT]" if seed else "Not answered yet")

    scale_rows = list(item.get("scale", []))

    measure = item.get("measure")
    doku_hint = item.get("doku_hint")
    head_children = [
        html.Div([
            html.Span("Theoretical · Item",
                      className="fc-survey-card-eyebrow"),
            _cls_badge(cls),
        ], style={"display": "flex", "gap": "10px",
                  "alignItems": "center"}),
        html.Div(className="fc-survey-item-head",
                  style={"marginTop": "6px"},
                  children=[
                      html.Span(item["id"],
                                 className="fc-survey-item-id"),
                      html.Span(item.get("title", ""),
                                 className="fc-survey-item-title"),
                      html.Span(item.get("axis", ""),
                                 className="fc-survey-item-axis"),
                  ]),
        html.Div(item.get("question", ""),
                  className="fc-survey-item-question"),
    ]
    if measure:
        head_children.append(
            html.Div([html.Span("Measures", className="fc-survey-measure-key"),
                      html.Span(measure, className="fc-survey-measure-val")],
                     className="fc-survey-measure"))
    if doku_hint:
        head_children.append(
            html.Div([html.Span("Where to look", className="fc-survey-hint-key"),
                      html.Span(doku_hint, className="fc-survey-hint-val")],
                     className="fc-survey-hint"))
    header = html.Div(className="fc-survey-card-head", children=head_children)

    body = html.Div(className="fc-survey-card-body", children=[
        _likert_tiles("fb-pa-opt", scale_rows, current_score,
                      selected_miner, nz_selected=nz_selected,
                      item=item["id"]),
    ])

    return html.Div(className="fc-survey-card", children=[header, body])


def _phase_a_nav_bar(item_idx: int, n_items: int) -> html.Div:
    on_last = item_idx >= n_items - 1
    return html.Div(className="fc-survey-card", children=[
        html.Div(className="fc-survey-card-footer",
                  style={"borderTop": "none"},
                  children=[
                      html.Button("← Previous",
                                  id=ids.FB_PHASE_A_PREV_BTN, n_clicks=0,
                                  disabled=item_idx <= 0,
                                  className="fc-survey-btn fc-survey-btn-ghost"),
                      html.Div(f"Item {item_idx + 1} / {n_items}",
                                style={"fontSize": "11px",
                                       "color": "var(--text-muted)",
                                       "fontWeight": 600,
                                       "letterSpacing": "0.06em",
                                       "textTransform": "uppercase"}),
                      html.Div(style={"display": "flex", "gap": "8px"},
                                children=[
                                    html.Button("Next →" if not on_last
                                                 else "Finish ▸",
                                                 id=(ids.FB_PHASE_A_NEXT_BTN
                                                      if not on_last
                                                      else ids.FB_PHASE_A_FINISH_BTN),
                                                 n_clicks=0,
                                                 className="fc-survey-btn "
                                                            "fc-survey-btn-primary"),
                                ]),
                  ]),
    ])


# ── Result (combined Phase A + Phase B summary) ────────────────────────────

_AXIS_LABEL = {
    "BQ": "Behavioral quality (BQ)",
    "IN": "Internal structure (IN)",
    "SF": "Structural fit (SF)",
}


def _band(fit: Optional[float]) -> Optional[str]:
    """Map a fit % to a descriptive band — same thresholds as ``_score_donut``."""
    if fit is None:
        return None
    if fit >= 75:
        return "a strong fit"
    if fit >= 50:
        return "a moderate fit"
    return "a weak fit"


def _suitability_sentence(cls: str, t_res: dict, e_res: dict) -> str:
    """Hedged, within-class suitability reading.

    Reports the Theoretical and Empirical legs separately, never combines them
    into a verdict, and never ranks across miners (RC3). Marks an incomplete
    reading as provisional. The Theoretical leg is reported as a fraction
    (``#Yes / #items``), the Empirical leg as a percentage band.
    """
    cls_label = _CLASS_LABEL.get(cls, cls)
    fit_e = e_res.get("fit")
    band_e = _band(fit_e)

    t_answered = t_res.get("max", 0)
    t_points = t_res.get("points", 0)
    t_total = t_res.get("max_full") or 3
    leg_t = (f"the theoretical evaluation reaches {t_points} of {t_total} "
             "criteria"
             if t_answered else "the theoretical evaluation has not been "
             "scored yet")
    leg_e = (f"the empirical evaluation suggests {band_e} ({fit_e:.0f}%)"
             if band_e else "the empirical evaluation has not been scored yet")

    sentence = f"For the {cls_label} class, {leg_t}, while {leg_e}."
    incomplete = ((t_answered and not t_res.get("complete"))
                  or (fit_e is not None and not e_res.get("complete")))
    if incomplete:
        sentence += " Scoring is still incomplete, so this reading is provisional."
    sentence += (" These figures describe this miner on this class only and are "
                 "not a cross-miner ranking.")
    return sentence


def _axis_groups_t(cls: str, per_item: dict) -> list[tuple[str, list[dict]]]:
    """Group Phase-T items by axis, in YAML order, with per-item status rows."""
    label = {"ja": "Yes", "nein": "No", "nz": "n.z."}
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for item in fb_items.phase_t_items_for_class(cls):
        axis = item.get("axis") or "—"
        cell = per_item.get(item["id"]) or {}
        value = cell.get("value")
        groups.setdefault(axis, [])
        if axis not in order:
            order.append(axis)
        groups[axis].append({
            "id": item["id"],
            "title": item.get("title", ""),
            "right": label.get(value, "—"),
            "scored": value is not None,
        })
    return [(ax, groups[ax]) for ax in order]


def _axis_groups_e(cls: str, per_cell: dict,
                   n_logs: int) -> list[tuple[str, list[dict]]]:
    """Group Phase-E items by axis; each row aggregates its cells across logs."""
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for item in fb_items.phase_e_items_for_class(cls):
        axis = item.get("axis") or "—"
        cells = [c for c in per_cell.values() if c.get("item") == item["id"]]
        answered = sum(1 for c in cells if c.get("value") is not None)
        points = sum(c.get("points", 0) for c in cells
                     if c.get("value") is not None)
        # Mean score this question earned across the logs it was rated on (out
        # of 2); this is the per-question contribution the Empirical Fit sums.
        avg = points / answered if answered else None
        right = (f"{answered}/{n_logs} logs · {points} pts · Ø {avg:.1f}/2"
                 if answered else "—")
        groups.setdefault(axis, [])
        if axis not in order:
            order.append(axis)
        groups[axis].append({
            "id": item["id"],
            "title": item.get("title", ""),
            "right": right,
            "scored": answered > 0,
        })
    return [(ax, groups[ax]) for ax in order]


def _breakdown_column(heading: str,
                      axis_groups: list[tuple[str, list[dict]]]) -> html.Div:
    sections: list = []
    for axis, rows in axis_groups:
        answered = sum(1 for r in rows if r["scored"])
        sections.append(html.Div(className="fc-survey-cat-axis", children=[
            html.Div(className="fc-survey-cat-axis-head", children=[
                html.Span(_AXIS_LABEL.get(axis, axis)),
                html.Span(f"{answered}/{len(rows)} scored",
                          className="fc-survey-cat-axis-count"),
            ]),
            *[
                html.Div(
                    className="fc-survey-cat-row"
                              + ("" if r["scored"] else " is-empty"),
                    children=[
                        html.Span(r["id"], className="fc-survey-cat-id"),
                        html.Span(r["title"], className="fc-survey-cat-title"),
                        html.Span(r["right"], className="fc-survey-cat-val"),
                    ],
                )
                for r in rows
            ],
        ]))
    return html.Div(className="fc-survey-2col-pane",
                    **{"data-fc-scroll-key": f"result-{heading}"},
                    children=[
        html.Div(heading, className="fc-survey-section-label"),
        *sections,
    ])


def _result_view(inst: MinerInstance, cls: str,
                  state: FlexState) -> html.Div:
    selected_miner = _miner_id_of(inst)

    topbar = _topbar(
        "Result",
        f"{inst.label or inst.id} · {_CLASS_LABEL.get(cls, cls)}",
        actions=[
            html.Button("← Change selection",
                        id=ids.FB_PHASE_B_EXIT_BTN,
                        n_clicks=0,
                        className="fc-survey-btn fc-survey-btn-ghost"),
        ],
    )

    if selected_miner is None:
        body = _empty_card(
            "No fit breakdown",
            "This inline miner has no YAML profile, so there is nothing to "
            "score on the T+E scheme.")
        return [topbar, _nav_strip("result", has_selection=True), body]

    t_res = fb_phase_t.phase_t_fit_with_answers(selected_miner, cls)
    e_res = fb_phase_e.phase_e_fit(selected_miner, cls, state=state)

    fit_e = e_res.get("fit")
    t_answered = t_res.get("n_ja", 0) + t_res.get("n_nein", 0) + t_res.get("n_nz", 0)
    t_total = t_res.get("max_full") or (t_answered + t_res.get("n_pending", 0))
    e_total = e_res.get("n_logs", 0) * e_res.get("n_items", 0)
    e_sub = f"{e_res.get('points', 0)} / {e_res.get('max', 0)} pts"

    pending_t = [iid for iid, c in (t_res.get("per_item") or {}).items()
                 if c.get("value") is None]

    # ── Donuts ───────────────────────────────────────────────────────────
    # Theoretical Fit (reported as #Ja / #Items, e.g. 2/3) and Empirical Fit
    # (a percentage) stand side by side — the two legs are never combined.
    # Each donut carries a "View details" link straight into its survey.
    def _donut_col(donut: html.Div, action: Optional[str] = None) -> html.Div:
        children = [donut]
        if action is not None:
            children.append(html.Button(
                "View details ↗",
                id=ids.fc_id("fb-ov-action", inst.id, cls=cls, action=action),
                n_clicks=0,
                className="fc-survey-btn fc-survey-btn-ghost",
                style={"fontSize": "11px", "padding": "5px 10px",
                       "whiteSpace": "nowrap"}))
        return html.Div(
            style={"display": "flex", "flexDirection": "column",
                   "alignItems": "center", "gap": "10px"},
            children=children)

    donuts = html.Div(
        style={"display": "flex", "gap": "32px", "padding": "28px 24px",
               "justifyContent": "center", "alignItems": "flex-start",
               "flexWrap": "wrap"},
        children=[
            _donut_col(_theoretical_donut(t_res, size=180,
                                          label="Theoretical Fit"),
                       action="pa"),
            _donut_col(_score_donut(fit_e, size=180, label="Empirical Fit",
                                    sublabel=e_sub), action="eb"),
        ],
    )

    # ── Block 1 — coverage ───────────────────────────────────────────────
    def _coverage_line(label: str, answered: int, total: int,
                       extra: str = "") -> html.Div:
        return html.Div(className="fc-survey-coverage-line", children=[
            html.Span(label, className="fc-survey-coverage-key"),
            html.Span(f"{answered} / {total} answered{extra}",
                      className="fc-survey-coverage-val"),
        ])

    t_extra = (f" · pending: {', '.join(pending_t)}" if pending_t else "")
    e_pending = e_res.get("n_pending", 0)
    e_nz = e_res.get("n_nz", 0)
    e_extra = ""
    if e_pending or e_nz:
        bits = []
        if e_pending:
            bits.append(f"{e_pending} pending")
        if e_nz:
            bits.append(f"{e_nz} n.z.")
        e_extra = " · " + ", ".join(bits)

    coverage = html.Div(
        style={"padding": "4px 24px 18px"},
        children=[
            html.Div("Coverage", className="fc-survey-section-label"),
            _coverage_line("Theoretical", t_answered, t_total, t_extra),
            _coverage_line("Empirical", e_res.get("n_scored", 0),
                           e_total, e_extra),
        ],
    )

    # ── Block 1b — per-log Empirical breakdown ───────────────────────────
    per_log_block = _per_log_block(e_res, inst, cls)

    # ── Block 2 — per-category breakdown ─────────────────────────────────
    breakdown = html.Div(
        style={"padding": "4px 24px 20px"},
        children=[
            html.Div("Per-category breakdown",
                     className="fc-survey-section-label"),
            html.Div(className="fc-survey-2col", children=[
                _breakdown_column("Theoretical",
                                  _axis_groups_t(cls, t_res.get("per_item") or {})),
                _breakdown_column("Empirical",
                                  _axis_groups_e(cls, e_res.get("per_cell") or {},
                                                 e_res.get("n_logs", 0))),
            ]),
        ],
    )

    # ── Block 3 — suitability sentence ───────────────────────────────────
    suitability = html.Div(
        style={"margin": "0 24px 20px"},
        className="fc-survey-callout",
        children=[
            html.Div("Suitability", className="fc-survey-callout-key"),
            html.Div(_suitability_sentence(cls, t_res, e_res),
                     className="fc-survey-callout-text"),
        ],
    )

    body = html.Div(className="fc-survey-card", children=[
        html.Div(className="fc-survey-card-head", children=[
            html.Div("Result", className="fc-survey-card-eyebrow"),
            html.Div("Theoretical Fit (as #Yes / #items) and Empirical Fit "
                      "(as a percentage) reported side by side for this "
                      "miner × class combination — the two legs are not "
                      "combined.",
                      className="fc-survey-card-lede"),
        ]),
        donuts,
        coverage,
        per_log_block,
        breakdown,
        suitability,
        html.Div(className="fc-survey-card-footer", children=[
            html.Div(_cls_badge(cls)),
            html.Div(style={"display": "flex", "gap": "8px"}, children=[
                html.Button(
                    "Edit Theoretical",
                    id=ids.fc_id("fb-ov-action", inst.id, cls=cls,
                                 action="edit"),
                    n_clicks=0,
                    className="fc-survey-btn fc-survey-btn-ghost"),
                html.Button(
                    "Edit Empirical",
                    id=ids.fc_id("fb-ov-action", inst.id, cls=cls,
                                 action="pb"),
                    n_clicks=0,
                    className="fc-survey-btn fc-survey-btn-ghost"),
                html.Button("▶ To overview",
                            id=ids.FB_PHASE_B_DONE_TO_OVERVIEW_BTN,
                            n_clicks=0,
                            className="fc-survey-btn "
                                      "fc-survey-btn-primary"),
            ]),
        ]),
    ])

    return [topbar, _nav_strip("result", has_selection=True), body]


def _per_log_block(e_res: dict, inst: MinerInstance, cls: str) -> html.Div:
    """Per-log Empirical breakdown: how many points each log scored, its own
    Fit, and the note that the Empirical Fit is the mean ("Mittelmaß") of them.

    Built from ``phase_e_fit``'s ``per_log`` so it always matches the donut.
    Each scored-log row is clickable and jumps back into the Empirical survey
    (Phase E) positioned at that log, so the rater can revise its cells.
    """
    per_log = e_res.get("per_log") or {}
    if not per_log:
        return html.Div()

    # Map each per-log stem to its index in the Phase-E log order so a click can
    # set the Phase-B nav cursor straight to that log. Stems outside the current
    # Phase-E selection (e.g. limited) stay non-clickable.
    log_idx_by_stem = {
        log_path.stem: i
        for i, log_path in enumerate(fb_phase_b.phase_b_logs(cls))
    }

    def _row(stem: str, acc: dict) -> html.Tr:
        lfit = acc.get("fit")
        pending = acc.get("n_pending", 0)
        fit_txt = "—" if lfit is None else f"{lfit:.0f}%"
        pts_txt = f"{acc.get('points', 0)} / {acc.get('max', 0)} pts"
        if pending:
            pts_txt += f" · {pending} pending"
        log_idx = log_idx_by_stem.get(stem)
        clickable = log_idx is not None
        name_children = [html.Span(stem)]
        if clickable:
            name_children.append(
                html.Span("↗", className="fc-survey-log-open",
                          style={"marginLeft": "6px",
                                 "color": "var(--ring-accent, #5B6CB8)"}))
        row_kwargs = {}
        if clickable:
            row_kwargs = {
                "id": ids.fc_id("fb-log-open", inst.id, cls=cls,
                                log_idx=log_idx),
                "n_clicks": 0,
                "className": "fc-survey-log-row is-clickable",
                "title": "Open this log in the Empirical survey",
            }
        return html.Tr(
            children=[
                html.Td(name_children, className="fc-survey-row-miner",
                        style={"fontWeight": "600"}),
                html.Td(pts_txt, style={"color": "var(--text-muted)",
                                        "fontSize": "12px"}),
                html.Td(fit_txt, style={"textAlign": "right",
                                        "fontVariantNumeric": "tabular-nums",
                                        "fontWeight": "700"}),
            ],
            **row_kwargs,
        )

    rows = [_row(stem, acc) for stem, acc in per_log.items()]

    fit_e = e_res.get("fit")
    n_scored = e_res.get("n_logs_scored", 0)
    mean_txt = "—" if fit_e is None else f"{fit_e:.0f}%"
    mean_row = html.Tr(
        style={"borderTop": "2px solid var(--border, #E3E5EA)"},
        children=[
            html.Td("Empirical Fit (mean across logs)",
                    style={"fontWeight": "700"}),
            html.Td(f"mean of {n_scored} scored log"
                    f"{'' if n_scored == 1 else 's'}",
                    style={"color": "var(--text-muted)", "fontSize": "12px"}),
            html.Td(mean_txt, style={"textAlign": "right",
                                     "fontVariantNumeric": "tabular-nums",
                                     "fontWeight": "800"}),
        ])

    return html.Div(
        style={"padding": "4px 24px 18px"},
        children=[
            html.Div("Per-log Empirical breakdown",
                     className="fc-survey-section-label"),
            html.Table(
                className="fc-survey-matrix",
                style={"width": "100%"},
                children=[html.Tbody(rows + [mean_row])]),
            html.Div(
                "The Empirical Fit is the mean („Mittelmaß“) of "
                "the per-log Fits: each log is scored on its own answered "
                "cells, then averaged so every log carries equal weight.",
                className="fc-survey-card-lede",
                style={"marginTop": "8px"}),
        ],
    )


# ── Phase B wizard ──────────────────────────────────────────────────────────

def _phase_b_survey_view(inst: MinerInstance, cls: str,
                          nav: dict) -> html.Div:
    logs = fb_phase_b.phase_b_logs(cls)
    items = items_phase_b_for_class(cls)

    if not logs or not items:
        return [_topbar("Empirical Evaluation", _CLASS_LABEL.get(cls, cls)),
                _empty_card(
                    f"Empirical Evaluation for {_CLASS_LABEL.get(cls, cls)} "
                    "has no logs or items configured.")]

    try:
        slot = slot_id(_type_id(inst), inst.config)
    except Exception as exc:
        return [_topbar("Empirical Evaluation", _CLASS_LABEL.get(cls, cls)),
                _empty_card(f"Could not create cache slot: {exc}")]

    log_idx = max(0, min(int((nav or {}).get("log_idx") or 0),
                           len(logs) - 1))
    current_log = logs[log_idx]
    answered = _count_phase_b_answers(logs, slot, items)
    total_cells = len(logs) * len(items)

    topbar = _topbar(
        "Empirical Evaluation",
        f"{inst.label or inst.id} · {_CLASS_LABEL.get(cls, cls)}",
        # Progress bar tracks answered cells (monotonic), not the log cursor.
        progress=(answered, total_cells),
        progress_label=f"Log {log_idx + 1}/{len(logs)} · "
                       f"{answered}/{total_cells} answered",
        actions=[
            html.Button("← Change selection",
                        id=ids.FB_PHASE_B_EXIT_BTN,
                        n_clicks=0,
                        className="fc-survey-btn fc-survey-btn-ghost"),
        ],
    )

    tabs = _nav_strip("phase_b", has_selection=True)
    toc = _phase_b_toc(logs, log_idx, slot, items)

    result = _lookup_result(slot, current_log)
    if result is None:
        body = _phase_b_no_run_block(inst, current_log, cls)
    else:
        body = _phase_b_log_card(inst, slot, current_log, result, items, cls)

    nav_bar = _phase_b_nav_bar(log_idx, len(logs))

    return [topbar, tabs, toc, body, nav_bar]


def _phase_b_toc(logs: list[Path], log_idx: int, slot: str,
                  items: list[dict]) -> html.Div:
    chips = []
    for i, log_path in enumerate(logs):
        log_id = _compute_log_id(log_path)
        n_answered = 0
        if log_id:
            cells = fb_scores.load_all_scores(log_id)
            n_answered = sum(1 for it in items
                             if cells.get((slot, it["id"])) and
                                cells[(slot, it["id"])].get("score") is not None)
        if n_answered == len(items):
            status = "is-done"
        elif n_answered:
            status = "is-partial"
        else:
            status = ""
        if i == log_idx:
            status += " is-current"
        chips.append(html.Button(
            id=ids.fc_id("fb-pb-toc", str(log_path)),
            n_clicks=0,
            className=f"fc-survey-toc-cell {status}".strip(),
            children=f"{log_path.stem} · {n_answered}/{len(items)}",
        ))
    return html.Div(chips, className="fc-survey-toc")


def _phase_b_config_block(inst: MinerInstance) -> html.Details:
    """Collapsible, editable miner-config section for the left pane.

    Reuses the Tab-2 ``render_config_form`` so edits flow through the
    Phase-B-scoped persist callback (``persist_phase_b_config``). Editing a
    value changes the cache slot, so the question side flips to "No cached run"
    until the miner is run again.
    """
    schema = _resolve_schema_for(inst)
    return html.Details(
        open=False,
        className="fc-survey-config",
        children=[
            html.Summary("Miner configuration",
                          className="fc-survey-config-summary"),
            html.Div(
                style={"padding": "12px 4px 4px"},
                children=[
                    html.Div("Changing the config invalidates the cached run; "
                              "rerun the log to score the new model.",
                              className="fc-survey-card-lede",
                              style={"marginBottom": "10px"}),
                    render_config_form(schema, inst.id, inst.config),
                ],
            ),
        ],
    )


def _phase_b_left_pane(inst: MinerInstance, log_path: Path, cls: str,
                        model_children: list) -> html.Div:
    head = html.Div(className="fc-survey-card-head", children=[
        html.Div([
            html.Span("Empirical · Log",
                       className="fc-survey-card-eyebrow"),
            _cls_badge(cls),
        ], style={"display": "flex", "gap": "10px",
                  "alignItems": "center"}),
        html.Div(log_path.stem, className="fc-survey-card-title",
                  style={"marginTop": "6px"}),
    ])
    config_block = html.Div(
        style={"padding": "12px 22px 18px",
               "borderTop": "1px solid var(--border-default)"},
        children=[_phase_b_config_block(inst)],
    )
    return html.Div(className="fc-survey-2col-pane",
                    **{"data-fc-scroll-key": f"pb-left-{log_path.stem}"},
                    children=[
        html.Div(className="fc-survey-card", children=[
            head, *model_children, config_block,
        ]),
    ])


def _phase_b_no_run_block(inst: MinerInstance, log_path: Path,
                           cls: str) -> html.Div:
    note = html.Div(
        style={"padding": "16px 22px"},
        children=[
            html.Div("No cached run for this log yet — adjust the config if "
                      "needed, then run.",
                      className="fc-survey-card-lede"),
            html.Div(style={"marginTop": "12px"}, children=[
                html.Button("▶ Run now",
                            id=ids.FB_PHASE_B_RUN_BTN, n_clicks=0,
                            className="fc-survey-btn fc-survey-btn-primary"),
            ]),
        ],
    )
    left = _phase_b_left_pane(inst, log_path, cls, [note])
    right = html.Div(className="fc-survey-2col-pane",
                     **{"data-fc-scroll-key": f"pb-norun-right-{log_path.stem}"},
                     children=[
        _empty_card("Run the log to score it",
                    "The questions appear once a model is discovered."),
    ])
    return html.Div(className="fc-survey-2col", children=[left, right])


def _phase_b_log_card(inst: MinerInstance, slot: str, log_path: Path,
                       result: dict, items: list[dict], cls: str) -> html.Div:
    metrics = extract_metrics(inst, result)
    imported = bool(metrics.pop("_imported", False))

    model_block = html.Div(
        style={"padding": "16px 22px"},
        children=[
            html.Div("Discovered model",
                      className="fc-survey-section-label"),
            _render_model_view(result),
            html.Div("Metrics",
                      className="fc-survey-section-label",
                      style={"marginTop": "16px"}),
            _metric_strip(metrics, imported),
        ],
    )
    left = _phase_b_left_pane(inst, log_path, cls, [model_block])

    item_cards = [
        _phase_b_item_card(inst, log_path, slot, item, metrics)
        for item in items
    ]
    right = html.Div(className="fc-survey-2col-pane",
                     **{"data-fc-scroll-key": f"pb-right-{log_path.stem}"},
                     children=[
        html.Div(className="fc-survey-card", children=[
            html.Div(className="fc-survey-card-head", children=[
                html.Div("Questions", className="fc-survey-card-eyebrow"),
                html.Div(f"Rate the discovered model on {len(items)} items",
                          className="fc-survey-card-lede"),
            ]),
            html.Div(
                style={"padding": "16px 22px", "display": "flex",
                       "flexDirection": "column", "gap": "14px"},
                children=item_cards,
            ),
        ]),
    ])

    return html.Div(className="fc-survey-2col", children=[left, right])


# ARM relations are not a ground truth, only an orientation the model can be
# read against, so both reference panels say so explicitly.
_ARM_CAPTION = "Orientation from ARM relations, not ground truth."


def _segment_hint_block(segments: list[dict]) -> html.Div:
    """Reference panel listing the hand-authored stable segments for this
    log + item: a section label, then one row per segment (name + activity
    chips + optional note). These are ARM-derived orientation, not ground
    truth."""
    rows = []
    for seg in segments:
        chips = [
            html.Span(act, className="fc-seg-chip")
            for act in seg.get("activities", ())
        ]
        children = [
            html.Span(seg.get("name", ""), className="fc-seg-name"),
            html.Div(chips, className="fc-seg-chips"),
        ]
        note = seg.get("note")
        if note:
            children.append(html.Div(note, className="fc-seg-note"))
        rows.append(html.Div(children, className="fc-seg-hint-row"))
    return html.Div(className="fc-seg-hint", children=[
        html.Div("Stable activity segments the model should reflect",
                  className="fc-seg-hint-label"),
        html.Div(_ARM_CAPTION, className="fc-seg-hint-caption"),
        *rows,
    ])


# Strength tiers for relationship rules, strongest first. The rank orders the
# bullets; the label tags each one so an eventual order is never read as a
# direct succession. "note" is the untyped catch-all and carries no badge.
_RULE_STRENGTH_META = {
    "direct":    (0, "direct"),
    "presence":  (1, "always present"),
    "exclusion": (2, "exclusion"),
    "eventual":  (3, "eventual"),
    "note":      (4, None),
}


def _rules_hint_block(rules: list[dict]) -> html.Div:
    """Reference panel listing the hand-authored activity relationships the
    model should reflect for this log + item (loosely-structured logs). Bullets
    are ordered by relationship strength (direct succession before an eventual
    order) and each carries a strength label. These follow from ARM relations
    and are an orientation, not a ground truth or a hard constraint."""
    ordered = sorted(
        rules,
        key=lambda r: _RULE_STRENGTH_META.get(r.get("strength"), (9, None))[0],
    )
    items = []
    for r in ordered:
        _, label = _RULE_STRENGTH_META.get(r.get("strength"), (9, None))
        children = []
        if label:
            children.append(html.Span(label, className="fc-seg-strength"))
        children.append(html.Span(r.get("text", "")))
        items.append(html.Li(children, className="fc-seg-rule"))
    return html.Div(className="fc-seg-hint", children=[
        html.Div("Activity relationships the model should reflect",
                  className="fc-seg-hint-label"),
        html.Div(_ARM_CAPTION + " Ordered by strength.",
                  className="fc-seg-hint-caption"),
        html.Ul(className="fc-seg-rules", children=items),
    ])


def _phase_b_item_card(inst: MinerInstance, log_path: Path, slot: str,
                        item: dict, metrics: dict) -> html.Div:
    item_id = item["id"]
    log_id = _compute_log_id(log_path)
    persisted = (fb_scores.load_score(log_id, slot, item_id)
                 if log_id else None)
    current_score = (persisted.get("score")
                     if isinstance(persisted, dict) else None)
    current_note = ((persisted.get("note")
                     if isinstance(persisted, dict) else "") or "")
    nz_selected = (isinstance(persisted, dict)
                   and persisted.get("value") == "nz")

    scale_rows = list(item["scale"])
    segments = fb_annotations.segments_for(log_path.stem, item_id)
    rules = fb_annotations.rules_for(log_path.stem, item_id)

    metric_keys = item.get("metric_keys") or ()
    evidence_chips = []
    for key in metric_keys:
        value = metrics.get(key)
        evidence_chips.append(html.Span(
            f"{key}: {_fmt(value, False)}",
            style={"fontFamily": "'IBM Plex Mono', monospace",
                   "fontSize": "11px", "padding": "3px 8px",
                   "borderRadius": "6px",
                   "background": "var(--bg-subtle)",
                   "color": "var(--text-secondary)"},
        ))

    return html.Div(
        style={"border": "1px solid var(--border-default)",
               "borderRadius": "10px",
               "padding": "16px"},
        children=[
            html.Div(className="fc-survey-item-head", children=[
                html.Span(item_id, className="fc-survey-item-id"),
                html.Span(item.get("title", ""),
                           className="fc-survey-item-title",
                           style={"fontSize": "15px"}),
                html.Span(item.get("axis", ""),
                           className="fc-survey-item-axis"),
            ]),
            html.Div(item.get("question", ""),
                      className="fc-survey-item-question",
                      style={"fontSize": "13px"}),
            (_segment_hint_block(segments) if segments else html.Div()),
            (_rules_hint_block(rules) if rules else html.Div()),
            _likert_tiles("fb-pb-opt", scale_rows, current_score, inst.id,
                          nz_selected=nz_selected,
                          log=str(log_path), item=item_id),
            (html.Div(evidence_chips,
                       style={"display": "flex", "gap": "6px",
                              "flexWrap": "wrap", "marginTop": "6px"})
             if evidence_chips else html.Div()),
            html.Label("Note (optional)",
                        className="fc-survey-field-label"),
            dcc.Textarea(
                id=ids.fc_id("fb-pb-note", inst.id,
                              log=str(log_path), item=item_id),
                value=current_note,
                className="fc-survey-ta",
            ),
        ],
    )


def _phase_b_nav_bar(log_idx: int, n_logs: int) -> html.Div:
    on_last = log_idx >= n_logs - 1
    return html.Div(className="fc-survey-card", children=[
        html.Div(className="fc-survey-card-footer",
                  style={"borderTop": "none"},
                  children=[
                      html.Button("← Previous log",
                                  id=ids.FB_PHASE_B_PREV_BTN, n_clicks=0,
                                  disabled=log_idx <= 0,
                                  className="fc-survey-btn fc-survey-btn-ghost"),
                      html.Div(f"Log {log_idx + 1} / {n_logs}",
                                style={"fontSize": "11px",
                                       "color": "var(--text-muted)",
                                       "fontWeight": 600,
                                       "letterSpacing": "0.06em",
                                       "textTransform": "uppercase"}),
                      html.Div(style={"display": "flex", "gap": "8px"},
                                children=[
                                    html.Button("Next log →" if not on_last
                                                 else "Finish ▸",
                                                 id=(ids.FB_PHASE_B_NEXT_BTN
                                                      if not on_last
                                                      else ids.FB_PHASE_B_FINISH_BTN),
                                                 n_clicks=0,
                                                 className="fc-survey-btn "
                                                            "fc-survey-btn-primary"),
                                ]),
                  ]),
    ])


# ── Overview matrix ────────────────────────────────────────────────────────

def _add_miner_button() -> html.Button:
    return html.Button(
        "+ Add miner",
        id=ids.FB_ADD_MINER_BTN, n_clicks=0,
        className="fc-survey-btn fc-survey-btn-primary",
        style={"whiteSpace": "nowrap"},
    )


def _has_scores(rep: dict) -> bool:
    """A miner is shown in the overview once it carries any score — a Phase-T
    seed or a saved Theoretical/Empirical answer both surface as a non-``None``
    fit. Miners that are merely registered (no seed, no answers) stay hidden
    until they are scored via "+ Add miner"."""
    fits = list((rep.get("t_fits") or {}).values()) \
        + list((rep.get("e_fits") or {}).values())
    return any(f is not None for f in fits)


def _overview_view(state: FlexState,
                   ov_open: Optional[dict] = None) -> html.Div:
    header = html.Div(className="fc-survey-card", children=[
        html.Div(className="fc-survey-card-head",
                 style={"flexDirection": "row", "alignItems": "flex-start",
                        "justifyContent": "space-between", "gap": "16px"},
                 children=[
                     html.Div([
                         html.Div("Overview", className="fc-survey-card-eyebrow"),
                         html.Div("Fit matrix · Miner × Class",
                                  className="fc-survey-card-title"),
                     ]),
                     _add_miner_button(),
                 ]),
    ])

    specs = miner_registry.miner_specs()
    nav = _nav_strip("overview", has_selection=False)
    if not specs:
        return html.Div([nav, header, _empty_card(
            "No miners registered — nothing to show.")])

    # Iterate the registry (one ephemeral instance per spec) but list only the
    # miners that actually carry a score; the report drives both the filter and
    # the row, so it is computed once per miner.
    rows = []
    for spec in specs:
        inst = _ephemeral_instance_for_spec(spec.id)
        if inst is None:
            continue
        selected_miner = _miner_id_of(inst)
        if selected_miner is None:
            continue
        rep = fb_combine.report(selected_miner, with_answers=True, state=state)
        if not _has_scores(rep):
            continue
        rows.append(_overview_row(inst, state, ov_open, rep=rep))

    if not rows:
        return html.Div([nav, header, _empty_card(
            "No miners scored yet.",
            "Use \"+ Add miner\" to pick a miner and a class and start "
            "scoring.")])

    header_row = html.Tr([
        html.Th("Miner"),
        html.Th(_CLASS_LABEL["structured"], style={"textAlign": "center"}),
        html.Th(_CLASS_LABEL["semi"], style={"textAlign": "center"}),
        html.Th(_CLASS_LABEL["loosely"], style={"textAlign": "center"}),
    ])
    table_card = html.Div(className="fc-survey-card", children=[
        html.Table(className="fc-survey-matrix",
                    children=[html.Thead(header_row),
                              html.Tbody(rows)]),
    ])

    return html.Div([nav, header, table_card])


def _overview_row(inst: MinerInstance, state: FlexState,
                  ov_open: Optional[dict] = None,
                  rep: Optional[dict] = None):
    selected_miner = _miner_id_of(inst)
    paradigm = _paradigm_of(inst)
    paradigm_label = _PARADIGM_LABEL.get(paradigm, paradigm or "")

    name_cell = html.Td([
        html.Div(inst.label or inst.id, className="fc-survey-row-miner"),
        html.Div(paradigm_label, className="fc-survey-row-sub"),
    ])

    if selected_miner is None:
        empty = html.Td("n/a", colSpan=3,
                         style={"color": "var(--text-muted)",
                                "fontSize": "12px"})
        return html.Tr([name_cell, empty])

    if rep is None:
        rep = fb_combine.report(selected_miner, with_answers=True, state=state)
    e_fits = rep.get("e_fits") or {}
    per_class = rep.get("per_class") or {}

    cells = []
    for cls_key in ("structured", "semi", "loosely"):
        t_det = (per_class.get(cls_key) or {}).get("phase_t") or {}
        e_det = (per_class.get(cls_key) or {}).get("phase_e") or {}
        log_fits = [acc.get("fit")
                    for acc in (e_det.get("per_log") or {}).values()
                    if acc.get("fit") is not None]
        cells.append(_overview_cell(inst, cls_key, t_det,
                                    e_fits.get(cls_key), log_fits))

    return html.Tr([name_cell, *cells])


def _overview_cell(inst: MinerInstance, cls: str,
                    t_det: Optional[dict],
                    fit_e: Optional[float],
                    log_fits: Optional[list[float]] = None):
    # Two rings per cell — the legs are never combined: the Theoretical Fit
    # (as #Yes / #items, e.g. 2/3) and the Empirical Fit (a percentage). Each
    # renders "—" while unscored. Below the Empirical ring, a dot-strip shows
    # the spread of the per-log Empirical Fits so a tight cluster and a wide
    # spread behind the same mean stay distinguishable. A "View details" button
    # opens the result page.
    e_col = [_score_donut(fit_e, size=72, label="Empirical")]
    spread = _per_log_spread(log_fits or [])
    if spread is not None:
        e_col.append(spread)
    rings = html.Div(
        style={"display": "flex", "gap": "18px", "alignItems": "flex-start",
               "justifyContent": "center", "flexWrap": "wrap"},
        children=[
            _theoretical_donut(t_det, size=72, label="Theoretical"),
            html.Div(style={"display": "flex", "flexDirection": "column",
                            "alignItems": "center", "gap": "4px"},
                     children=e_col),
        ],
    )
    children = [rings]
    children.append(html.Button(
        "View details",
        id=ids.fc_id("fb-ov-action", inst.id, cls=cls, action="result"),
        n_clicks=0,
        className="fc-survey-btn fc-survey-btn-ghost",
        style={"fontSize": "11px", "padding": "5px 10px",
               "whiteSpace": "nowrap"},
    ))
    return html.Td(
        style={"textAlign": "center", "verticalAlign": "middle"},
        children=html.Div(
            style={"display": "flex", "flexDirection": "column",
                   "alignItems": "center", "gap": "10px"},
            children=children,
        ),
    )


def _per_log_spread(log_fits: list[float]) -> Optional[html.Div]:
    """Compact dot-strip of the per-log Empirical Fits (0–100 axis).

    One neutral dot per scored log; the mean (the Empirical Fit itself) is a
    short tick. Returns ``None`` when fewer than two logs are scored, since a
    single point carries no distribution. Stays farbneutral and within-cell —
    it describes one (miner, class) cell, never a cross-miner comparison.
    """
    fits = [max(0.0, min(100.0, float(f))) for f in log_fits]
    if len(fits) < 2:
        return None
    lo, hi = min(fits), max(fits)
    mean = sum(fits) / len(fits)

    width, height, pad = 92, 16, 5
    span = width - 2 * pad

    def _x(pct: float) -> float:
        return pad + span * (pct / 100.0)

    y = height / 2
    dot = _resolve_css_var("var(--ring-accent, #5B6CB8)")
    track = _resolve_css_var("var(--ring-track, #E4E7ED)")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}">',
        f'<line x1="{pad}" y1="{y}" x2="{width - pad}" y2="{y}" '
        f'stroke="{track}" stroke-width="2" stroke-linecap="round"/>',
        # min–max range bar behind the dots
        f'<line x1="{_x(lo):.2f}" y1="{y}" x2="{_x(hi):.2f}" y2="{y}" '
        f'stroke="{dot}" stroke-width="2" stroke-linecap="round" '
        f'opacity="0.35"/>',
    ]
    for f in fits:
        parts.append(f'<circle cx="{_x(f):.2f}" cy="{y}" r="2.4" '
                     f'fill="{dot}"/>')
    # Mean tick (taller than the dots) so the cell's Empirical mean is locatable.
    parts.append(f'<line x1="{_x(mean):.2f}" y1="{y - 4}" '
                 f'x2="{_x(mean):.2f}" y2="{y + 4}" '
                 f'stroke="{dot}" stroke-width="1.5"/>')
    parts.append('</svg>')
    from urllib.parse import quote
    src = "data:image/svg+xml;utf8," + quote("".join(parts))

    range_txt = (f"{lo:.0f}–{hi:.0f}%" if hi > lo else f"{lo:.0f}%")
    return html.Div(
        title=(f"Empirical per-log spread · {len(fits)} logs · "
               f"min {lo:.0f}% · mean {mean:.0f}% · max {hi:.0f}%"),
        style={"display": "flex", "flexDirection": "column",
               "alignItems": "center", "gap": "1px"},
        children=[
            html.Img(src=src,
                     style={"width": f"{width}px", "height": f"{height}px"}),
            html.Div(f"E per-log · {range_txt}",
                     style={"fontSize": "9px", "color": "var(--text-muted)",
                            "letterSpacing": "0.02em",
                            "fontVariantNumeric": "tabular-nums"}),
        ],
    )


# ── Score donut (SVG via data URI) ─────────────────────────────────────────

def _theoretical_donut(t_res: Optional[dict], *, size: int = 180,
                       label: str = "Theoretical Fit") -> html.Div:
    """Theoretical Fit ring, reported as a fraction ``#Ja / #Items`` (e.g.
    ``2/3``) rather than a percentage. The arc fill follows ``points / max_full``;
    an unscored leg (nothing answered) renders as an empty ring with ``—``."""
    t_res = t_res or {}
    points = t_res.get("points", 0)
    max_full = t_res.get("max_full") or 3
    answered = t_res.get("max", 0)  # #items that count (ja/nein/nz)
    if answered <= 0 or not max_full:
        return _score_donut(None, size=size, label=label, value_text="—")
    pct = points / max_full * 100
    return _score_donut(pct, size=size, label=label,
                        value_text=f"{points}/{max_full}")


def _score_donut(pct: Optional[float], *,
                 size: int = 200, label: str = "",
                 sublabel: str = "",
                 stroke: int = 10,
                 accent: Optional[str] = None,
                 value_text: Optional[str] = None) -> html.Div:
    """Score ring. The arc fill follows ``pct`` (0–100); the centre text is
    ``"{pct}%"`` unless ``value_text`` overrides it (e.g. ``"2/3"`` for the
    Theoretical Fit, which is reported as a fraction, not a percentage)."""
    pct_value = 0.0 if pct is None else max(0.0, min(100.0, float(pct)))
    radius = (size - stroke) / 2
    circumference = 2 * 3.141592653589793 * radius
    dash = circumference * (pct_value / 100.0)
    gap = circumference - dash
    cx = cy = size / 2

    # Single neutral arc colour (no green/amber/red banding, not black); unrated
    # stays muted. Callers may still override via ``accent``.
    if accent is None:
        if pct is None:
            color = "var(--text-muted, #bbb)"
        else:
            color = "var(--ring-accent, #5B6CB8)"
    else:
        color = accent

    track_color = "var(--ring-track, #E4E7ED)"
    if value_text is None:
        value_text = "—" if pct is None else f"{pct_value:.0f}%"

    svg_data_uri = _donut_svg_data_uri(size, stroke, radius, cx, cy,
                                         dash, gap, color, track_color)
    svg = html.Div(
        style={"position": "relative", "width": f"{size}px",
               "height": f"{size}px"},
        children=[
            html.Img(src=svg_data_uri,
                     style={"position": "absolute", "inset": "0",
                            "width": "100%", "height": "100%"}),
            html.Div(
                style={"position": "absolute", "inset": "0",
                       "display": "flex", "alignItems": "center",
                       "justifyContent": "center",
                       "flexDirection": "column"},
                children=[
                    html.Div(value_text, style={
                        "fontSize": f"{int(size * 0.22)}px",
                        "fontWeight": "700",
                        "color": "var(--text-primary)",
                        "fontVariantNumeric": "tabular-nums",
                        "lineHeight": "1"}),
                    (html.Div(sublabel, style={
                        "fontSize": f"{max(10, int(size * 0.08))}px",
                        "color": "var(--text-muted)",
                        "marginTop": "4px"}) if sublabel else html.Div()),
                ],
            ),
        ],
    )

    children = [svg]
    if label:
        children.append(html.Div(label, style={
            "marginTop": "8px",
            "fontSize": "11px",
            "fontWeight": "700",
            "color": "var(--text-muted)",
            "textTransform": "uppercase",
            "letterSpacing": "0.08em"}))

    return html.Div(
        style={"display": "inline-flex", "flexDirection": "column",
               "alignItems": "center"},
        children=children,
    )


def _donut_svg_data_uri(size: int, stroke: int, radius: float,
                          cx: float, cy: float,
                          dash: float, gap: float, color: str,
                          track_color: str) -> str:
    plain_color = _resolve_css_var(color)
    plain_track = _resolve_css_var(track_color)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {size} {size}">'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" '
        f'fill="none" stroke="{plain_track}" stroke-width="{stroke}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" '
        f'fill="none" stroke="{plain_color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" '
        f'stroke-dasharray="{dash:.3f} {gap:.3f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'</svg>'
    )
    from urllib.parse import quote
    return "data:image/svg+xml;utf8," + quote(svg)


def _resolve_css_var(color: str) -> str:
    color = color.strip()
    if color.startswith("var(") and "," in color:
        return color.split(",", 1)[1].rstrip(") ").strip()
    return color


# ── Metric strip (reused for Phase-B) ──────────────────────────────────────

_METRIC_DISPLAY: tuple[tuple[str, str], ...] = (
    ("replay_fitness", "Replay fitness"),
    ("etc_precision", "ETC precision"),
    ("non_vacuous_satisfaction_rate", "Non-vac. sat."),
    ("vacuity_rate", "Vacuity rate"),
    ("constraint_density", "Constraint density"),
    ("process_tree_depth", "Tree depth"),
    ("extended_cardoso_cfc", "CFC"),
    ("flower_detected", "Flower"),
)


def _fmt(value: object, imported: bool) -> str:
    if value is None:
        return "n/a" if imported else "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _metric_strip(metrics: dict, imported: bool) -> html.Div:
    pills = []
    for key, label in _METRIC_DISPLAY:
        if key not in metrics:
            continue
        value = metrics.get(key)
        pills.append(html.Div(
            style={"display": "inline-flex", "flexDirection": "column",
                   "padding": "8px 12px", "marginRight": "6px",
                   "marginBottom": "6px",
                   "background": "var(--bg-subtle)",
                   "borderRadius": "8px", "fontSize": "11px",
                   "minWidth": "90px"},
            children=[
                html.Span(label, style={"color": "var(--text-muted)",
                                          "fontSize": "10px",
                                          "textTransform": "uppercase",
                                          "letterSpacing": "0.06em",
                                          "fontWeight": 700}),
                html.Span(_fmt(value, imported),
                            style={"fontWeight": "600",
                                   "fontSize": "13px",
                                   "fontVariantNumeric": "tabular-nums"}),
            ],
        ))
    if not pills:
        return html.Div("(no metrics available)",
                         style={"fontSize": "12px",
                                "color": "var(--text-muted)"})
    return html.Div(pills, style={"marginBottom": "0"})


# ── Helpers ────────────────────────────────────────────────────────────────

def _count_phase_b_answers(logs: list[Path], slot: str,
                             items: list[dict]) -> int:
    total = 0
    item_ids = {it["id"] for it in items}
    for log_path in logs:
        log_id = _compute_log_id(log_path)
        if not log_id:
            continue
        cells = fb_scores.load_all_scores(log_id)
        for (cell_slot, item_id), payload in cells.items():
            if cell_slot != slot or item_id not in item_ids:
                continue
            if payload.get("score") is not None:
                total += 1
    return total


def _paradigm_of(inst: MinerInstance) -> str:
    if inst.spec_source == "registry":
        spec = miner_registry.get(inst.spec_id or "")
        return spec.paradigm if spec else ""
    if inst.inline_spec:
        return inst.inline_spec.paradigm
    return ""


def _miner_id_of(inst: MinerInstance) -> Optional[str]:
    if inst.spec_source == "registry" and inst.spec_id:
        return inst.spec_id
    return None


def _find_instance(state: FlexState, instance_id: str) -> Optional[MinerInstance]:
    for inst in state.instances:
        if inst.id == instance_id:
            return inst
    return None


def _ephemeral_instance_for_spec(spec_id: str) -> Optional[MinerInstance]:
    """Synthesize a registry-backed instance with default config.

    Mirrors the modal's add path (``miner_list_callbacks._build_instance_from_modal``):
    config is pre-filled from the spec's schema defaults. ``id=spec_id`` keeps it
    deterministic so pattern-matched component IDs (Phase-A/B score/note cells)
    stay stable across re-renders and the same instance can be reconstructed
    from the session/pattern id alone — no lookup in ``state.instances`` needed.
    """
    spec = miner_registry.get(spec_id)
    if spec is None:
        return None
    config = {p.key: p.default for p in spec.config_schema}
    return MinerInstance(
        id=spec_id,
        spec_source="registry",
        spec_id=spec_id,
        label=spec.label,
        config=config,
    )


def _resolve_miner(state: FlexState, miner_id: str) -> Optional[MinerInstance]:
    """Resolve a Tab-3 ``miner_id`` to an instance.

    First honour a configured Tab-2 instance (back-compat with sessions that
    stored an instance UUID), then fall back to a registry spec id — which is
    what the registry-driven start dropdown now emits.
    """
    if not miner_id:
        return None
    inst = _find_instance(state, miner_id)
    if inst is not None:
        return inst
    return _ephemeral_instance_for_spec(miner_id)


def _spec_dropdown_label(spec) -> str:
    """Plain-text label for the registry miner dropdown (paradigm in parens)."""
    paradigm = _PARADIGM_LABEL.get(spec.paradigm, spec.paradigm or "")
    return f"{spec.label}  ·  {paradigm}" if paradigm else spec.label


def _compute_log_id(log_path: Path) -> Optional[str]:
    try:
        return result_cache.compute_log_id(Path(log_path))
    except (OSError, ValueError) as exc:
        logger.warning("compute_log_id failed for %s: %s", log_path, exc)
        return None


def _lookup_result(slot: str, log_path: Path) -> Optional[dict]:
    log_id = _compute_log_id(log_path)
    if not log_id:
        return None
    entry = result_cache.lookup(slot, log_id)
    if entry is None:
        return None
    try:
        return result_cache.rehydrate(entry)
    except Exception as exc:
        logger.warning("rehydrate failed for %s/%s: %s", slot, log_id, exc)
        return None
