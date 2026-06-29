"""Per-trace Declare constraint satisfaction.

Implements the trace semantics of every MINERful Declare template seen across
the cached runs (16 templates, plus the standard relatives — Response /
Precedence / Succession / End / Existence / Absence — that MINERful can also
emit). One small predicate per template; a single dispatcher pulls activity
parameters out of the MINERful JSON shape and routes to it.

**Replayability semantic.** A variant is *replayable* by a discovered
declarative model iff every constraint is `not_violated` on the variant —
which includes vacuous satisfactions (the constraint never activates). That
matches S-BQ-2's question (*do the variants observed in the log remain
replayable?*) without conflating it with the orthogonal vacuity discussion: a
trace that never triggers a constraint is still trivially replayed by it.

Notation: activities are bare strings; a *trace* is a tuple/list of activity
strings in event order. The MINERful spec stores parameters as a
two-level list (``[['a'], ['b']]``) — the outer list lets a template be
branched (e.g. ``Response({a,a'}, b)``); MINERful emits unbranched
constraints in the discovery output, so we treat ``params[i][0]`` as the
``i``-th activity name. The dispatcher tolerates extra branch elements by
ignoring them rather than throwing.

References: van der Aalst et al. *Declare: Full Support for Loosely-Structured
Processes* (2009); Di Ciccio & Mecella *MINERful* (2013); Burattin et al.
*Conformance Checking Based on Declarative Process Models* (2016).
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence


# A trace = ordered sequence of activity names (one event = one entry).
Trace = Sequence[str]


# ── Helpers ────────────────────────────────────────────────────────────────

def _count(trace: Trace, a: str) -> int:
    return sum(1 for x in trace if x == a)


def _positions(trace: Trace, a: str) -> list[int]:
    return [i for i, x in enumerate(trace) if x == a]


def _has(trace: Trace, a: str) -> bool:
    return any(x == a for x in trace)


# ── Existence-family templates (unary) ─────────────────────────────────────

def _atleast1(trace: Trace, a: str) -> bool:
    return _has(trace, a)


def _atmost1(trace: Trace, a: str) -> bool:
    return _count(trace, a) <= 1


def _existence(trace: Trace, a: str, n: int = 1) -> bool:
    return _count(trace, a) >= n


def _absence(trace: Trace, a: str, n: int = 1) -> bool:
    """``Absence(a, n)`` = a appears strictly less than n times.

    MINERful's standard ``Absence`` is ``Absence(a, 1)`` ≡ ``not _has(a)``;
    ``Absence2`` is ``count < 2`` etc.
    """
    return _count(trace, a) < n


def _init(trace: Trace, a: str) -> bool:
    """``Init(a)`` = the first event of the trace is ``a``.

    Empty traces are *vacuously* satisfied: the activation (a first event)
    does not exist, so there is nothing to violate.
    """
    if not trace:
        return True
    return trace[0] == a


def _end(trace: Trace, a: str) -> bool:
    if not trace:
        return True
    return trace[-1] == a


# ── Binary positive templates (a → b) ──────────────────────────────────────

def _responded_existence(trace: Trace, a: str, b: str) -> bool:
    return (not _has(trace, a)) or _has(trace, b)


def _response(trace: Trace, a: str, b: str) -> bool:
    """Every ``a`` is eventually followed by some ``b`` later in the trace."""
    for i, x in enumerate(trace):
        if x == a:
            if not any(y == b for y in trace[i + 1:]):
                return False
    return True


def _precedence(trace: Trace, a: str, b: str) -> bool:
    """Every ``b`` is preceded by some ``a`` earlier in the trace."""
    for i, x in enumerate(trace):
        if x == b:
            if not any(y == a for y in trace[:i]):
                return False
    return True


def _succession(trace: Trace, a: str, b: str) -> bool:
    return _response(trace, a, b) and _precedence(trace, a, b)


def _alternate_response(trace: Trace, a: str, b: str) -> bool:
    """Every ``a`` is followed by a ``b`` *before* the next ``a``."""
    pending = False
    for x in trace:
        if x == a:
            if pending:        # second a with no b between → violated
                return False
            pending = True
        elif x == b and pending:
            pending = False
    # If the last a has no b after, that is the same situation Response
    # already rejects — keep the diagnostic consistent.
    return not pending


def _alternate_precedence(trace: Trace, a: str, b: str) -> bool:
    """Every ``b`` is preceded by an ``a`` with no ``b`` between."""
    seen_a = False
    for x in trace:
        if x == a:
            seen_a = True
        elif x == b:
            if not seen_a:
                return False
            seen_a = False     # consumed by this b; next b needs another a
    return True


def _alternate_succession(trace: Trace, a: str, b: str) -> bool:
    return (_alternate_response(trace, a, b)
            and _alternate_precedence(trace, a, b))


def _chain_response(trace: Trace, a: str, b: str) -> bool:
    """Every ``a`` is *immediately* followed by ``b`` (next event = b)."""
    for i, x in enumerate(trace):
        if x == a:
            if i + 1 >= len(trace) or trace[i + 1] != b:
                return False
    return True


def _chain_precedence(trace: Trace, a: str, b: str) -> bool:
    """Every ``b`` is *immediately* preceded by ``a`` (previous event = a)."""
    for i, x in enumerate(trace):
        if x == b:
            if i == 0 or trace[i - 1] != a:
                return False
    return True


def _chain_succession(trace: Trace, a: str, b: str) -> bool:
    return _chain_response(trace, a, b) and _chain_precedence(trace, a, b)


def _coexistence(trace: Trace, a: str, b: str) -> bool:
    return _has(trace, a) == _has(trace, b)


# ── Binary negative templates ──────────────────────────────────────────────

def _not_responded_existence(trace: Trace, a: str, b: str) -> bool:
    """If ``a`` occurs anywhere, ``b`` does NOT occur anywhere."""
    return (not _has(trace, a)) or (not _has(trace, b))


def _not_response(trace: Trace, a: str, b: str) -> bool:
    """No ``a`` is followed by a ``b`` somewhere later."""
    for i, x in enumerate(trace):
        if x == a and any(y == b for y in trace[i + 1:]):
            return False
    return True


def _not_precedence(trace: Trace, a: str, b: str) -> bool:
    """No ``b`` has an ``a`` somewhere earlier."""
    for i, x in enumerate(trace):
        if x == b and any(y == a for y in trace[:i]):
            return False
    return True


def _not_succession(trace: Trace, a: str, b: str) -> bool:
    """No ``a … b`` subsequence anywhere in the trace.

    Equivalent to ``_not_response`` AND ``_not_precedence`` — kept explicit so
    each template has its own predicate the dispatcher can name in errors.
    """
    return _not_response(trace, a, b) and _not_precedence(trace, a, b)


def _not_chain_response(trace: Trace, a: str, b: str) -> bool:
    """No ``a`` is *immediately* followed by ``b``."""
    for i, x in enumerate(trace):
        if x == a and i + 1 < len(trace) and trace[i + 1] == b:
            return False
    return True


def _not_chain_precedence(trace: Trace, a: str, b: str) -> bool:
    """No ``b`` is *immediately* preceded by ``a``."""
    for i, x in enumerate(trace):
        if x == b and i > 0 and trace[i - 1] == a:
            return False
    return True


def _not_chain_succession(trace: Trace, a: str, b: str) -> bool:
    return (_not_chain_response(trace, a, b)
            and _not_chain_precedence(trace, a, b))


def _not_coexistence(trace: Trace, a: str, b: str) -> bool:
    return not (_has(trace, a) and _has(trace, b))


# ── Dispatcher ─────────────────────────────────────────────────────────────

_UNARY: dict[str, Callable[[Trace, str], bool]] = {
    "AtLeast1": _atleast1,
    "AtMost1": _atmost1,
    "Init": _init,
    "End": _end,
    "Last": _end,                # MINERful sometimes uses "Last"
    "Existence": _atleast1,      # alias when no explicit n is encoded
}

_UNARY_N: dict[str, Callable[[Trace, str, int], bool]] = {
    "Existence": _existence,
    "Existence2": lambda t, a: _existence(t, a, 2),
    "Existence3": lambda t, a: _existence(t, a, 3),
    "Absence": _absence,
    "Absence2": lambda t, a: _absence(t, a, 2),
    "Absence3": lambda t, a: _absence(t, a, 3),
}

_BINARY: dict[str, Callable[[Trace, str, str], bool]] = {
    "RespondedExistence": _responded_existence,
    "Response": _response,
    "Precedence": _precedence,
    "Succession": _succession,
    "AlternateResponse": _alternate_response,
    "AlternatePrecedence": _alternate_precedence,
    "AlternateSuccession": _alternate_succession,
    "ChainResponse": _chain_response,
    "ChainPrecedence": _chain_precedence,
    "ChainSuccession": _chain_succession,
    "CoExistence": _coexistence,
    "NotRespondedExistence": _not_responded_existence,
    "NotResponse": _not_response,
    "NotPrecedence": _not_precedence,
    "NotSuccession": _not_succession,
    "NotChainResponse": _not_chain_response,
    "NotChainPrecedence": _not_chain_precedence,
    "NotChainSuccession": _not_chain_succession,
    "NotCoExistence": _not_coexistence,
}


# Templates we know about but cannot rule on — dispatcher returns ``None``
# (= unknown). The replay aggregation can decide what to do with that.
class UnknownTemplate(LookupError):
    pass


def is_satisfied(template: str, params: list, trace: Trace) -> Optional[bool]:
    """Return whether ``trace`` does not violate the constraint.

    ``None`` is returned for templates that are not implemented (so the caller
    can decide between strict abort and a softer treatment). MINERful emits
    parameters as ``[[branch1_a, branch1_a'], [branch2_b, ...]]`` — we use the
    first activity of each branch; multi-activity branches degrade gracefully
    rather than throwing.
    """
    activities = _resolve_activities(params)

    if template in _UNARY_N:
        if not activities:
            return None
        return _UNARY_N[template](trace, activities[0])

    if template in _UNARY:
        if not activities:
            return None
        return _UNARY[template](trace, activities[0])

    if template in _BINARY:
        if len(activities) < 2:
            return None
        return _BINARY[template](trace, activities[0], activities[1])

    return None


def _resolve_activities(params) -> list[str]:
    """Pull the leading activity name out of each branch.

    Accepts MINERful's ``[['a'], ['b']]`` shape as well as a flat ``['a','b']``
    fallback. Trims whitespace. Empty branches resolve to ``''``.
    """
    out: list[str] = []
    if not isinstance(params, (list, tuple)):
        return out
    for entry in params:
        if isinstance(entry, (list, tuple)):
            out.append(str(entry[0]).strip() if entry else "")
        else:
            out.append(str(entry).strip())
    return out


def evaluate_trace(constraints: Iterable[dict],
                   trace: Trace) -> dict[str, object]:
    """Run every constraint against one trace.

    Returns:
        ``{"replayable": bool, "n_total": int, "n_satisfied": int,
           "n_violated": int, "n_unknown": int, "violations": [(template, params)]}``

    ``replayable`` is ``True`` iff no constraint is violated. Unknown templates
    do not count as violations — but they DO bump ``n_unknown`` so a caller
    can warn that the answer is not strict.
    """
    n_total = n_sat = n_vio = n_unk = 0
    violations: list[tuple[str, list]] = []
    for c in constraints or ():
        if not isinstance(c, dict):
            continue
        n_total += 1
        template = str(c.get("template") or "")
        params = c.get("parameters") or []
        verdict = is_satisfied(template, params, trace)
        if verdict is None:
            n_unk += 1
        elif verdict:
            n_sat += 1
        else:
            n_vio += 1
            violations.append((template, list(params)))
    return {
        "replayable": n_vio == 0,
        "n_total": n_total,
        "n_satisfied": n_sat,
        "n_violated": n_vio,
        "n_unknown": n_unk,
        "violations": violations,
    }
