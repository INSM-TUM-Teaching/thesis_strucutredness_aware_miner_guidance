"""Browser-URL routing so the back/forward buttons navigate the app.

The app is a single page: tab selection and the Questionnaire's view live in
``dcc.Store``s, not in the URL, so without this the browser history has no
entries and back/forward leave the app entirely.

Here we mirror the navigation state into the URL query string of a
``dcc.Location`` (``ids.URL_BAR``) and back:

* **state to URL** (`_state_to_url`): whenever the active tab or the
  Questionnaire session changes, write a canonical ``?tab=...&view=...`` search
  string. Updating ``dcc.Location.search`` via a callback uses ``pushState``, so
  every navigation becomes a real history entry. Skips the write when the search
  already matches, so programmatic restores (below) add no spurious entries.
* **URL to state** (`_url_to_state`): whenever the search changes — back/forward,
  or a freshly opened bookmark on first load — parse it and set the tab + session
  accordingly. ``prevent_initial_call="initial_duplicate"`` lets it run on the
  initial page load so deep-linked URLs are honoured.

The two callbacks cannot loop: each one no-ops once the other side already
matches, and ``_state_to_url`` only inspects the navigation-relevant keys
(``view``/``miner_id``/``class``), so unrelated session churn (nonce, wizard
cursors, config overrides) never rewrites the URL.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlencode

from dash import Input, Output, State, no_update

from flex_compare.ui import ids


# URL slug <-> tab value. Slugs are stable, human-friendly, and bookmarkable.
_TAB_TO_SLUG = {
    ids.TAB_LOG: "log",
    ids.TAB_MINERS: "miners",
    ids.TAB_FRAGEBOGEN: "questionnaire",
}
_SLUG_TO_TAB = {v: k for k, v in _TAB_TO_SLUG.items()}


def _search_from_nav(tab: Optional[str], session: dict) -> str:
    """Build the canonical ``?...`` search string for the current navigation.

    Only the Questionnaire tab carries sub-state (view + selected miner/class);
    the other tabs are just ``?tab=<slug>``. Key order is fixed so the string
    round-trips exactly against :func:`_nav_from_search` (the loop guard relies
    on exact-string comparison).
    """
    slug = _TAB_TO_SLUG.get(tab, "log")
    params = [("tab", slug)]
    if slug == "questionnaire":
        params.append(("view", session.get("view") or "overview"))
        if session.get("miner_id"):
            params.append(("miner", session["miner_id"]))
        if session.get("class"):
            params.append(("class", session["class"]))
    return "?" + urlencode(params)


def _nav_from_search(search: Optional[str]) -> dict:
    """Parse a search string into ``{tab, view, miner, class}``.

    An empty URL maps to the default landing (Log tab, Questionnaire overview):
    the URL is the single source of truth for navigation, so going *back* to the
    initial blank entry must restore that landing rather than no-op.
    """
    if not search or search in ("?", "#"):
        return {"tab": ids.TAB_LOG, "view": "overview",
                "miner": None, "class": None}
    q = parse_qs(search.lstrip("?"))
    slug = (q.get("tab") or ["log"])[0]
    return {
        "tab": _SLUG_TO_TAB.get(slug, ids.TAB_LOG),
        "view": (q.get("view") or ["overview"])[0],
        "miner": (q.get("miner") or [None])[0],
        "class": (q.get("class") or [None])[0],
    }


def register(app) -> None:
    @app.callback(
        Output(ids.URL_BAR, "search"),
        Input(ids.TABS, "value"),
        Input(ids.FB_SESSION_STORE, "data"),
        State(ids.URL_BAR, "search"),
        prevent_initial_call=True,
    )
    def _state_to_url(tab, session, cur_search):
        want = _search_from_nav(tab, session or {})
        if want == (cur_search or ""):
            return no_update
        return want

    @app.callback(
        Output(ids.TABS, "value", allow_duplicate=True),
        Output(ids.FB_SESSION_STORE, "data", allow_duplicate=True),
        Input(ids.URL_BAR, "search"),
        State(ids.TABS, "value"),
        State(ids.FB_SESSION_STORE, "data"),
        prevent_initial_call="initial_duplicate",
    )
    def _url_to_state(search, cur_tab, cur_session):
        nav = _nav_from_search(search)
        tab_out = nav["tab"] if nav["tab"] != cur_tab else no_update

        cur_session = cur_session or {}
        same = (
            cur_session.get("view") == nav["view"]
            and cur_session.get("miner_id") == nav["miner"]
            and cur_session.get("class") == nav["class"]
        )
        if same:
            session_out = no_update
        else:
            # Merge the nav keys in, preserving transient session state
            # (nonce, ov_open, pb_cfg, wizard cursors) that the URL doesn't carry.
            session_out = {
                **cur_session,
                "view": nav["view"],
                "miner_id": nav["miner"],
                "class": nav["class"],
            }
        return tab_out, session_out
