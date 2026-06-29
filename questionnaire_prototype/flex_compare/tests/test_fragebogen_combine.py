"""Combined Fit (3/7·Tfit + 4/7·Efit) plus side-by-side leg reporting."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flex_compare.fragebogen import combine, config_loader, items
from flex_compare.fragebogen import phase_e_answers as fb_scores


class CombineReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config_loader.reload()
        items.refresh()

    def setUp(self) -> None:
        # Isolate the Phase-E score cache so "E has no cells" holds regardless
        # of any cells persisted in the real project cache.
        self._tmp = tempfile.TemporaryDirectory()
        fb_scores.set_root(Path(self._tmp.name))

    def tearDown(self) -> None:
        fb_scores.set_root(None)
        self._tmp.cleanup()

    def test_combination_mode_is_weighted(self) -> None:
        # Each class combines its two legs with equal weight per item.
        for cls in ("structured", "semi", "loosely"):
            self.assertEqual(combine.combination_config(cls)["mode"], "weighted")

    def test_report_carries_combined_and_both_legs(self) -> None:
        report = combine.report("imp")
        self.assertEqual(report["mode"], "weighted")
        self.assertIn("structured", report["t_fits"])
        self.assertIn("structured", report["e_fits"])
        self.assertIn("structured", report["fits"])
        # T is seeded → has a fit. E has no cells → None, so combined is None.
        self.assertEqual(report["t_fits"]["structured"], 100.0)
        self.assertIsNone(report["e_fits"]["structured"])
        self.assertIsNone(report["fits"]["structured"])

    def test_t_home_is_structured_for_imf(self) -> None:
        report = combine.report("imp")
        self.assertEqual(report["t_home"], "structured")

    def test_class_weights_three_t_four_e(self) -> None:
        # 3 Phase-T items, 4 Phase-E items → 3/7 and 4/7.
        for cls in ("structured", "semi", "loosely"):
            w = combine.class_weights(cls)
            self.assertEqual((w["n_t"], w["n_e"]), (3, 4))
            self.assertAlmostEqual(w["w_t"], 3 / 7)
            self.assertAlmostEqual(w["w_e"], 4 / 7)

    def test_combined_fit_equal_weight_per_item(self) -> None:
        # 3/7·100 + 4/7·50 = 300/7 + 200/7 = 500/7 ≈ 71.4.
        self.assertEqual(
            combine.combined_fit(100.0, 50.0, n_t=3, n_e=4), 71.4)

    def test_combined_fit_none_if_either_leg_missing(self) -> None:
        self.assertIsNone(combine.combined_fit(None, 50.0, n_t=3, n_e=4))
        self.assertIsNone(combine.combined_fit(100.0, None, n_t=3, n_e=4))
        self.assertIsNone(combine.combined_fit(None, None, n_t=3, n_e=4))

    def test_borderline_single_class(self) -> None:
        self.assertFalse(combine.borderline({"a": 80.0}, 10))

    def test_borderline_two_close_classes(self) -> None:
        self.assertTrue(combine.borderline({"a": 80.0, "b": 75.0}, 10))
        self.assertFalse(combine.borderline({"a": 80.0, "b": 60.0}, 10))


if __name__ == "__main__":
    unittest.main()
