"""Persist config edits + drive ``visible_when`` field visibility."""
from __future__ import annotations

import logging

from dash import ALL, Input, Output, State, ctx, no_update

from flex_compare.internal.shared.registry import miner_registry

from flex_compare import state as fc_state
from flex_compare.ui import ids


logger = logging.getLogger(__name__)


def register(app):
    # ── Save config edits back to .flex_compare/state.json ──
    @app.callback(
        Output(ids.APP_STATE_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-config", "instance": ALL, "key": ALL}, "value"),
        State({"type": "fc-config", "instance": ALL, "key": ALL}, "id"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def _persist_config(values, id_list, app_state):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or triggered.get("type") != "fc-config":
            return no_update
        if not app_state:
            return no_update

        # Group values by instance id.
        by_instance: dict[str, dict] = {}
        for value, idd in zip(values or [], id_list or []):
            inst_id = idd.get("instance")
            key = idd.get("key")
            if inst_id and key is not None:
                by_instance.setdefault(inst_id, {})[key] = value

        state = fc_state.load()
        changed = False
        for inst in list(state.instances):
            new_cfg = by_instance.get(inst.id)
            if new_cfg is None:
                continue
            merged = {**inst.config, **new_cfg}
            if merged != inst.config:
                fc_state.update_instance_config(state, inst.id, merged)
                changed = True
        if not changed:
            return no_update
        try:
            fc_state.save(state)
        except Exception as exc:
            logger.warning("state save failed: %s", exc)
        return state.to_jsonable()
