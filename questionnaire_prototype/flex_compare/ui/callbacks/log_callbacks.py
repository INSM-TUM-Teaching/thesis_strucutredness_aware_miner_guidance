"""Log selection + ARM classification callbacks (Tab 1)."""
from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path

from dash import Input, Output, State, ctx, html, no_update

from flex_compare.internal.shared.arm_runner import ArmRunnerError, run_arm

from flex_compare import state as fc_state
from flex_compare.ui import ids
from flex_compare.ui.components import arm_view


logger = logging.getLogger(__name__)


# Lazy import of pm4py for log-stats — keeps app startup fast.
def _log_stats(log_path: Path) -> str:
    try:
        import pm4py

        log = pm4py.read_xes(str(log_path))
        n_cases = log["case:concept:name"].nunique() if hasattr(log, "columns") else len(log)
        n_events = len(log)
        n_activities = log["concept:name"].nunique() if hasattr(log, "columns") else None
        return f"📊 {n_cases} cases · {n_events} events · {n_activities or '—'} activities"
    except Exception as exc:
        return f"(unable to load log: {exc})"


def _classify_log_name(stem: str) -> str | None:
    try:
        from flex_compare.internal.experiment_reports import infer_experiment_class

        cls = infer_experiment_class(stem, default=None)
        return cls
    except Exception:
        return None


def _sidebar_classification(arm_result: dict | None, log_path_value: str | None) -> html.Div:
    """Compact classification widget for the right-hand classification card.

    Adds the filename-derived hint above the colour-stripped badge from
    :mod:`flex_compare.ui.components.arm_view`.
    """
    children: list = []
    if log_path_value:
        name_class = _classify_log_name(Path(log_path_value).stem)
        if name_class:
            children.append(html.Div(
                f"Filename hint: {name_class}",
                className="pm-info",
                style={"fontSize": "11px", "marginBottom": "6px"},
            ))
    children.append(arm_view.classification_badge(arm_result))
    return html.Div(children=children)


def register(app):
    # ── 1. Log selection (dropdown OR upload) → LOG_PATH_STORE ──
    # Both Tab 1's dropdown and Tab 2's dropdown feed this callback and we
    # echo the picked value back to both so they stay in lockstep no matter
    # which one the user touched.
    @app.callback(
        Output(ids.LOG_PATH_STORE, "data"),
        Output(ids.LOG_STATS, "children"),
        Output("fc-toolbar-log-label", "children"),
        Output(ids.LOG_CHANGE_GUARD, "children"),
        Output(ids.LOG_CHANGE_GUARD, "style"),
        Output(ids.LOG_SELECT, "value"),
        Output(ids.MINER_TAB_LOG_SELECT, "value"),
        Input(ids.LOG_SELECT, "value"),
        Input(ids.MINER_TAB_LOG_SELECT, "value"),
        Input(ids.LOG_UPLOAD, "contents"),
        State(ids.LOG_UPLOAD, "filename"),
        State(ids.LOG_PATH_STORE, "data"),
        State(ids.ACTIVE_JOBS_FLAG, "data"),
        prevent_initial_call=False,
    )
    def _select_log(selected_tab1, selected_tab2, upload_contents, upload_filename,
                    current, active_jobs):
        # P4 guard: if a miner run is in flight, refuse to switch logs and
        # tell the user to cancel first. The two refusing paths short-circuit
        # before persistence.
        triggered = ctx.triggered_id
        wants_change = triggered in (ids.LOG_SELECT, ids.MINER_TAB_LOG_SELECT,
                                       ids.LOG_UPLOAD)
        if wants_change and active_jobs:
            banner_style = {
                "display": "block",
                "position": "fixed", "top": "60px", "left": "50%",
                "transform": "translateX(-50%)", "zIndex": 150,
                "background": "#fef3c7", "border": "1px solid #f59e0b",
                "color": "#92400e", "padding": "10px 14px",
                "borderRadius": "6px", "fontSize": "13px",
                "boxShadow": "0 4px 12px rgba(0,0,0,0.15)",
            }
            return (current,
                    no_update, no_update,
                    "Miner runs are in flight — Cancel all in Tab 2 before switching the log.",
                    banner_style,
                    current, current)

        path: str | None
        if triggered == ids.LOG_UPLOAD and upload_contents and upload_filename:
            target_dir = fc_state.state_dir() / "uploads"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / upload_filename
            _, b64 = upload_contents.split(",", 1)
            target.write_bytes(base64.b64decode(b64))
            path = str(target)
        elif triggered == ids.LOG_SELECT:
            path = selected_tab1
        elif triggered == ids.MINER_TAB_LOG_SELECT:
            path = selected_tab2
        else:
            path = current

        hidden = (no_update, {"display": "none"})

        if not path:
            return path, "(no log selected)", "(no log selected)", *hidden, path, path
        p = Path(path)
        if not p.is_file():
            return (path, f"(log file not found: {path})", f"(missing: {p.name})",
                    *hidden, path, path)

        try:
            s = fc_state.load()
            s.selected_log = path
            fc_state.save(s)
        except Exception as exc:
            logger.warning("state save failed: %s", exc)

        return path, _log_stats(p), f"Log: {p.name}", *hidden, path, path

    # ── 2. ARM run on button click ──
    @app.callback(
        Output(ids.ARM_RESULT_STORE, "data"),
        Input(ids.ARM_RUN_BTN, "n_clicks"),
        State(ids.LOG_PATH_STORE, "data"),
        State(ids.ARM_TEMPORAL_SLIDER, "value"),
        State(ids.ARM_EXISTENTIAL_SLIDER, "value"),
        prevent_initial_call=True,
    )
    def _run_arm(n, log_path, temporal, existential):
        if not log_path:
            return None
        try:
            result = run_arm(Path(log_path),
                             temporal_threshold=float(temporal),
                             existential_threshold=float(existential))
        except ArmRunnerError as exc:
            return {"error": str(exc)}
        # Persist thresholds.
        try:
            s = fc_state.load()
            s.arm_thresholds = {"temporal": float(temporal),
                                "existential": float(existential)}
            fc_state.save(s)
        except Exception as exc:
            logger.warning("state save failed: %s", exc)
        # ArmResult is a TypedDict — already JSON-friendly.
        return dict(result)

    # ── 3. ARM → classification badge + heatmap ──
    @app.callback(
        Output(ids.CLASSIFICATION_BADGE, "children"),
        Output(ids.ARM_OUTPUT, "children"),
        Input(ids.ARM_RESULT_STORE, "data"),
        Input(ids.LOG_PATH_STORE, "data"),
    )
    def _render_arm(arm_result, log_path):
        return (
            _sidebar_classification(arm_result, log_path),
            arm_view.render_arm_body(arm_result),
        )
