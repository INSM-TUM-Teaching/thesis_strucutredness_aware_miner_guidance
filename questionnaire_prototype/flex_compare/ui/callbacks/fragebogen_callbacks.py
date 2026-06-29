"""Tab-3 callbacks — session start/reset, on-demand runs, per-cell autosave.

Five callbacks share one session store
(``ids.FB_SESSION_STORE``: ``{miner_id, class, nonce}``):

* ``render_body`` rebuilds the tab's content whenever the session or app state
  changes — the single source of UI state. Action callbacks (start / reset /
  run-all / run-single) only update the session store; the body re-render is
  the *effect*.
* ``start_session`` snapshots the dropdowns into the store.
* ``reset_session`` clears the selection.
* ``run_all_missing`` and ``run_single_log`` invoke
  :func:`flex_compare.runner.run_instance` synchronously per missing log,
  caching the results into ``.miner_cache/results/``. They then bump the
  store's ``nonce`` to force a body re-render that picks up the new cache.
* ``autosave_score`` writes one ``.miner_cache/fitscore_eval/...`` JSON per
  ``(log, instance, item)`` cell on every RadioItems / Textarea change. The
  ``log`` discriminator lives in the pattern ID, so the autosave knows which
  log a score belongs to without round-tripping through any other store.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from dash import ALL, MATCH, Input, Output, State, ctx, no_update

from flex_compare import runner as fc_runner
from flex_compare import state as fc_state
from flex_compare.fragebogen import items as fb_items
from flex_compare.fragebogen import phase_a as fb_phase_a
from flex_compare.fragebogen import phase_a_answers as fb_pa_answers
from flex_compare.fragebogen import scores as fb_scores
from flex_compare.fragebogen.items import get_item, items_for_class
from flex_compare.fragebogen.log_discovery import logs_for_class
from flex_compare.internal.shared.cache import result_cache
from flex_compare.state import FlexState, MinerInstance
from flex_compare.ui import ids
from flex_compare.ui.tabs import fragebogen as fb_tab


logger = logging.getLogger(__name__)


def register(app) -> None:

    # ── Body rendering ──────────────────────────────────────────────────────
    @app.callback(
        Output(ids.FB_BODY, "children"),
        Input(ids.FB_SESSION_STORE, "data"),
        Input(ids.APP_STATE_STORE, "data"),
        Input(ids.FB_PHASE_A_NAV_STORE, "data"),
        Input(ids.FB_PHASE_B_NAV_STORE, "data"),
    )
    def render_body(session, app_state_raw, pa_nav, pb_nav):
        state = _state_from_store(app_state_raw) or FlexState()
        return fb_tab.render_body(session, state, pa_nav, pb_nav)

    # ── Start: dropdowns → session store ────────────────────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_START_BTN, "n_clicks"),
        State(ids.FB_MINER_SELECT, "value"),
        State(ids.FB_CLASS_SELECT, "value"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def start_session(n_clicks, miner_id, cls, current):
        if not n_clicks or not miner_id or not cls:
            return no_update
        nonce = int((current or {}).get("nonce") or 0) + 1
        # Explicit view: the default store view is now "overview", so "Start
        # Phase A" must request the wizard or it would land on the overview.
        return {"miner_id": miner_id, "class": cls,
                "view": "phase_a", "nonce": nonce}

    # ── Reset ──────────────────────────────────────────────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_RESET_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def reset_session(n_clicks, current):
        if not n_clicks:
            return no_update
        nonce = int((current or {}).get("nonce") or 0) + 1
        return {"miner_id": None, "class": None, "nonce": nonce}

    # ── Run all missing ────────────────────────────────────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_RUN_STATUS, "children", allow_duplicate=True),
        Input(ids.FB_RUN_ALL_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def run_all_missing(n_clicks, session, app_state_raw):
        if not n_clicks:
            return no_update, no_update
        session = session or {}
        miner_id = session.get("miner_id")
        cls = session.get("class")
        if not miner_id or not cls:
            return no_update, no_update

        state = _state_from_store(app_state_raw) or FlexState()
        inst = _find_instance(state, miner_id)
        if inst is None:
            return no_update, "⚠ Miner instance not found."

        try:
            slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
        except Exception as exc:
            return no_update, f"⚠ slot_id failed: {exc}"

        logs = logs_for_class(cls, fb_tab.DEFAULT_LOG_DIR)
        missing = [p for p in logs
                   if result_cache.lookup(slot, _safe_log_id(p)) is None]
        if not missing:
            return no_update, "Nothing to do — all logs cached."

        t0 = time.monotonic()
        successes, failures = _run_batch(inst, missing)
        dt = time.monotonic() - t0
        status = (f"✓ {successes} of {len(missing)} runs successful "
                  f"({dt:.1f}s)")
        if failures:
            status += f" · {failures} failed — see logs"

        nonce = int((session or {}).get("nonce") or 0) + 1
        new_session = {**session, "nonce": nonce}
        return new_session, status

    # ── Run a single log ───────────────────────────────────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_RUN_STATUS, "children", allow_duplicate=True),
        Input({"type": "fc-fb-run-single",
                "instance": MATCH, "log": MATCH}, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def run_single_log(n_clicks, session, app_state_raw):
        if not n_clicks:
            return no_update, no_update
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update, no_update
        instance_id = trig.get("instance")
        log_path_str = trig.get("log")
        if not instance_id or not log_path_str:
            return no_update, no_update

        state = _state_from_store(app_state_raw) or FlexState()
        inst = _find_instance(state, instance_id)
        if inst is None:
            return no_update, "⚠ Miner instance not found."

        t0 = time.monotonic()
        successes, failures = _run_batch(inst, [Path(log_path_str)])
        dt = time.monotonic() - t0
        log_name = Path(log_path_str).stem
        if successes:
            status = f"✓ Run for {log_name} done ({dt:.1f}s)"
        else:
            status = f"⚠ Run for {log_name} failed"

        nonce = int((session or {}).get("nonce") or 0) + 1
        new_session = {**(session or {}), "nonce": nonce}
        return new_session, status

    # ── Reload YAML config without restarting the app ──────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_RUN_STATUS, "children", allow_duplicate=True),
        Input(ids.FB_RELOAD_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def reload_config(n_clicks, session):
        if not n_clicks:
            return no_update, no_update
        try:
            fb_items.refresh()
        except Exception as exc:
            logger.warning("reload_config: refresh failed: %s", exc)
            return no_update, f"⚠ Config reload failed: {exc}"
        n_items = len(fb_items.ITEMS)
        nonce = int((session or {}).get("nonce") or 0) + 1
        new_session = {**(session or {}), "nonce": nonce}
        return new_session, f"✓ Config reloaded — {n_items} items"

    # ── Autosave on score / note change ────────────────────────────────────
    @app.callback(
        Output(ids.SAVE_FEEDBACK, "children", allow_duplicate=True),
        Input({"type": "fc-fb-score", "instance": ALL,
                "log": ALL, "item": ALL}, "value"),
        Input({"type": "fc-fb-note", "instance": ALL,
                "log": ALL, "item": ALL}, "value"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def autosave_score(_scores, _notes, app_state_raw):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update
        kind = trig.get("type")
        if kind not in ("fc-fb-score", "fc-fb-note"):
            return no_update

        instance_id = trig.get("instance")
        log_path_str = trig.get("log")
        item_id = trig.get("item")
        if not instance_id or not log_path_str or not item_id:
            return no_update

        state = _state_from_store(app_state_raw)
        inst = _find_instance(state, instance_id) if state else None
        if inst is None:
            return no_update

        log_path = Path(log_path_str)
        log_id = _safe_log_id(log_path)
        if log_id is None:
            return no_update
        try:
            slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
        except Exception as exc:
            logger.warning("autosave: slot_id failed for %s: %s",
                           instance_id, exc)
            return no_update

        triggered_value = None
        triggered_field = None
        for entry in ctx.triggered:
            prop_id = entry.get("prop_id", "")
            if not prop_id.endswith(".value"):
                continue
            triggered_value = entry.get("value")
            if "fc-fb-score" in prop_id:
                triggered_field = "score"
            elif "fc-fb-note" in prop_id:
                triggered_field = "note"
            break

        existing = fb_scores.load_score(log_id, slot, item_id) or {}
        score = existing.get("score")
        note = existing.get("note") or ""
        if triggered_field == "score":
            score = _coerce_score(triggered_value)
        elif triggered_field == "note":
            note = triggered_value or ""

        try:
            fb_scores.save_score(
                log_id=log_id,
                slot=slot,
                item_id=item_id,
                score=score,
                note=note,
                log_stem=log_path.stem,
                instance_id=inst.id,
                instance_label=inst.label or inst.id,
                metric_evidence=_metric_evidence_for(inst, log_id, slot, item_id),
            )
        except OSError as exc:
            logger.warning("autosave: write failed for %s/%s/%s: %s",
                           log_id, slot, item_id, exc)
            return f"⚠ Save failed: {exc}"
        return f"✓ {item_id} · {log_path.stem} saved"

    # ── Phase-A survey: enter / exit ───────────────────────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_A_START_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        prevent_initial_call=True,
    )
    def enter_phase_a_survey(n_clicks, session, nav):
        if not n_clicks:
            return no_update, no_update
        session = dict(session or {})
        session["view"] = "phase_a"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        nav = {"item_idx": 0,
               "nonce": int((nav or {}).get("nonce") or 0) + 1}
        return session, nav

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_A_EXIT_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def exit_phase_a_survey(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        # "← Change selection" → back to the start picker for a fresh choice.
        session["miner_id"] = None
        session["class"] = None
        session["view"] = "start"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    # ── Phase-A survey: prev / next ────────────────────────────────────────
    @app.callback(
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_A_PREV_BTN, "n_clicks"),
        Input(ids.FB_PHASE_A_NEXT_BTN, "n_clicks"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def nav_phase_a(_prev, _next, nav, session):
        trig = ctx.triggered_id
        if trig not in (ids.FB_PHASE_A_PREV_BTN, ids.FB_PHASE_A_NEXT_BTN):
            return no_update
        # Phantom-mount guard (see switch_phase_tab): the nav bar re-mounts with
        # n_clicks=0 on every body re-render; only act on a real click.
        clicks = {ids.FB_PHASE_A_PREV_BTN: _prev, ids.FB_PHASE_A_NEXT_BTN: _next}
        if not clicks.get(trig):
            return no_update
        cls = (session or {}).get("class")
        items = items_for_class(cls)
        if not items:
            return no_update
        idx = int((nav or {}).get("item_idx") or 0)
        if trig == ids.FB_PHASE_A_NEXT_BTN:
            idx = min(len(items) - 1, idx + 1)
        else:
            idx = max(0, idx - 1)
        return {"item_idx": idx,
                "nonce": int((nav or {}).get("nonce") or 0) + 1}

    @app.callback(
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-fb-pa-toc", "instance": ALL}, "n_clicks"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def jump_phase_a_toc(_clicks, nav, session):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update
        # Skip phantom fires from re-mounted toc chips: every chip arrives with
        # n_clicks=0 on body re-render. Without this guard Dash treats the first
        # chip as the trigger and resets item_idx to 0, bouncing the wizard
        # back to item 1 after each Next click.
        if not any(c for c in (_clicks or []) if c):
            return no_update
        item_id = trig.get("instance")
        cls = (session or {}).get("class")
        items = items_for_class(cls)
        if not item_id or not items:
            return no_update
        try:
            idx = next(i for i, it in enumerate(items) if it["id"] == item_id)
        except StopIteration:
            return no_update
        return {"item_idx": idx,
                "nonce": int((nav or {}).get("nonce") or 0) + 1}

    # ── Phase-A wizard: finish → Empirical Evaluation (Phase B) ────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_A_FINISH_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def finish_phase_a(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["view"] = "phase_b"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    # ── Phase tabs: jump between Phase A · Phase B · Result ────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_B_NAV_STORE, "data", allow_duplicate=True),
        Input(ids.FB_TAB_PA_BTN, "n_clicks"),
        Input(ids.FB_TAB_PB_BTN, "n_clicks"),
        Input(ids.FB_TAB_RESULT_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        prevent_initial_call=True,
    )
    def switch_phase_tab(_pa, _pb, _result, session, pa_nav, pb_nav):
        trig = ctx.triggered_id
        mapping = {
            ids.FB_TAB_PA_BTN: "phase_a",
            ids.FB_TAB_PB_BTN: "phase_b",
            ids.FB_TAB_RESULT_BTN: "result",
        }
        target = mapping.get(trig)
        if not target:
            return no_update, no_update, no_update
        # Phantom-mount guard: every body re-render (e.g. a Phase-B prev/next
        # click) re-creates the tab strip with all three buttons at n_clicks=0,
        # and Dash fires this callback with the *first* Input (Phase A) as the
        # trigger — yanking the user from Phase B/Result back to Phase A. A real
        # click always carries n_clicks > 0, so bail when the trigger's count is
        # falsy.
        clicks = {ids.FB_TAB_PA_BTN: _pa,
                  ids.FB_TAB_PB_BTN: _pb,
                  ids.FB_TAB_RESULT_BTN: _result}
        if not clicks.get(trig):
            return no_update, no_update, no_update
        session = dict(session or {})
        # The phase tabs only make sense with an active (miner, class) pair.
        # They render disabled on Overview/Start, but harden against a click
        # arriving with a stale/cleared session.
        if not session.get("miner_id") or not session.get("class"):
            return no_update, no_update, no_update
        if session.get("view") == target:
            return no_update, no_update, no_update
        session["view"] = target
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session, no_update, no_update

    # ── Phase-B wizard: enter / exit / nav / finish / done transitions ─────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_B_EXIT_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def exit_phase_b(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["miner_id"] = None
        session["class"] = None
        session["view"] = "start"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    @app.callback(
        Output(ids.FB_PHASE_B_NAV_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_B_PREV_BTN, "n_clicks"),
        Input(ids.FB_PHASE_B_NEXT_BTN, "n_clicks"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def nav_phase_b(_prev, _next, nav, session):
        trig = ctx.triggered_id
        if trig not in (ids.FB_PHASE_B_PREV_BTN, ids.FB_PHASE_B_NEXT_BTN):
            return no_update
        # Phantom-mount guard (see switch_phase_tab): the nav bar re-mounts with
        # n_clicks=0 on every body re-render; only act on a real click.
        clicks = {ids.FB_PHASE_B_PREV_BTN: _prev, ids.FB_PHASE_B_NEXT_BTN: _next}
        if not clicks.get(trig):
            return no_update
        from flex_compare.fragebogen import phase_b as fb_phase_b
        cls = (session or {}).get("class")
        logs = fb_phase_b.phase_b_logs(cls) if cls else []
        if not logs:
            return no_update
        idx = int((nav or {}).get("log_idx") or 0)
        if trig == ids.FB_PHASE_B_NEXT_BTN:
            idx = min(len(logs) - 1, idx + 1)
        else:
            idx = max(0, idx - 1)
        return {"log_idx": idx,
                "nonce": int((nav or {}).get("nonce") or 0) + 1}

    @app.callback(
        Output(ids.FB_PHASE_B_NAV_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-fb-pb-toc", "instance": ALL}, "n_clicks"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def jump_phase_b_toc(_clicks, nav, session):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update
        # Same phantom-mount guard as jump_phase_a_toc.
        if not any(c for c in (_clicks or []) if c):
            return no_update
        log_path_str = trig.get("instance")  # we stored log path in `instance`
        from flex_compare.fragebogen import phase_b as fb_phase_b
        cls = (session or {}).get("class")
        logs = fb_phase_b.phase_b_logs(cls) if cls else []
        if not log_path_str or not logs:
            return no_update
        try:
            idx = next(i for i, p in enumerate(logs)
                       if str(p) == log_path_str)
        except StopIteration:
            return no_update
        return {"log_idx": idx,
                "nonce": int((nav or {}).get("nonce") or 0) + 1}

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_B_FINISH_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def finish_phase_b(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["view"] = "result"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_B_DONE_TO_OVERVIEW_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def phase_b_done_to_overview(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["view"] = "overview"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    # ── Phase-B: run the currently-shown log on demand ─────────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_PHASE_B_RUN_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def run_phase_b_current(n_clicks, session, nav, app_state_raw):
        if not n_clicks:
            return no_update
        from flex_compare.fragebogen import phase_b as fb_phase_b
        cls = (session or {}).get("class")
        miner_id = (session or {}).get("miner_id")
        if not cls or not miner_id:
            return no_update
        state = _state_from_store(app_state_raw) or FlexState()
        inst = fb_tab._resolve_miner(state, miner_id)
        if inst is None:
            return no_update
        # Run with the same Phase-B config override the view shows, so the
        # cached result lands in the slot the question side looks up.
        inst = fb_tab._with_config_override(inst, (session or {}).get("pb_cfg"))
        logs = fb_phase_b.phase_b_logs(cls)
        idx = int((nav or {}).get("log_idx") or 0)
        if not logs or idx >= len(logs):
            return no_update
        _run_batch(inst, [logs[idx]])
        session = dict(session or {})
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    # ── Phase-B autosave per (log, miner, item) cell ───────────────────────
    @app.callback(
        Output(ids.FB_PHASE_B_SAVE_FEEDBACK, "children", allow_duplicate=True),
        Input({"type": "fc-fb-pb-score", "instance": ALL,
                "log": ALL, "item": ALL}, "value"),
        Input({"type": "fc-fb-pb-note", "instance": ALL,
                "log": ALL, "item": ALL}, "value"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def autosave_phase_b(_scores, _notes, app_state_raw):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update
        kind = trig.get("type")
        if kind not in ("fc-fb-pb-score", "fc-fb-pb-note"):
            return no_update
        instance_id = trig.get("instance")
        log_path_str = trig.get("log")
        item_id = trig.get("item")
        if not instance_id or not log_path_str or not item_id:
            return no_update
        state = _state_from_store(app_state_raw)
        inst = _find_instance(state, instance_id) if state else None
        if inst is None:
            return no_update
        log_path = Path(log_path_str)
        log_id = _safe_log_id(log_path)
        if log_id is None:
            return no_update
        try:
            slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
        except Exception as exc:
            logger.warning("phase_b autosave: slot_id failed for %s: %s",
                           instance_id, exc)
            return no_update

        triggered_value = None
        triggered_field = None
        for entry in ctx.triggered:
            prop_id = entry.get("prop_id", "")
            if not prop_id.endswith(".value"):
                continue
            triggered_value = entry.get("value")
            if "fc-fb-pb-score" in prop_id:
                triggered_field = "score"
            elif "fc-fb-pb-note" in prop_id:
                triggered_field = "note"
            break

        persisted = fb_scores.load_score(log_id, slot, item_id)
        base = persisted or {}
        score = base.get("score")
        note = base.get("note") or ""
        if triggered_field == "score":
            score = _coerce_score(triggered_value)
        elif triggered_field == "note":
            note = triggered_value or ""

        # Skip phantom autosaves fired when the per-log card re-mounts during
        # navigation: nothing to persist if the candidate matches what's already
        # on disk (or an empty/unanswered cell when nothing is persisted yet).
        if persisted is not None:
            if (score == persisted.get("score")
                    and note == (persisted.get("note") or "")):
                return no_update
        else:
            if score is None and not note:
                return no_update

        try:
            fb_scores.save_score(
                log_id=log_id, slot=slot, item_id=item_id,
                score=score, note=note,
                log_stem=log_path.stem,
                instance_id=inst.id,
                instance_label=inst.label or inst.id,
                metric_evidence=_metric_evidence_for(inst, log_id, slot,
                                                      item_id),
            )
        except OSError as exc:
            logger.warning("phase_b autosave: write failed for %s/%s/%s: %s",
                           log_id, slot, item_id, exc)
            return f"⚠ Save failed: {exc}"
        return f"✓ Empirical · {item_id} · {log_path.stem} saved"

    # ── Phase-B: answer tile click → toggle-save the score ─────────────────
    @app.callback(
        Output(ids.FB_PHASE_B_NAV_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_B_SAVE_FEEDBACK, "children", allow_duplicate=True),
        Input({"type": "fc-fb-pb-opt", "instance": ALL,
                "log": ALL, "item": ALL, "score": ALL}, "n_clicks"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def toggle_phase_b_opt(_clicks, nav, app_state_raw):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or trig.get("type") != "fc-fb-pb-opt":
            return no_update, no_update
        # Phantom-mount guard: every tile re-mounts at n_clicks=0 on body
        # re-render; act only on a real click.
        if not any(c for c in (_clicks or []) if c):
            return no_update, no_update
        instance_id = trig.get("instance")
        log_path_str = trig.get("log")
        item_id = trig.get("item")
        clicked = _coerce_score(trig.get("score"))
        if not instance_id or not log_path_str or not item_id or clicked is None:
            return no_update, no_update
        state = _state_from_store(app_state_raw)
        inst = _find_instance(state, instance_id) if state else None
        if inst is None:
            return no_update, no_update
        log_path = Path(log_path_str)
        log_id = _safe_log_id(log_path)
        if log_id is None:
            return no_update, no_update
        try:
            slot = fc_runner.slot_id(fc_runner._type_id(inst), inst.config)
        except Exception as exc:
            logger.warning("phase_b toggle: slot_id failed for %s: %s",
                           instance_id, exc)
            return no_update, no_update

        persisted = fb_scores.load_score(log_id, slot, item_id) or {}
        current = persisted.get("score")
        note = persisted.get("note") or ""
        # Second click on the already-selected tile clears the answer.
        new_score = None if clicked == current else clicked
        try:
            fb_scores.save_score(
                log_id=log_id, slot=slot, item_id=item_id,
                score=new_score, note=note,
                log_stem=log_path.stem,
                instance_id=inst.id,
                instance_label=inst.label or inst.id,
                metric_evidence=_metric_evidence_for(inst, log_id, slot,
                                                      item_id),
            )
        except OSError as exc:
            logger.warning("phase_b toggle: write failed for %s/%s/%s: %s",
                           log_id, slot, item_id, exc)
            return no_update, f"⚠ Save failed: {exc}"
        nav = {**(nav or {}),
               "nonce": int((nav or {}).get("nonce") or 0) + 1}
        verb = "cleared" if new_score is None else "saved"
        return nav, f"✓ Empirical · {item_id} · {log_path.stem} {verb}"

    # ── Phase-B: editable config → session-scoped override ─────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-config", "instance": ALL, "key": ALL}, "value"),
        State({"type": "fc-config", "instance": ALL, "key": ALL}, "id"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def persist_phase_b_config(values, id_list, session):
        # The Phase-B miner is often an ephemeral registry instance absent from
        # state.instances, so the shared _persist_config cannot store its edits.
        # Mirror them into the session so _with_config_override picks them up.
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or trig.get("type") != "fc-config":
            return no_update
        session = session or {}
        if session.get("view") != "phase_b":
            return no_update
        miner_id = session.get("miner_id")
        if not miner_id or trig.get("instance") != miner_id:
            return no_update
        cfg: dict = {}
        for value, idd in zip(values or [], id_list or []):
            if not isinstance(idd, dict):
                continue
            if idd.get("instance") == miner_id and idd.get("key") is not None:
                cfg[idd["key"]] = value
        # Loop guard: re-mount after a re-render replays identical values.
        if cfg == (session.get("pb_cfg") or {}):
            return no_update
        new = dict(session)
        new["pb_cfg"] = cfg
        new["nonce"] = int(session.get("nonce") or 0) + 1
        return new

    # ── Overview: open / close + cell click → re-bewerten ──────────────────
    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_OVERVIEW_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def open_overview(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["view"] = "overview"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_OVERVIEW_BACK_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def close_overview(n_clicks, session):
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["miner_id"] = None
        session["class"] = None
        session["view"] = "start"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.FB_ADD_MINER_BTN, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def add_miner(n_clicks, session):
        """"+ Add miner" on the Overview opens the start picker so any
        registered miner (scored or not) can be scored on a class."""
        if not n_clicks:
            return no_update
        session = dict(session or {})
        session["miner_id"] = None
        session["class"] = None
        session["view"] = "start"
        session["nonce"] = int(session.get("nonce") or 0) + 1
        return session

    @app.callback(
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_B_NAV_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-fb-ov-action", "instance": ALL,
                "cls": ALL, "action": ALL}, "n_clicks"),
        State(ids.FB_SESSION_STORE, "data"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        State(ids.FB_PHASE_B_NAV_STORE, "data"),
        prevent_initial_call=True,
    )
    def overview_action(_clicks, session, pa_nav, pb_nav):
        """Navigate for a (miner, class) chosen from the overview / result page.

        ``action`` = ``result`` → the result page (Fit + T/E breakdown);
        ``pa``/``edit`` → Phase A wizard (same editable surface);
        ``pb`` → Phase B wizard. Resets the relevant nav cursor to the start.
        """
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update, no_update, no_update
        # Phantom-mount guard (see switch_phase_tab): act only on a real click.
        if not any(c for c in (_clicks or []) if c):
            return no_update, no_update, no_update
        miner_id = trig.get("instance")
        cls = trig.get("cls")
        action = trig.get("action")
        if not miner_id or not cls:
            return no_update, no_update, no_update
        session = dict(session or {})
        session["miner_id"] = miner_id
        session["class"] = cls
        session["ov_open"] = None
        session["pb_cfg"] = None          # drop any prior miner's config override
        session["nonce"] = int(session.get("nonce") or 0) + 1
        if action == "result":
            session["view"] = "result"
            return session, no_update, no_update
        session["view"] = "phase_b" if action == "pb" else "phase_a"
        if action == "pb":
            pa_out = no_update
            pb_out = {"log_idx": 0,
                      "nonce": int((pb_nav or {}).get("nonce") or 0) + 1}
        else:
            pa_out = {"item_idx": 0,
                      "nonce": int((pa_nav or {}).get("nonce") or 0) + 1}
            pb_out = no_update
        return session, pa_out, pb_out

    # ── Phase-A survey: autosave per (miner, item) cell ────────────────────
    @app.callback(
        Output(ids.FB_PHASE_A_SAVE_FEEDBACK, "children",
               allow_duplicate=True),
        Input({"type": "fc-fb-pa-score", "instance": ALL,
                "item": ALL}, "value"),
        Input({"type": "fc-fb-pa-note", "instance": ALL,
                "item": ALL}, "value"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def autosave_phase_a(_scores, _notes, session):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update
        miner_id = trig.get("instance")
        item_id = trig.get("item")
        kind = trig.get("type")
        if not miner_id or not item_id or kind not in (
                "fc-fb-pa-score", "fc-fb-pa-note"):
            return no_update
        cls = (session or {}).get("class")
        if not cls:
            return no_update

        triggered_value = None
        triggered_field = None
        for entry in ctx.triggered:
            prop_id = entry.get("prop_id", "")
            if not prop_id.endswith(".value"):
                continue
            triggered_value = entry.get("value")
            if "fc-fb-pa-score" in prop_id:
                triggered_field = "score"
            elif "fc-fb-pa-note" in prop_id:
                triggered_field = "note"
            break

        persisted = fb_pa_answers.load_answer(cls, miner_id, item_id)
        base = persisted or _seed_for(cls, miner_id, item_id) or {}
        score = base.get("score")
        note = (base.get("note") or "")
        if triggered_field == "score":
            score = _coerce_pa_score(triggered_value)
        elif triggered_field == "note":
            note = triggered_value or ""

        # Skip phantom autosaves fired on (re-)mount of the item card: nothing
        # has actually changed if the candidate matches what's already on disk
        # (or, when no answer is persisted yet, the YAML seed).
        if persisted is not None:
            if (score == persisted.get("score")
                    and note == (persisted.get("note") or "")):
                return no_update
        else:
            seed = _seed_for(cls, miner_id, item_id) or {}
            if (score == seed.get("score")
                    and note == (seed.get("note") or "")):
                return no_update

        try:
            fb_pa_answers.save_answer(cls=cls, miner_id=miner_id,
                                       item_id=item_id, score=score,
                                       note=note)
        except OSError as exc:
            logger.warning("phase_a autosave: write failed for %s/%s/%s: %s",
                           cls, miner_id, item_id, exc)
            return f"⚠ Save failed: {exc}"
        return f"✓ Theoretical · {item_id} · {miner_id} saved"

    # ── Phase-A: answer tile click → toggle-save the score ─────────────────
    @app.callback(
        Output(ids.FB_PHASE_A_NAV_STORE, "data", allow_duplicate=True),
        Output(ids.FB_PHASE_A_SAVE_FEEDBACK, "children", allow_duplicate=True),
        Input({"type": "fc-fb-pa-opt", "instance": ALL,
                "item": ALL, "score": ALL}, "n_clicks"),
        State(ids.FB_PHASE_A_NAV_STORE, "data"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def toggle_phase_a_opt(_clicks, nav, session):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or trig.get("type") != "fc-fb-pa-opt":
            return no_update, no_update
        # Phantom-mount guard: tiles re-mount at n_clicks=0 on body re-render.
        if not any(c for c in (_clicks or []) if c):
            return no_update, no_update
        miner_id = trig.get("instance")
        item_id = trig.get("item")
        clicked = _coerce_pa_score(trig.get("score"))
        cls = (session or {}).get("class")
        if not miner_id or not item_id or clicked is None or not cls:
            return no_update, no_update

        persisted = fb_pa_answers.load_answer(cls, miner_id, item_id)
        base = persisted or _seed_for(cls, miner_id, item_id) or {}
        current = base.get("score")
        note = base.get("note") or ""
        # Second click on the already-selected tile clears the answer.
        new_score = None if clicked == current else clicked
        try:
            fb_pa_answers.save_answer(cls=cls, miner_id=miner_id,
                                       item_id=item_id, score=new_score,
                                       note=note)
        except OSError as exc:
            logger.warning("phase_a toggle: write failed for %s/%s/%s: %s",
                           cls, miner_id, item_id, exc)
            return no_update, f"⚠ Save failed: {exc}"
        nav = {**(nav or {}),
               "nonce": int((nav or {}).get("nonce") or 0) + 1}
        verb = "cleared" if new_score is None else "saved"
        return nav, f"✓ Theoretical · {item_id} · {miner_id} {verb}"


# ── Internal helpers ────────────────────────────────────────────────────────


def _coerce_pa_score(value) -> Optional[int]:
    """Phase-A radio carries -1 for "n/a"; turn that back into ``None``."""
    if value is None or value == "":
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return None if v == -1 else v


def _seed_for(cls: str, miner_id: str,
              item_id: str) -> Optional[dict]:
    """YAML-seed of ``(cls, miner_id, item_id)`` reshaped like an answer."""
    item = get_item(item_id)
    if item is None or item.get("class") != cls:
        return None
    seed = (item.get("phase_a") or {}).get(miner_id) or {}
    if not seed:
        return None
    return {"score": seed.get("score"), "note": seed.get("note", "")}


def _state_from_store(raw) -> Optional[FlexState]:
    if not isinstance(raw, dict):
        return None
    try:
        return fc_state.FlexState.from_jsonable(raw)
    except Exception as exc:
        logger.warning("state rehydrate failed: %s", exc)
        return None


def _find_instance(state: Optional[FlexState],
                   instance_id: str) -> Optional[MinerInstance]:
    """Resolve a Tab-3 miner id to an instance.

    Honour a configured Tab-2 instance first (back-compat), then fall back to a
    registry spec id — the start dropdown and overview now emit spec ids, and
    the ephemeral instance is what makes autosave/runs work for miners that were
    never added in Tab 2.
    """
    if state is not None and instance_id:
        for inst in state.instances:
            if inst.id == instance_id:
                return inst
    return fb_tab._ephemeral_instance_for_spec(instance_id) if instance_id else None


def _safe_log_id(log_path: Path) -> Optional[str]:
    try:
        return result_cache.compute_log_id(Path(log_path))
    except Exception as exc:
        logger.warning("compute_log_id failed for %s: %s", log_path, exc)
        return None


def _coerce_score(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metric_evidence_for(inst: MinerInstance, log_id: str, slot: str,
                         item_id: str) -> dict:
    item = get_item(item_id)
    if item is None:
        return {}
    keys = item.get("metric_keys") or ()
    if not keys:
        return {}
    entry = result_cache.lookup(slot, log_id)
    if entry is None:
        return {}
    try:
        result = result_cache.rehydrate(entry)
    except Exception:
        return {}
    metrics = fc_runner.extract_metrics(inst, result)
    return {k: metrics.get(k) for k in keys}


def _run_batch(inst: MinerInstance, log_paths: list[Path]) -> tuple[int, int]:
    """Run ``inst`` against each log sequentially. Returns ``(successes, failures)``.

    Errors are logged but do not abort the batch — the user can retry the
    failing log via the per-log ▶ Run button.
    """
    successes = 0
    failures = 0
    for log_path in log_paths:
        try:
            outcome = fc_runner.run_instance(inst, log_path, force=False)
        except Exception as exc:
            logger.warning("run_instance threw for %s on %s: %s",
                           inst.id, log_path.name, exc)
            failures += 1
            continue
        if outcome.status == "ok" and outcome.result is not None:
            successes += 1
        else:
            failures += 1
            logger.warning("run failed for %s on %s — status=%s · %s",
                           inst.id, log_path.name, outcome.status,
                           outcome.error_summary)
    return successes, failures
