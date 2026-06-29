"""Add / Remove miners + render the cards container."""
from __future__ import annotations

import json
import logging
from typing import Any

from dash import ALL, Input, Output, State, ctx, html, no_update

from flex_compare.internal.shared.registry import miner_registry

from flex_compare import state as fc_state
from flex_compare.state import InlineSpec, MinerInstance, new_instance_id
from flex_compare.ui import ids
from flex_compare.ui.components.miner_card import render_miner_card


logger = logging.getLogger(__name__)


def _default_label_for(spec_value: str) -> str:
    """e.g. "registry:minerful" → "MINERful (thesis defaults)"."""
    source, _, spec_id = spec_value.partition(":")
    if source == "registry":
        spec = miner_registry.get(spec_id)
        return spec.label if spec else spec_id
    if source == "inline":
        return f"Custom ({spec_id})"
    return spec_id


def _build_instance_from_modal(
    spec_value: str,
    label: str,
    paradigm: str,
    entry_point: str,
    command: str,
    output_format: str,
    output_pattern: str,
    config_json: str,
) -> tuple[MinerInstance | None, str]:
    """Returns (instance, error_message)."""
    source, _, spec_id = (spec_value or "").partition(":")
    label = (label or "").strip() or _default_label_for(spec_value)

    if source == "registry":
        spec = miner_registry.get(spec_id)
        if spec is None:
            return None, f"unknown registry spec: {spec_id!r}"
        # Pre-fill config from schema defaults.
        config = {p.key: p.default for p in spec.config_schema}
        return MinerInstance(
            id=new_instance_id(),
            spec_source="registry",
            spec_id=spec_id,
            label=label,
            config=config,
        ), ""

    if source == "inline":
        runner_kind = spec_id  # "module" or "executable"
        try:
            config = json.loads(config_json or "{}")
            if not isinstance(config, dict):
                raise ValueError("config JSON must be an object")
        except (json.JSONDecodeError, ValueError) as exc:
            return None, f"invalid config JSON: {exc}"

        if runner_kind == "module":
            if not (entry_point or "").strip():
                return None, "entry point is required for Python module type"
            inline = InlineSpec(
                label=label, paradigm=paradigm,
                runner_kind="module", entry_point=entry_point.strip(),
                config_schema=tuple(),  # free-form — no schema
            )
        elif runner_kind == "executable":
            if not (command or "").strip():
                return None, "command template is required for executable type"
            if not (output_pattern or "").strip():
                return None, "output pattern is required for executable type"
            inline = InlineSpec(
                label=label, paradigm=paradigm,
                runner_kind="executable",
                command_template=command.strip(),
                output_format=output_format or "pnml",
                output_pattern=output_pattern.strip(),
                config_schema=tuple(),
            )
        else:
            return None, f"unknown inline runner kind: {runner_kind!r}"

        return MinerInstance(
            id=new_instance_id(),
            spec_source="inline",
            spec_id=None,
            inline_spec=inline,
            label=label,
            config=config,
        ), ""

    return None, f"unknown type prefix: {source!r}"


def register(app):
    # ── Open / close add-modal ──
    @app.callback(
        Output(ids.ADD_MODAL, "style"),
        Output("fc-add-modal-inline-fields", "style"),
        Output(ids.ADD_MODAL_FEEDBACK, "children", allow_duplicate=True),
        Input(ids.ADD_MINER_BTN, "n_clicks"),
        Input(ids.ADD_MODAL_CANCEL, "n_clicks"),
        Input(ids.ADD_MODAL_TYPE, "value"),
        Input(ids.ADD_MODAL_CONFIRM, "n_clicks"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def _modal_visibility(open_n, cancel_n, type_value, confirm_n, app_state):
        triggered = ctx.triggered_id
        # Cancel always closes
        if triggered == ids.ADD_MODAL_CANCEL:
            return {"display": "none"}, {"display": "none"}, ""
        # Open
        if triggered == ids.ADD_MINER_BTN:
            show_inline = bool(type_value and str(type_value).startswith("inline:"))
            return {"display": "block"}, ({} if show_inline else {"display": "none"}), ""
        # Type change while modal open: toggle inline fields visibility.
        if triggered == ids.ADD_MODAL_TYPE:
            show_inline = bool(type_value and str(type_value).startswith("inline:"))
            return {"display": "block"}, ({} if show_inline else {"display": "none"}), no_update
        # Confirm — handled by the add-instance callback below; close here.
        return no_update, no_update, no_update

    # ── Confirm add → mutate state + close modal ──
    @app.callback(
        Output(ids.APP_STATE_STORE, "data", allow_duplicate=True),
        Output(ids.ADD_MODAL, "style", allow_duplicate=True),
        Output(ids.ADD_MODAL_FEEDBACK, "children"),
        Input(ids.ADD_MODAL_CONFIRM, "n_clicks"),
        State(ids.ADD_MODAL_TYPE, "value"),
        State(ids.ADD_MODAL_LABEL, "value"),
        State(ids.ADD_MODAL_INLINE_PARADIGM, "value"),
        State(ids.ADD_MODAL_INLINE_ENTRY_POINT, "value"),
        State(ids.ADD_MODAL_INLINE_COMMAND, "value"),
        State(ids.ADD_MODAL_INLINE_OUTPUT_FORMAT, "value"),
        State(ids.ADD_MODAL_INLINE_OUTPUT_PATTERN, "value"),
        State(ids.ADD_MODAL_INLINE_CONFIG, "value"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def _confirm_add(n, spec_value, label, paradigm, entry_point, command,
                     output_format, output_pattern, config_json, app_state):
        if not n:
            return no_update, no_update, no_update

        instance, err = _build_instance_from_modal(
            spec_value, label, paradigm, entry_point, command,
            output_format, output_pattern, config_json,
        )
        if instance is None:
            return no_update, no_update, err

        state = fc_state.load()
        fc_state.add_instance(state, instance)
        try:
            fc_state.save(state)
        except Exception as exc:
            logger.warning("state save failed: %s", exc)
            return no_update, no_update, f"could not persist state: {exc}"
        return state.to_jsonable(), {"display": "none"}, ""

    # ── Remove instance (pattern-matched button) ──
    @app.callback(
        Output(ids.APP_STATE_STORE, "data", allow_duplicate=True),
        Input({"type": "fc-remove-btn", "instance": ALL}, "n_clicks"),
        State(ids.APP_STATE_STORE, "data"),
        prevent_initial_call=True,
    )
    def _remove(clicks, app_state):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or triggered.get("type") != "fc-remove-btn":
            return no_update
        # Filter out the no-op initial fires (n_clicks == 0 across the board).
        if not any((c or 0) > 0 for c in (clicks or [])):
            return no_update
        instance_id = triggered.get("instance")
        if not instance_id:
            return no_update
        state = fc_state.load()
        fc_state.remove_instance(state, instance_id)
        try:
            fc_state.save(state)
        except Exception as exc:
            logger.warning("state save failed: %s", exc)
        return state.to_jsonable()

    # ── State change → re-render cards container ──
    @app.callback(
        Output(ids.MINER_CARDS_CONTAINER, "children"),
        Input(ids.APP_STATE_STORE, "data"),
    )
    def _render_cards(app_state):
        if not app_state:
            return []
        state = fc_state.FlexState.from_jsonable(app_state)
        return [render_miner_card(i) for i in state.instances]
