"""Segment annotations loader + lookup + shape validation."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from flex_compare.fragebogen import annotations
from flex_compare.fragebogen.annotations import AnnotationError


class _TempAnnotations:
    """Point the loader at a temp annotations dir, then restore on exit."""

    def __init__(self, **files: str) -> None:
        self.files = files

    def __enter__(self) -> Path:
        self._orig = annotations.ANNOTATIONS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        for name, content in self.files.items():
            (d / f"{name}.yaml").write_text(textwrap.dedent(content),
                                            encoding="utf-8")
        annotations.ANNOTATIONS_DIR = d
        try:
            annotations.reload()
        except Exception:
            # Restore before propagating: a failing load must not leave the
            # global pointing at the temp dir (__exit__ won't run on enter).
            self.__exit__()
            raise
        return d

    def __exit__(self, *exc) -> None:
        annotations.ANNOTATIONS_DIR = self._orig
        self._tmp.cleanup()
        annotations.reload()


_VALID = """\
Log02_semiStructured:
  E-Sm-BQ-1:
    segments:
      - name: "Stable core"
        activities: [Register, Check, Approve]
        note: "fixed ordering"
      - name: "Flexible region"
        activities: [Notify, Escalate]
"""


class AnnotationsLookupTests(unittest.TestCase):
    def test_segments_for_returns_validated_segments(self) -> None:
        with _TempAnnotations(semi=_VALID):
            segs = annotations.segments_for("Log02_semiStructured", "E-Sm-BQ-1")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["name"], "Stable core")
        self.assertEqual(segs[0]["activities"], ["Register", "Check", "Approve"])
        self.assertEqual(segs[0]["note"], "fixed ordering")
        self.assertIsNone(segs[1]["note"])

    def test_unknown_log_or_item_returns_empty(self) -> None:
        with _TempAnnotations(semi=_VALID):
            self.assertEqual(annotations.segments_for("nope", "E-Sm-BQ-1"), [])
            self.assertEqual(
                annotations.segments_for("Log02_semiStructured", "E-Sm-IN-2"),
                [])
            self.assertEqual(annotations.rules_for("nope", "E-Sm-BQ-1"), [])

    def test_rules_for_returns_text_and_strength(self) -> None:
        loosely = """\
            Log03_looselyStructured:
              E-L-BQ-1:
                rules:
                  - {text: "b directly before c", strength: direct}
                  - {text: "f before c", strength: eventual}
                  - "otherwise unordered"
            """
        with _TempAnnotations(loosely=loosely):
            rules = annotations.rules_for("Log03_looselyStructured", "E-L-BQ-1")
            self.assertEqual(rules, [
                {"text": "b directly before c", "strength": "direct"},
                {"text": "f before c", "strength": "eventual"},
                # bare string normalises to the untyped "note" strength
                {"text": "otherwise unordered", "strength": "note"},
            ])
            # An entry with only rules carries no segments.
            self.assertEqual(
                annotations.segments_for("Log03_looselyStructured", "E-L-BQ-1"),
                [])

    def test_missing_dir_is_empty_not_error(self) -> None:
        orig = annotations.ANNOTATIONS_DIR
        try:
            annotations.ANNOTATIONS_DIR = Path("/no/such/annotations/dir")
            annotations.reload()
            self.assertEqual(annotations.segments_for("x", "y"), [])
        finally:
            annotations.ANNOTATIONS_DIR = orig
            annotations.reload()

    def test_empty_file_is_valid(self) -> None:
        with _TempAnnotations(semi="# nothing here\n"):
            self.assertEqual(annotations.load(), {})


class AnnotationsValidationTests(unittest.TestCase):
    def _expect_error(self, content: str) -> None:
        with self.assertRaises(AnnotationError):
            with _TempAnnotations(semi=content):
                pass

    def test_segment_without_name_rejected(self) -> None:
        self._expect_error("""\
            Log02_semiStructured:
              E-Sm-BQ-1:
                segments:
                  - activities: [A, B]
            """)

    def test_activities_not_a_list_rejected(self) -> None:
        self._expect_error("""\
            Log02_semiStructured:
              E-Sm-BQ-1:
                segments:
                  - name: X
                    activities: "A, B"
            """)

    def test_empty_segments_rejected(self) -> None:
        self._expect_error("""\
            Log02_semiStructured:
              E-Sm-BQ-1:
                segments: []
            """)

    def test_top_level_not_mapping_rejected(self) -> None:
        self._expect_error("- just a list\n")

    def test_entry_with_neither_segments_nor_rules_rejected(self) -> None:
        self._expect_error("""\
            Log03_looselyStructured:
              E-L-BQ-1:
                foo: bar
            """)

    def test_empty_rules_rejected(self) -> None:
        self._expect_error("""\
            Log03_looselyStructured:
              E-L-BQ-1:
                rules: []
            """)

    def test_non_string_rule_rejected(self) -> None:
        self._expect_error("""\
            Log03_looselyStructured:
              E-L-BQ-1:
                rules:
                  - 42
            """)

    def test_unknown_rule_strength_rejected(self) -> None:
        self._expect_error("""\
            Log03_looselyStructured:
              E-L-BQ-1:
                rules:
                  - {text: "f before c", strength: super-strong}
            """)

    def test_rule_mapping_without_text_rejected(self) -> None:
        self._expect_error("""\
            Log03_looselyStructured:
              E-L-BQ-1:
                rules:
                  - {strength: direct}
            """)


class ShippedAnnotationsTests(unittest.TestCase):
    """The three shipped stub files load cleanly (empty mappings)."""

    def setUp(self) -> None:
        annotations.reload()

    def test_shipped_files_load(self) -> None:
        # Stubs are comment-only -> empty mapping, no error.
        self.assertIsInstance(annotations.load(), dict)


if __name__ == "__main__":
    unittest.main()
