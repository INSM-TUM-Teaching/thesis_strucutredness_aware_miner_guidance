"""Prototype Tool - Structuredness-Aware Miner Guidance — miner-flexible comparison Dash app.

Two tabs you actually use, plus a placeholder for the rubric:

* Tab 1 — pick or upload an event log; run the ARM classifier; see the
  matrix + structuredness verdict.
* Tab 2 — add/remove miner instances dynamically; each has its own config
  (data-driven from the registered :class:`MinerSpec.config_schema`); run
  them; compare results side-by-side.
* Tab 3 — Fragebogen placeholder (rubric / Fit-scoring is in scope for the
  separate ``tool/`` package, see ``tool/REQUIREMENTS.md``).

Start with:

    DASH_PORT=8502 .venv/bin/python -m flex_compare.app
"""
from __future__ import annotations

import logging
import os

import dash

from flex_compare import state as fc_state
from flex_compare.ui import layout as ui_layout
from flex_compare.ui.callbacks import (
    config_callbacks, fragebogen_callbacks, log_callbacks,
    miner_list_callbacks, routing_callbacks, run_callbacks,
    zoom_modal_callbacks,
)


logging.basicConfig(
    level=os.environ.get("FLEX_COMPARE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> dash.Dash:
    app = dash.Dash(__name__, title="Prototype Tool - Structuredness-Aware Miner Guidance",
                    suppress_callback_exceptions=True,
                    update_title=None)
    # Callable layout: Dash invokes it on every page load, so a browser reload
    # re-reads the on-disk state fresh instead of replaying the snapshot baked
    # in at server-start. Without this, Tab 2's miner cards (and the
    # APP_STATE_STORE) show a stale state until an add/remove callback fires.
    app.layout = lambda: ui_layout.render(fc_state.load())

    log_callbacks.register(app)
    miner_list_callbacks.register(app)
    config_callbacks.register(app)
    run_callbacks.register(app)
    zoom_modal_callbacks.register(app)
    fragebogen_callbacks.register(app)
    routing_callbacks.register(app)

    return app


app = create_app()
server = app.server  # gunicorn entry point


def _cli() -> None:
    """Console-script entry point installed by pyproject.toml."""
    port = int(os.environ.get("DASH_PORT", "8502"))
    host = os.environ.get("DASH_HOST", "127.0.0.1")
    logger.info("starting flex_compare on http://%s:%d", host, port)
    app.run(host=host, port=port, debug=bool(os.environ.get("DASH_DEBUG")))


if __name__ == "__main__":
    _cli()
