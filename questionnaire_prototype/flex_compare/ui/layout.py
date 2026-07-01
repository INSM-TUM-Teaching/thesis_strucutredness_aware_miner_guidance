"""Top-level layout: header + tab bar + per-tab body slot."""
from __future__ import annotations

from pathlib import Path

from dash import dcc, html

from flex_compare.internal.shared.paths import PROJECT_ROOT

from flex_compare.state import FlexState
from flex_compare.ui import ids
from flex_compare.ui.tabs import fragebogen, log_and_arm, miners as miners_tab


DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "with-case-ids"


def _default_selected_log(log_dir: Path) -> str | None:
    """First ``*.xes`` in ``log_dir`` (sorted), or ``None`` if there are none."""
    if not log_dir.is_dir():
        return None
    logs = sorted(log_dir.glob("*.xes"))
    return str(logs[0]) if logs else None


def render(state: FlexState) -> html.Div:
    # Tab-2 runs go through LOG_PATH_STORE, which mirrors ``state.selected_log``.
    # When nothing is persisted yet it is ``None``, and every Tab-2 Run / Run-all
    # click silently no-ops (the callbacks guard on a falsy log) with no feedback
    # — which reads as "the buttons don't work". Seed the first available log so
    # the dropdowns and the store are populated on load and the run buttons work
    # immediately. The Questionnaire tab is unaffected (it uses per-class logs).
    if not state.selected_log:
        state.selected_log = _default_selected_log(DEFAULT_LOG_DIR)

    return html.Div(
        style={"fontFamily": "IBM Plex Sans, system-ui, sans-serif",
               "background": "var(--bg-page, #f9fafb)", "minHeight": "100vh"},
        children=[
            # Mirrors navigation (tab + Questionnaire view) into the URL so the
            # browser back/forward buttons work; see routing_callbacks.
            dcc.Location(id=ids.URL_BAR, refresh=False),

            # Persistent state stores
            dcc.Store(id=ids.APP_STATE_STORE, data=state.to_jsonable()),
            dcc.Store(id=ids.LOG_PATH_STORE, data=state.selected_log),
            dcc.Store(id=ids.ARM_RESULT_STORE, data=None),
            dcc.Store(id=ids.RUN_TRIGGER_STORE, data=None),
            dcc.Store(id=ids.ACTIVE_JOBS_FLAG, data=False),
            dcc.Interval(id=ids.TICK_INTERVAL, interval=1500, n_intervals=0,
                         disabled=True),

            # Log-change guard banner (shown only while runs are in flight).
            html.Div(id=ids.LOG_CHANGE_GUARD, style={"display": "none"}),

            # Header — pm-header from comparison_app's design system.
            html.Div(
                className="pm-header",
                style={"maxWidth": "1440px",
                       "margin": "1.2rem auto 0 auto"},
                children=[
                    html.Div([
                        html.Div("Prototype Tool - Structuredness-Aware Miner Guidance", className="pm-brand-title"),
                        html.Div(
                            "Discovery playground — pick a log, add miners, compare",
                            className="pm-brand-sub",
                        ),
                    ]),
                    html.Div(),  # meta column (selected log etc. could live here)
                    html.Div(),  # actions column
                ],
            ),

            # Tabs
            dcc.Tabs(
                id=ids.TABS,
                value=ids.TAB_LOG,
                # Rounded segmented/pill styling (see .pm-tabs in theme.css) so the
                # top tab bar matches the rounded cards and the Fragebogen sub-tabs.
                className="pm-tabs",
                parent_className="pm-tabs-parent",
                # The active tab (and Questionnaire view) is mirrored into the URL
                # by routing_callbacks, which is the single source of truth for
                # navigation — so a reload restores the tab from the URL, not from
                # localStorage persistence (which would fight the URL on load).
                children=[
                    dcc.Tab(label="Log & ARM", value=ids.TAB_LOG,
                            children=log_and_arm.render_layout(DEFAULT_LOG_DIR,
                                                                state.selected_log)),
                    dcc.Tab(label="Miners", value=ids.TAB_MINERS,
                            children=miners_tab.render_layout(state, DEFAULT_LOG_DIR)),
                    dcc.Tab(label="Questionnaire", value=ids.TAB_FRAGEBOGEN,
                            children=fragebogen.render_layout(state)),
                ],
            ),

            # Sticky footer for save feedback
            html.Div(id=ids.SAVE_FEEDBACK,
                     style={"position": "fixed", "bottom": "12px", "right": "16px",
                            "fontSize": "11px", "color": "var(--text-muted, #888)"}),
        ],
    )
