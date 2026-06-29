"""Static IDs + pattern-matching ID helpers for the flex_compare app.

Pattern-matched component IDs are built through :func:`fc_id` and queried with
:func:`fc_match`/:func:`fc_all` so a typo in a role name fails loudly as a
``KeyError`` (not silently as a non-firing callback — Dash's worst debugging
experience).
"""
from __future__ import annotations

from typing import Any

from dash.dependencies import ALL, MATCH


# ── Static IDs (single-instance components) ──────────────────────────────────
URL_BAR = "fc-url"
APP_STATE_STORE = "fc-app-state"               # mirrors the on-disk FlexState
LOG_PATH_STORE = "fc-log-path-store"           # currently selected log path
ARM_RESULT_STORE = "fc-arm-result-store"
RUN_TRIGGER_STORE = "fc-run-trigger-store"     # (instance_id, run_nonce) tuples
TICK_INTERVAL = "fc-tick"
SAVE_FEEDBACK = "fc-save-feedback"

# Tabs
TABS = "fc-tabs"
TAB_LOG = "fc-tab-log"
TAB_MINERS = "fc-tab-miners"
TAB_FRAGEBOGEN = "fc-tab-fragebogen"

# Tab 3 — Fragebogen Phase 2
FB_SESSION_STORE = "fc-fb-session-store"   # {"miner_id": str|None, "class": str|None, "nonce": int}
FB_BODY = "fc-fb-body"
FB_MINER_SELECT = "fc-fb-miner-select"
FB_CLASS_SELECT = "fc-fb-class-select"
FB_START_BTN = "fc-fb-start-btn"
FB_RESET_BTN = "fc-fb-reset-btn"
FB_RUN_ALL_BTN = "fc-fb-run-all-btn"
FB_RUN_STATUS = "fc-fb-run-status"
FB_RELOAD_BTN = "fc-fb-reload-btn"

# Tab 3 — Phase-A survey wizard
FB_PHASE_A_START_BTN = "fc-fb-pa-start-btn"
FB_PHASE_A_EXIT_BTN = "fc-fb-pa-exit-btn"
FB_PHASE_A_PREV_BTN = "fc-fb-pa-prev-btn"
FB_PHASE_A_NEXT_BTN = "fc-fb-pa-next-btn"
FB_PHASE_A_FINISH_BTN = "fc-fb-pa-finish-btn"   # → result view
FB_PHASE_A_NAV_STORE = "fc-fb-pa-nav-store"    # {"item_idx": int, "nonce": int}
FB_PHASE_A_SAVE_FEEDBACK = "fc-fb-pa-save-feedback"

# Tab 3 — Phase-B survey wizard
FB_PHASE_B_NAV_STORE = "fc-fb-pb-nav-store"    # {"log_idx": int, "nonce": int}
FB_PHASE_B_PREV_BTN = "fc-fb-pb-prev-btn"
FB_PHASE_B_NEXT_BTN = "fc-fb-pb-next-btn"
FB_PHASE_B_FINISH_BTN = "fc-fb-pb-finish-btn"
FB_PHASE_B_EXIT_BTN = "fc-fb-pb-exit-btn"
FB_PHASE_B_RUN_BTN = "fc-fb-pb-run-btn"
FB_PHASE_B_DONE_TO_OVERVIEW_BTN = "fc-fb-pb-done-to-ov-btn"   # used in result view
FB_PHASE_B_SAVE_FEEDBACK = "fc-fb-pb-save-feedback"

# Tab 3 — Overview
FB_OVERVIEW_BTN = "fc-fb-overview-btn"
FB_OVERVIEW_BACK_BTN = "fc-fb-overview-back-btn"
FB_ADD_MINER_BTN = "fc-fb-add-miner-btn"

# Tab 3 — Phase tabs (free navigation between Phase A · Phase B · Result)
FB_TAB_PA_BTN = "fc-fb-tab-pa-btn"
FB_TAB_PB_BTN = "fc-fb-tab-pb-btn"
FB_TAB_RESULT_BTN = "fc-fb-tab-result-btn"

# Tab 1
LOG_UPLOAD = "fc-log-upload"
LOG_SELECT = "fc-log-select"
LOG_STATS = "fc-log-stats"
ARM_RUN_BTN = "fc-arm-run-btn"
ARM_TEMPORAL_SLIDER = "fc-arm-temporal"
ARM_EXISTENTIAL_SLIDER = "fc-arm-existential"
ARM_OUTPUT = "fc-arm-output"
CLASSIFICATION_BADGE = "fc-classification-badge"

# Tab 2
ADD_MINER_BTN = "fc-add-miner-btn"
RUN_ALL_BTN = "fc-run-all-btn"
CANCEL_ALL_BTN = "fc-cancel-all-btn"
MINER_CARDS_CONTAINER = "fc-miner-cards"
COMPARISON_STRIP = "fc-comparison-strip"
ACTIVE_JOBS_FLAG = "fc-active-jobs-flag"
LOG_CHANGE_GUARD = "fc-log-change-guard"
MINER_TAB_LOG_SELECT = "fc-miner-tab-log-select"

# Add-Miner modal
ADD_MODAL = "fc-add-modal"
ADD_MODAL_TYPE = "fc-add-modal-type"
ADD_MODAL_LABEL = "fc-add-modal-label"
ADD_MODAL_INLINE_PARADIGM = "fc-add-modal-inline-paradigm"
ADD_MODAL_INLINE_RUNNER_KIND = "fc-add-modal-inline-runner-kind"
ADD_MODAL_INLINE_ENTRY_POINT = "fc-add-modal-inline-entry-point"
ADD_MODAL_INLINE_COMMAND = "fc-add-modal-inline-command"
ADD_MODAL_INLINE_OUTPUT_FORMAT = "fc-add-modal-inline-output-format"
ADD_MODAL_INLINE_OUTPUT_PATTERN = "fc-add-modal-inline-output-pattern"
ADD_MODAL_INLINE_CONFIG = "fc-add-modal-inline-config"     # JSON textarea
ADD_MODAL_CONFIRM = "fc-add-modal-confirm"
ADD_MODAL_CANCEL = "fc-add-modal-cancel"
ADD_MODAL_FEEDBACK = "fc-add-modal-feedback"


# ── Dynamic IDs (one component per miner instance) ───────────────────────────
def fc_id(role: str, instance: str, **extra: Any) -> dict:
    """Concrete pattern-matching component ID for a single instance."""
    return {"type": f"fc-{role}", "instance": instance, **extra}


def fc_match(role: str, **extra: Any) -> dict:
    """Callback selector matching exactly one instance via Dash MATCH."""
    return {"type": f"fc-{role}", "instance": MATCH, **extra}


def fc_all(role: str, **extra: Any) -> dict:
    """Callback selector matching every instance via Dash ALL."""
    return {"type": f"fc-{role}", "instance": ALL, **extra}


# Canon roles — Tippfehler in this list explode at import time, not at runtime.
ROLES = (
    "miner-card",
    "miner-card-header",
    "run-btn",
    "remove-btn",
    "status",
    "config",          # extra key: "key"
    "result-store",
    "result-view",
    "running-banner",
    # Fragebogen Tab 3 — extra keys: "log" (path string) + "item" (questionnaire item id)
    "fb-score",
    "fb-note",
    # Per-log "▶ Run" button — extra key: "log" (path string)
    "fb-run-single",
    # Phase-A survey wizard — extra keys: "miner" (canonical id) + "item" (questionnaire item id)
    "fb-pa-score",
    "fb-pa-note",
    # Phase-A answer tiles (click-to-toggle) — extra keys: "item" + "score"
    "fb-pa-opt",
    # Phase-A TOC chips — extra key: "item" (questionnaire item id)
    "fb-pa-toc",
    # Phase-B survey — extra keys: "log" (path string) + "item" (B-prefixed id)
    "fb-pb-score",
    "fb-pb-note",
    # Phase-B answer tiles (click-to-toggle) — extra keys: "log" + "item" + "score"
    "fb-pb-opt",
    # Phase-B per-log TOC chips — extra key: "log" (path string)
    "fb-pb-toc",
    # Overview/result action buttons — extra keys: "cls" + "action"
    # ("result" | "pa" | "pb" | "edit")
    "fb-ov-action",
)
