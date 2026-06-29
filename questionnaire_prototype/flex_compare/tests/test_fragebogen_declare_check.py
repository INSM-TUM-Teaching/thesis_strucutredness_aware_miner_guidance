"""Trace semantics for the Declare templates.

Each test names the *intent* of the template, then exercises one accepting
and one rejecting trace. Empty traces are accepted by every template that
declarative semantics treats as vacuously satisfied (no activation → no
violation). The dispatcher's parameter-extraction handles MINERful's
``[['a'], ['b']]`` shape; the tests use that shape verbatim so we catch any
regression in the param parser.
"""
from __future__ import annotations

import unittest

from flex_compare.fragebogen.declare_check import evaluate_trace, is_satisfied


def _params(*activities):
    """Wrap activity strings in MINERful's two-level branch list."""
    return [[a] for a in activities]


class UnaryTemplatesTests(unittest.TestCase):
    def test_at_least1(self):
        self.assertTrue(is_satisfied("AtLeast1", _params("a"), ["x", "a", "y"]))
        self.assertFalse(is_satisfied("AtLeast1", _params("a"), ["x", "y"]))
        self.assertFalse(is_satisfied("AtLeast1", _params("a"), []))

    def test_at_most1(self):
        self.assertTrue(is_satisfied("AtMost1", _params("a"), ["a"]))
        self.assertTrue(is_satisfied("AtMost1", _params("a"), []))
        self.assertTrue(is_satisfied("AtMost1", _params("a"), ["x", "y"]))
        self.assertFalse(is_satisfied("AtMost1", _params("a"), ["a", "x", "a"]))

    def test_init(self):
        self.assertTrue(is_satisfied("Init", _params("a"), ["a", "b", "c"]))
        self.assertFalse(is_satisfied("Init", _params("a"), ["b", "a", "c"]))
        self.assertTrue(is_satisfied("Init", _params("a"), []))  # vacuous

    def test_end(self):
        self.assertTrue(is_satisfied("End", _params("a"), ["x", "y", "a"]))
        self.assertFalse(is_satisfied("End", _params("a"), ["x", "a", "y"]))
        self.assertTrue(is_satisfied("End", _params("a"), []))

    def test_existence_with_count(self):
        self.assertTrue(is_satisfied("Existence2", _params("a"), ["a", "x", "a"]))
        self.assertFalse(is_satisfied("Existence2", _params("a"), ["a", "x"]))

    def test_absence_with_count(self):
        # Absence2(a) = a occurs strictly less than twice.
        self.assertTrue(is_satisfied("Absence2", _params("a"), ["a", "b"]))
        self.assertFalse(is_satisfied("Absence2", _params("a"), ["a", "b", "a"]))


class BinaryPositiveTemplatesTests(unittest.TestCase):
    def test_responded_existence(self):
        self.assertTrue(is_satisfied("RespondedExistence",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("RespondedExistence",
                                       _params("a", "b"), ["a", "x"]))
        # vacuous — a never occurs:
        self.assertTrue(is_satisfied("RespondedExistence",
                                      _params("a", "b"), ["x", "y"]))

    def test_response(self):
        self.assertTrue(is_satisfied("Response",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("Response",
                                       _params("a", "b"), ["a", "x"]))

    def test_precedence(self):
        self.assertTrue(is_satisfied("Precedence",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("Precedence",
                                       _params("a", "b"), ["b", "a"]))

    def test_succession(self):
        self.assertTrue(is_satisfied("Succession",
                                      _params("a", "b"), ["a", "b"]))
        self.assertFalse(is_satisfied("Succession",
                                       _params("a", "b"), ["a"]))
        self.assertFalse(is_satisfied("Succession",
                                       _params("a", "b"), ["b"]))

    def test_alternate_response(self):
        self.assertTrue(is_satisfied("AlternateResponse",
                                      _params("a", "b"), ["a", "b", "a", "b"]))
        # two a's in a row before any b → violated
        self.assertFalse(is_satisfied("AlternateResponse",
                                       _params("a", "b"),
                                       ["a", "a", "b"]))

    def test_alternate_precedence(self):
        self.assertTrue(is_satisfied("AlternatePrecedence",
                                      _params("a", "b"), ["a", "b", "a", "b"]))
        self.assertFalse(is_satisfied("AlternatePrecedence",
                                       _params("a", "b"),
                                       ["a", "b", "b"]))

    def test_chain_response(self):
        self.assertTrue(is_satisfied("ChainResponse",
                                      _params("a", "b"), ["a", "b"]))
        self.assertFalse(is_satisfied("ChainResponse",
                                       _params("a", "b"), ["a", "x", "b"]))

    def test_chain_precedence(self):
        self.assertTrue(is_satisfied("ChainPrecedence",
                                      _params("a", "b"), ["a", "b"]))
        self.assertFalse(is_satisfied("ChainPrecedence",
                                       _params("a", "b"), ["a", "x", "b"]))

    def test_co_existence(self):
        self.assertTrue(is_satisfied("CoExistence",
                                      _params("a", "b"), ["a", "b"]))
        self.assertTrue(is_satisfied("CoExistence",
                                      _params("a", "b"), ["x"]))
        self.assertFalse(is_satisfied("CoExistence",
                                       _params("a", "b"), ["a"]))
        self.assertFalse(is_satisfied("CoExistence",
                                       _params("a", "b"), ["b"]))


class BinaryNegativeTemplatesTests(unittest.TestCase):
    def test_not_responded_existence(self):
        self.assertTrue(is_satisfied("NotRespondedExistence",
                                      _params("a", "b"), ["x"]))
        self.assertFalse(is_satisfied("NotRespondedExistence",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_response(self):
        self.assertTrue(is_satisfied("NotResponse",
                                      _params("a", "b"), ["b", "a"]))
        self.assertFalse(is_satisfied("NotResponse",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_precedence(self):
        self.assertTrue(is_satisfied("NotPrecedence",
                                      _params("a", "b"), ["b", "a"]))
        self.assertFalse(is_satisfied("NotPrecedence",
                                       _params("a", "b"), ["a", "x", "b"]))

    def test_not_succession(self):
        self.assertTrue(is_satisfied("NotSuccession",
                                      _params("a", "b"), ["b", "a"]))
        self.assertFalse(is_satisfied("NotSuccession",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_chain_response(self):
        self.assertTrue(is_satisfied("NotChainResponse",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("NotChainResponse",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_chain_precedence(self):
        self.assertTrue(is_satisfied("NotChainPrecedence",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("NotChainPrecedence",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_chain_succession(self):
        self.assertTrue(is_satisfied("NotChainSuccession",
                                      _params("a", "b"), ["a", "x", "b"]))
        self.assertFalse(is_satisfied("NotChainSuccession",
                                       _params("a", "b"), ["a", "b"]))

    def test_not_co_existence(self):
        self.assertTrue(is_satisfied("NotCoExistence",
                                      _params("a", "b"), ["a"]))
        self.assertTrue(is_satisfied("NotCoExistence",
                                      _params("a", "b"), ["b"]))
        self.assertTrue(is_satisfied("NotCoExistence",
                                      _params("a", "b"), ["x"]))
        self.assertFalse(is_satisfied("NotCoExistence",
                                       _params("a", "b"), ["a", "b"]))


class DispatcherTests(unittest.TestCase):
    def test_unknown_template_returns_none(self):
        self.assertIsNone(is_satisfied("MysteryTemplate",
                                        _params("a"), ["a"]))

    def test_empty_params_returns_none(self):
        self.assertIsNone(is_satisfied("Response", [], ["a", "b"]))

    def test_branched_params_use_first_activity(self):
        # MINERful can in principle emit ``[['a', 'a2'], ['b']]`` for branched
        # constraints — our checker uses the leading activity name.
        self.assertTrue(is_satisfied("Response",
                                      [["a", "a2"], ["b"]],
                                      ["a", "b"]))


class EvaluateTraceTests(unittest.TestCase):
    def test_aggregates_violation_count(self):
        constraints = [
            {"template": "Response", "parameters": _params("a", "b")},
            {"template": "Precedence", "parameters": _params("a", "b")},
            {"template": "MysteryTemplate", "parameters": _params("a")},
        ]
        # "a b" satisfies both Response and Precedence; mystery template
        # is unknown so it counts as n_unknown.
        verdict = evaluate_trace(constraints, ["a", "b"])
        self.assertTrue(verdict["replayable"])
        self.assertEqual(verdict["n_total"], 3)
        self.assertEqual(verdict["n_satisfied"], 2)
        self.assertEqual(verdict["n_violated"], 0)
        self.assertEqual(verdict["n_unknown"], 1)

    def test_one_violation_marks_not_replayable(self):
        constraints = [
            {"template": "Response", "parameters": _params("a", "b")},
            {"template": "NotResponse", "parameters": _params("a", "b")},
        ]
        # "a b" satisfies Response, but violates NotResponse — not replayable.
        verdict = evaluate_trace(constraints, ["a", "b"])
        self.assertFalse(verdict["replayable"])
        self.assertEqual(verdict["n_violated"], 1)
        self.assertEqual(len(verdict["violations"]), 1)
        self.assertEqual(verdict["violations"][0][0], "NotResponse")


if __name__ == "__main__":
    unittest.main()
