from __future__ import annotations

from typing import Any


def fmt_bool_ja_nein(value: Any) -> str:
    """Format boolean as German ja/nein for Markdown reports."""
    if value is True:
        return "ja"
    if value is False:
        return "nein"
    return "n/a"


def fmt_bool_yes_no(value: Any) -> str:
    """Format boolean as yes/no."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "n/a"


def fmt_number(value: Any, digits: int = 6, none_placeholder: str = "n/a") -> str:
    """Format a numeric value as a fixed-point string."""
    if value is None:
        return none_placeholder
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.{digits}f}"
    return str(value)


def round_if_number(value: Any, digits: int = 6) -> Any:
    """Round numeric values for DataFrame export; leave non-numeric as-is."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, digits)
    return value


def na_if_none(value: Any) -> Any:
    """Replace None with the string 'n/a'."""
    return "n/a" if value is None else value


def checkbox(flag: bool) -> str:
    """Render a Markdown checkbox as [x] or [ ]."""
    return "[x]" if flag else "[ ]"


def fmt_value(value: Any, digits: int = 6) -> Any:
    """Generic formatter for Streamlit table cells.

    Returns a rounded float, 'yes'/'no' for booleans, 'n/a' for None,
    or the value itself otherwise.
    """
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return round(value, digits)
    return value
