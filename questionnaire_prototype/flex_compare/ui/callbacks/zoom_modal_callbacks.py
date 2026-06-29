"""Pattern-matching callback that toggles the per-instance model-zoom modal."""
from __future__ import annotations

from dash import ALL, Input, Output, State, ctx, no_update


_HIDDEN = {"display": "none"}
_VISIBLE = {"display": "block"}


def register(app) -> None:
    @app.callback(
        Output({"type": "fc-zoom-modal", "instance": ALL}, "style"),
        Input({"type": "fc-zoom-open", "instance": ALL}, "n_clicks"),
        Input({"type": "fc-zoom-close", "instance": ALL}, "n_clicks"),
        State({"type": "fc-zoom-modal", "instance": ALL}, "id"),
        prevent_initial_call=True,
    )
    def _toggle(_open_clicks, _close_clicks, modal_ids):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return [no_update for _ in modal_ids]
        # Pattern-matching callbacks also fire when matching components are
        # newly added to the layout (initial value 0/None). Ignore those —
        # only react when there was a real click (value >= 1).
        fired = ctx.triggered[0] if ctx.triggered else None
        if not fired or not fired.get("value"):
            return [no_update for _ in modal_ids]
        if triggered.get("type") == "fc-zoom-open":
            target = triggered.get("instance")
            return [
                _VISIBLE if m.get("instance") == target else no_update
                for m in modal_ids
            ]
        if triggered.get("type") == "fc-zoom-close":
            target = triggered.get("instance")
            return [
                _HIDDEN if m.get("instance") == target else no_update
                for m in modal_ids
            ]
        return [no_update for _ in modal_ids]
