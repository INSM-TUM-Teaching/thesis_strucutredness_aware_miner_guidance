"""Run callbacks: per-instance + Run-all + comparison strip + cancel-all.

Concurrency cap (P2): all runs go through a single
``concurrent.futures.ThreadPoolExecutor`` whose width is taken from
``FLEX_RUN_CONCURRENCY`` (default 3). Excess submissions wait their turn —
cards show ``● Queued`` until the executor picks them up.

Cancellation (P4): every job carries a ``cancel_requested`` flag the
custom-exec subprocess loop polls once a second; for native-adapter jobs,
the flag becomes a soft no-op (Python adapters don't expose hooks). The
runner stores the live ``subprocess.Popen`` handle, so ``cancel_all()``
also terminates the foreign process directly (no orphan JVMs).
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dash import ALL, Input, MATCH, Output, State, ctx, html, no_update

from flex_compare import state as fc_state
from flex_compare.internal.shared.cache import result_cache
from flex_compare.runner import (
    RunOutcome, _type_id, extract_metrics, run_instance, slot_id,
)
from flex_compare.state import MinerInstance
from flex_compare.ui import ids
from flex_compare.ui.components.result_view import (
    render_error_view, render_result_view,
)


logger = logging.getLogger(__name__)


# ── Bounded executor (P2) ────────────────────────────────────────────────────
_MAX_CONCURRENCY = max(1, int(os.environ.get("FLEX_RUN_CONCURRENCY", "3")))
_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_CONCURRENCY, thread_name_prefix="fc-run"
)


@dataclass
class JobState:
    queued: bool = False
    running: bool = False
    outcome: Optional[RunOutcome] = None
    started_at: float = 0.0
    queued_at: float = 0.0
    cancel_requested: bool = False
    popen: Optional[subprocess.Popen] = None
    future: Optional[Future] = field(default=None, repr=False)


_JOBS: dict[str, JobState] = {}
_JOBS_LOCK = threading.Lock()


# ── Public helpers ───────────────────────────────────────────────────────────
def any_job_active() -> bool:
    with _JOBS_LOCK:
        return any(j.queued or j.running for j in _JOBS.values())


def cancel_all() -> int:
    """Best-effort cancel of every queued/running job. Returns count requested."""
    count = 0
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if not (job.queued or job.running):
                continue
            job.cancel_requested = True
            count += 1
            # Stop unstarted futures cheaply.
            if job.future is not None and not job.future.done():
                job.future.cancel()
            # Terminate live foreign subprocess so the JVM doesn't orphan.
            popen = job.popen
            if popen is not None and popen.poll() is None:
                try:
                    popen.terminate()
                except Exception:
                    logger.exception("popen.terminate() failed")
    return count


def clear_finished() -> None:
    with _JOBS_LOCK:
        for inst_id in list(_JOBS.keys()):
            j = _JOBS[inst_id]
            if not (j.queued or j.running):
                _JOBS.pop(inst_id, None)


def _cache_payload_for(instance: MinerInstance, log_path: str) -> dict | None:
    """Look up the on-disk cache for ``(instance, log_path)`` and return the
    result-store payload (same shape ``_tick`` writes) or ``None`` on miss."""
    if not log_path:
        return None
    try:
        p = Path(log_path)
        if not p.is_file():
            return None
        slot = slot_id(_type_id(instance), instance.config)
        log_id = result_cache.compute_log_id(p)
        hit = result_cache.lookup(slot, log_id)
        if hit is None:
            return None
        result = result_cache.rehydrate(hit)
    except Exception as exc:
        logger.warning("cache lookup failed for %s: %s", instance.id, exc)
        return None
    return {
        "status": "ok",
        "result": result,
        "error_summary": None,
        "command": None,
        "exec_log_path": None,
        "cache_hit": True,
    }


def _kick_job(instance: MinerInstance, log_path: str, *, force: bool = False) -> None:
    job = _JOBS.setdefault(instance.id, JobState())
    with _JOBS_LOCK:
        if job.queued or job.running:
            return
        job.queued = True
        job.queued_at = time.monotonic()
        job.outcome = None
        job.cancel_requested = False
        job.popen = None

    def _on_started(popen: subprocess.Popen) -> None:
        with _JOBS_LOCK:
            job.popen = popen

    def _cancel_check() -> bool:
        return job.cancel_requested

    def _runner():
        with _JOBS_LOCK:
            if job.cancel_requested:
                job.queued = False
                job.outcome = RunOutcome(
                    status="cancelled", result=None,
                    error_summary="cancelled before start",
                )
                return
            job.queued = False
            job.running = True
            job.started_at = time.monotonic()
        try:
            outcome = run_instance(
                instance, Path(log_path),
                force=force,
                on_started=_on_started, cancel_check=_cancel_check,
            )
        except Exception as exc:
            logger.exception("uncaught runner exception")
            outcome = RunOutcome(
                status="parse_error", result=None,
                error_summary=f"{type(exc).__name__}: {exc}",
            )
        with _JOBS_LOCK:
            job.running = False
            job.outcome = outcome
            job.popen = None

    job.future = _EXECUTOR.submit(_runner)


# ── Status pill rendering — uses comparison_app's pm-pill classes. ───────────
def _status_pill(text: str, variant: str) -> html.Span:
    """variant ∈ {idle, ready, running, error} mapped to pm-pill-* classes
    defined in assets/theme.css."""
    return html.Span(text, className=f"pm-pill pm-pill-{variant}")


_RUNNING_BANNER_STYLE = {
    "display": "block",
    "marginTop": "4px",
    "marginBottom": "8px",
    "padding": "8px 12px",
    "background": "var(--bg-elevated, #eef3fb)",
    "border": "1px solid var(--border-default, #cfd8e3)",
    "borderRadius": "6px",
    "fontSize": "12px",
    "fontWeight": "600",
    "color": "var(--color-primary, #1f6feb)",
}


def _running_banner_text(job: JobState | None) -> str:
    if job is None:
        return ""
    if job.queued:
        return "⏸  Queued — waiting for a runner slot…"
    if job.running:
        return "⏳  Running…"
    return ""


def _status_for_job(job: JobState | None) -> html.Span:
    if job is None:
        return _status_pill("● Ready", "idle")
    if job.queued:
        return _status_pill("⏸ Queued", "idle")
    if job.running:
        return _status_pill("⏳ Running…", "running")
    if job.outcome is None:
        return _status_pill("● Ready", "idle")
    if job.outcome.status == "ok":
        return _status_pill(
            "✓ Done" + (" (cached)" if job.outcome.cache_hit else ""),
            "ready",
        )
    if job.outcome.status == "cancelled":
        return _status_pill("⊘ Cancelled", "idle")
    return _status_pill(f"⚠ {job.outcome.status}", "error")


# ── Comparison strip ─────────────────────────────────────────────────────────
def _comparison_strip(
    app_state: dict | None,
    payloads: list | None = None,
    id_list: list | None = None,
) -> html.Div:
    if not app_state:
        return html.Div()
    state = fc_state.FlexState.from_jsonable(app_state)
    if not state.instances:
        return html.Div()

    # Prefer the per-card payloads streamed by `_tick`/`_hydrate_from_cache`
    # so the strip stays in sync with what each card shows (including cached
    # results loaded on log change, when `_JOBS` is empty).
    payload_by_inst: dict[str, dict] = {}
    for idd, payload in zip(id_list or [], payloads or []):
        if not isinstance(idd, dict) or not isinstance(payload, dict):
            continue
        inst_id = idd.get("instance")
        if inst_id and payload.get("status") == "ok" and payload.get("result"):
            payload_by_inst[inst_id] = payload

    rows: list[tuple[MinerInstance, dict, bool]] = []
    for inst in state.instances:
        result = None
        payload = payload_by_inst.get(inst.id)
        if payload:
            result = payload.get("result")
        else:
            job = _JOBS.get(inst.id)
            if job and job.outcome and job.outcome.status == "ok" and job.outcome.result:
                result = job.outcome.result
        if not result:
            continue
        metrics = extract_metrics(inst, result)
        imported = bool(metrics.pop("_imported", False))
        rows.append((inst, metrics, imported))

    if not rows:
        return html.Div()

    metric_keys = [
        ("BQ", "replay_fitness", "Replay fitness"),
        ("BQ", "etc_precision", "ETC precision"),
        ("BQ", "non_vacuous_satisfaction_rate", "Non-vac. sat. rate"),
        ("BQ", "vacuity_rate", "Vacuity rate"),
        ("IN", "extended_cardoso_cfc", "CFC"),
        ("IN", "process_tree_depth", "Tree depth"),
        ("IN", "mean_fan_out", "Mean fan-out"),
        ("IN", "tau_ratio", "τ-ratio"),
        ("IN", "constraint_density", "Constraint density"),
        ("IN", "constraint_variability", "Constraint variability"),
        ("SF", "flower_detected", "Flower detected"),
        ("SF", "soundness_passed", "Sound"),
    ]

    def _fmt(value, imported):
        if value is None:
            return "n/a (imported)" if imported else "—"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    head_cells = [html.Th("Metric", style={"textAlign": "left", "padding": "6px 8px"})]
    for inst, _, _ in rows:
        head_cells.append(html.Th(inst.label, style={"padding": "6px 8px"}))

    body_rows: list = []
    last_group = None
    for group, key, label in metric_keys:
        if all(metrics.get(key) is None for _, metrics, _ in rows):
            continue
        if group != last_group:
            body_rows.append(html.Tr(
                html.Td(group, colSpan=len(head_cells), style={
                    "padding": "8px 8px 4px", "fontSize": "10px",
                    "color": "var(--text-muted, #888)", "fontWeight": "600",
                    "textTransform": "uppercase",
                }),
            ))
            last_group = group
        cells = [html.Td(label, style={"padding": "4px 8px", "fontSize": "12px"})]
        for _, metrics, imported in rows:
            cells.append(html.Td(_fmt(metrics.get(key), imported),
                                  style={"padding": "4px 8px", "fontSize": "12px",
                                         "fontFamily": "monospace"}))
        body_rows.append(html.Tr(cells))

    return html.Div(
        children=[
            html.Div("Comparison", style={
                "fontWeight": "700", "fontSize": "13px", "marginBottom": "4px",
            }),
            html.Div(
                "Numbers from miners using different paradigms (procedural / "
                "declarative / hybrid) are not directly comparable — RC3 caveat.",
                style={"fontSize": "11px", "color": "var(--text-muted,#666)",
                       "marginBottom": "10px", "fontStyle": "italic"},
            ),
            html.Table(
                children=[html.Thead(html.Tr(head_cells)), html.Tbody(body_rows)],
                style={"width": "100%", "borderCollapse": "collapse",
                       "background": "white",
                       "border": "1px solid var(--border-default,#e5e7eb)",
                       "borderRadius": "8px"},
            ),
        ],
    )


# ── Callback registration ────────────────────────────────────────────────────
def register(app):
    # ── Per-instance run / rerun button ──
    # One blue button per card: it behaves as a fresh "Run" when no result
    # is on screen, and as a cache-bypassing "Rerun" once a result exists
    # (force=True). The old model stays visible during the rerun — the
    # result-store is only overwritten when the new run completes.
    @app.callback(
        Output(ids.TICK_INTERVAL, "disabled", allow_duplicate=True),
        Input({"type": "fc-run-btn", "instance": ALL}, "n_clicks"),
        State({"type": "fc-run-btn", "instance": ALL}, "id"),
        State({"type": "fc-result-store", "instance": ALL}, "data"),
        State({"type": "fc-result-store", "instance": ALL}, "id"),
        State(ids.APP_STATE_STORE, "data"),
        State(ids.LOG_PATH_STORE, "data"),
        prevent_initial_call=True,
    )
    def _on_run_click(clicks, btn_ids, store_data, store_ids, app_state, log_path):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or triggered.get("type") != "fc-run-btn":
            return no_update
        if not any((c or 0) > 0 for c in (clicks or [])):
            return no_update
        if not log_path or not app_state:
            return no_update

        instance_id = triggered.get("instance")
        state = fc_state.FlexState.from_jsonable(app_state)
        instance = fc_state.find_instance(state, instance_id)
        if instance is None:
            return no_update

        # Has this instance already produced a result? If so, treat the
        # click as a Rerun and bypass the on-disk cache.
        has_result = False
        for idd, data in zip(store_ids or [], store_data or []):
            if isinstance(idd, dict) and idd.get("instance") == instance_id:
                if isinstance(data, dict) and data.get("status") == "ok" and data.get("result"):
                    has_result = True
                break
        _kick_job(instance, log_path, force=has_result)
        return False  # enable the tick interval

    # ── Run-button label: "▶ Run" → "↻ Rerun" once a result exists ──
    @app.callback(
        Output({"type": "fc-run-btn", "instance": MATCH}, "children"),
        Input({"type": "fc-result-store", "instance": MATCH}, "data"),
        prevent_initial_call=False,
    )
    def _run_button_label(payload):
        if isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("result"):
            return "↻  Rerun"
        return "▶  Run"

    # ── Run-all ──
    @app.callback(
        Output(ids.TICK_INTERVAL, "disabled", allow_duplicate=True),
        Input(ids.RUN_ALL_BTN, "n_clicks"),
        State(ids.APP_STATE_STORE, "data"),
        State(ids.LOG_PATH_STORE, "data"),
        prevent_initial_call=True,
    )
    def _on_run_all(n, app_state, log_path):
        if not n or not log_path or not app_state:
            return no_update
        state = fc_state.FlexState.from_jsonable(app_state)
        for inst in state.instances:
            _kick_job(inst, log_path)
        return False

    # ── Cancel-all ──
    @app.callback(
        Output(ids.TICK_INTERVAL, "disabled", allow_duplicate=True),
        Input(ids.CANCEL_ALL_BTN, "n_clicks"),
        prevent_initial_call=True,
    )
    def _on_cancel_all(n):
        if not n:
            return no_update
        cancel_all()
        return False  # keep tick alive so cards refresh to cancelled state

    # ── Tick: poll all jobs, push status + result-store updates ──
    @app.callback(
        Output({"type": "fc-result-store", "instance": ALL}, "data",
               allow_duplicate=True),
        Output({"type": "fc-status", "instance": ALL}, "children",
               allow_duplicate=True),
        Output({"type": "fc-running-banner", "instance": ALL}, "children",
               allow_duplicate=True),
        Output({"type": "fc-running-banner", "instance": ALL}, "style",
               allow_duplicate=True),
        Output(ids.TICK_INTERVAL, "disabled", allow_duplicate=True),
        Output("fc-active-jobs-flag", "data"),
        Input(ids.TICK_INTERVAL, "n_intervals"),
        State({"type": "fc-result-store", "instance": ALL}, "id"),
        prevent_initial_call=True,
    )
    def _tick(_n, id_list):
        data_out: list[Any] = []
        status_out: list[Any] = []
        banner_children: list[Any] = []
        banner_styles: list[Any] = []
        any_active = False
        for idd in id_list or []:
            inst_id = idd.get("instance")
            job = _JOBS.get(inst_id)
            active = bool(job and (job.queued or job.running))
            if active:
                any_active = True
            status_out.append(_status_for_job(job))
            banner_children.append(
                _running_banner_text(job) if active else ""
            )
            banner_styles.append(
                _RUNNING_BANNER_STYLE if active else {"display": "none"}
            )
            if job and job.outcome:
                outcome = job.outcome
                data_out.append({
                    "status": outcome.status,
                    "result": outcome.result,
                    "error_summary": outcome.error_summary,
                    "command": outcome.command,
                    "exec_log_path": str(outcome.exec_log_path)
                        if outcome.exec_log_path else None,
                    "cache_hit": outcome.cache_hit,
                })
            else:
                data_out.append(no_update)
        return (data_out, status_out, banner_children, banner_styles,
                not any_active, any_active)

    # ── Per-card result rendering ──
    # ``prevent_initial_call=False`` so the card repaints on initial page
    # load once `_hydrate_from_cache` populates the result-store from disk
    # (no need to click anything in Tab 2 first).
    @app.callback(
        Output({"type": "fc-result-view", "instance": MATCH}, "children"),
        Input({"type": "fc-result-store", "instance": MATCH}, "data"),
        State({"type": "fc-result-view", "instance": MATCH}, "id"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=False,
    )
    def _render_result(payload, idd, app_state):
        if not payload or not app_state:
            return no_update
        inst_id = idd.get("instance")
        state = fc_state.FlexState.from_jsonable(app_state)
        instance = fc_state.find_instance(state, inst_id)
        if instance is None:
            return html.Div("(removed)")

        status = payload.get("status")
        if status == "ok" and payload.get("result"):
            return render_result_view(instance, payload["result"],
                                       cache_hit=bool(payload.get("cache_hit")))
        if status == "cancelled":
            return html.Div("(cancelled)",
                            style={"fontSize": "12px",
                                   "color": "var(--text-muted, #888)"})
        return render_error_view(
            payload.get("error_summary") or "(no error info)",
            Path(payload["exec_log_path"]) if payload.get("exec_log_path") else None,
            payload.get("command"),
        )

    # ── Comparison strip — refresh whenever any result-store updates ──
    @app.callback(
        Output(ids.COMPARISON_STRIP, "children"),
        Input({"type": "fc-result-store", "instance": ALL}, "data"),
        State({"type": "fc-result-store", "instance": ALL}, "id"),
        State(ids.APP_STATE_STORE, "data"),
    )
    def _render_strip(payloads, id_list, app_state):
        return _comparison_strip(app_state, payloads=payloads, id_list=id_list)

    # ── Hydrate result-stores from on-disk cache ──
    # Fires on initial render and whenever the log changes (Tab 1 or Tab 2
    # dropdown) or the instance list changes. Without this, Tab 2 starts
    # empty and the user has to click something to repaint cached results.
    # ``allow_duplicate=True`` because ``_tick`` writes the same outputs.
    @app.callback(
        Output({"type": "fc-result-store", "instance": ALL}, "data",
               allow_duplicate=True),
        Output({"type": "fc-status", "instance": ALL}, "children",
               allow_duplicate=True),
        Input(ids.LOG_PATH_STORE, "data"),
        Input(ids.APP_STATE_STORE, "data"),
        State({"type": "fc-result-store", "instance": ALL}, "id"),
        prevent_initial_call="initial_duplicate",
    )
    def _hydrate_from_cache(log_path, app_state, id_list):
        n = len(id_list or [])
        if not n:
            return [], []
        if not app_state:
            return [no_update] * n, [no_update] * n

        # If the log changed and no jobs are running, drop stale per-instance
        # job state so the comparison strip + status pills reflect the new
        # log (the LOG_CHANGE_GUARD blocks switches while jobs are in
        # flight, so this can only land on the safe path).
        triggered = ctx.triggered_id
        if triggered == ids.LOG_PATH_STORE and not any_job_active():
            with _JOBS_LOCK:
                _JOBS.clear()

        state = fc_state.FlexState.from_jsonable(app_state)
        by_id = {i.id: i for i in state.instances}

        data_out: list[Any] = []
        status_out: list[Any] = []
        for idd in id_list or []:
            inst_id = idd.get("instance")
            instance = by_id.get(inst_id)
            if instance is None:
                data_out.append(no_update)
                status_out.append(no_update)
                continue
            # Don't clobber a running/queued job's state.
            job = _JOBS.get(inst_id)
            if job and (job.queued or job.running):
                data_out.append(no_update)
                status_out.append(no_update)
                continue
            payload = _cache_payload_for(instance, log_path)
            if payload is None:
                data_out.append(None)
                status_out.append(_status_pill("● Ready", "idle"))
            else:
                data_out.append(payload)
                status_out.append(_status_pill("✓ Done (cached)", "ready"))
        return data_out, status_out
