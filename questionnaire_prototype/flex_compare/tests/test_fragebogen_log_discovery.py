"""Class-based log discovery — filename routing + sort stability."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flex_compare.fragebogen.log_discovery import logs_by_class, logs_for_class


class LogDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # Three structured, two semi, one loosely, plus two foreign names that
        # the discovery must silently skip.
        for name in (
            "Log01_structured.xes",
            "Log04_structured.xes",
            "Log02_semiStructured.xes",
            "Log15_structured.xes",
            "Log06_semiStructured.xes",
            "Log08_looselyStructured.xes",
            "Log09_unstructured.xes",                       # outside the three
            "Log14_looselyStructured_semiStructured.xes",   # ambiguous → skip
        ):
            (self.dir / name).write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_logs_for_class_structured_lists_sorted(self) -> None:
        paths = logs_for_class("structured", self.dir)
        self.assertEqual([p.name for p in paths],
                         ["Log01_structured.xes",
                          "Log04_structured.xes",
                          "Log15_structured.xes"])

    def test_logs_for_class_semi(self) -> None:
        paths = logs_for_class("semi", self.dir)
        self.assertEqual([p.name for p in paths],
                         ["Log02_semiStructured.xes",
                          "Log06_semiStructured.xes"])

    def test_logs_for_class_loosely(self) -> None:
        paths = logs_for_class("loosely", self.dir)
        self.assertEqual([p.name for p in paths],
                         ["Log08_looselyStructured.xes"])

    def test_logs_for_unknown_class_is_empty(self) -> None:
        self.assertEqual(logs_for_class("unstructured", self.dir), [])
        self.assertEqual(logs_for_class("", self.dir), [])

    def test_logs_for_missing_dir_is_empty(self) -> None:
        self.assertEqual(logs_for_class("structured", Path("/nope/nope")), [])

    def test_logs_by_class_aggregates(self) -> None:
        groups = logs_by_class(self.dir)
        self.assertEqual({k: [p.name for p in v] for k, v in groups.items()},
                         {"structured": ["Log01_structured.xes",
                                         "Log04_structured.xes",
                                         "Log15_structured.xes"],
                          "semi": ["Log02_semiStructured.xes",
                                   "Log06_semiStructured.xes"],
                          "loosely": ["Log08_looselyStructured.xes"]})

    def test_foreign_filenames_are_skipped(self) -> None:
        # The two foreign names exist on disk but show up in no group.
        all_paths = [p for paths in logs_by_class(self.dir).values()
                     for p in paths]
        names = {p.name for p in all_paths}
        self.assertNotIn("Log09_unstructured.xes", names)
        self.assertNotIn("Log14_looselyStructured_semiStructured.xes", names)


if __name__ == "__main__":
    unittest.main()
