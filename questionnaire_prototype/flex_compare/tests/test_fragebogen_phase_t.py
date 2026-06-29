"""Phase-T (theoretical, binary Ja/Nein) scoring."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flex_compare.fragebogen import config_loader, items, phase_t
from flex_compare.fragebogen import phase_t_answers as fb_answers


class PhaseTStructuredSeedsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config_loader.reload()
        items.refresh()

    def test_imf_is_all_ja_on_structured(self) -> None:
        # Structured Phase T = {T-S-BQ-1, T-S-BQ-2, T-S-SF-1}; imp seeds all "ja".
        res = phase_t.phase_t_fit("imp", "structured")
        self.assertEqual(res["n_ja"], 3)
        self.assertEqual(res["n_nein"], 0)
        self.assertEqual(res["n_nz"], 0)
        self.assertEqual(res["points"], 3)
        self.assertEqual(res["max"], 3)
        self.assertEqual(res["fit"], 100.0)
        self.assertTrue(res["complete"])

    def test_decl_two_ja_one_nein_on_structured(self) -> None:
        # decl seeds: T-S-BQ-1=ja, T-S-BQ-2=ja, T-S-SF-1=nein
        # → 2 ja, 1 nein → fit = 66.7
        res = phase_t.phase_t_fit("decl", "structured")
        self.assertEqual(res["n_ja"], 2)
        self.assertEqual(res["n_nein"], 1)
        self.assertEqual(res["fit"], 66.7)

    def test_unseeded_miner_is_all_pending(self) -> None:
        res = phase_t.phase_t_fit("unknown-miner", "structured")
        self.assertEqual(res["n_pending"], 3)
        self.assertEqual(res["max"], 0)
        self.assertIsNone(res["fit"])
        self.assertFalse(res["complete"])

    def test_pm4_heuristics_one_ja_two_nein_on_structured(self) -> None:
        # pm4-heuristics on structured: T-S-BQ-1=nein, T-S-BQ-2=nein,
        # T-S-SF-1=ja → 1 ja, 2 nein, 0 pending → max=3, fit=33.3
        res = phase_t.phase_t_fit("pm4-heuristics", "structured")
        self.assertEqual(res["n_ja"], 1)
        self.assertEqual(res["n_nein"], 2)
        self.assertEqual(res["n_pending"], 0)
        self.assertEqual(res["max"], 3)
        self.assertEqual(res["fit"], 33.3)
        self.assertTrue(res["complete"])

    def test_nz_counts_as_zero_in_denominator(self) -> None:
        # T-Sm-SF-1 is allow_nz=true; imp seed is "nz" → 0 in numerator, +1 in denom
        # imp on Semi: BQ-1=nein, BQ-2=ja, SF-1=nz → 1 ja, 1 nein, 1 nz
        # → points=1, max=3, fit=33.3
        res = phase_t.phase_t_fit("imp", "semi")
        self.assertEqual(res["n_ja"], 1)
        self.assertEqual(res["n_nein"], 1)
        self.assertEqual(res["n_nz"], 1)
        self.assertEqual(res["points"], 1)
        self.assertEqual(res["max"], 3)
        self.assertEqual(res["fit"], 33.3)

    def test_item_value_lookup(self) -> None:
        self.assertEqual(phase_t.phase_t_item_value("T-S-BQ-1", "imp"), "ja")
        self.assertEqual(phase_t.phase_t_item_value("T-S-SF-1", "decl"), "nein")
        self.assertEqual(phase_t.phase_t_item_value("T-Sm-SF-1", "imp"), "nz")
        self.assertIsNone(
            phase_t.phase_t_item_value("T-S-BQ-1", "unknown-miner"))

    def test_vector_has_stable_shape(self) -> None:
        vec = phase_t.phase_t_vector("imp")
        self.assertEqual(set(vec["fits"]), {"structured", "semi", "loosely"})
        self.assertEqual(vec["fits"]["structured"], 100.0)
        self.assertEqual(vec["home_class"], "structured")

    def test_configured_classes_lists_all_three(self) -> None:
        self.assertEqual(set(phase_t.configured_classes()),
                         {"structured", "semi", "loosely"})


class PhaseTOverlayTests(unittest.TestCase):
    """Persisted answers must override the YAML seed."""

    def setUp(self) -> None:
        config_loader.reload()
        items.refresh()
        self._tmp = tempfile.TemporaryDirectory()
        fb_answers.set_root(Path(self._tmp.name))

    def tearDown(self) -> None:
        fb_answers.set_root(None)
        self._tmp.cleanup()

    def test_without_answers_overlay_matches_seed(self) -> None:
        seed = phase_t.phase_t_fit("imp", "structured")
        overlay = phase_t.phase_t_fit_with_answers("imp", "structured")
        self.assertEqual(overlay["fit"], seed["fit"])
        self.assertEqual(overlay["n_human"], 0)

    def test_human_nein_overrides_seed_ja(self) -> None:
        fb_answers.save_answer(cls="structured", miner_id="imp",
                                item_id="T-S-BQ-1", value="nein")
        res = phase_t.phase_t_fit_with_answers("imp", "structured")
        # imp seeds ja/ja/ja; BQ-1 overridden to nein → 2 ja, 1 nein → 66.7
        self.assertEqual(res["n_ja"], 2)
        self.assertEqual(res["n_nein"], 1)
        self.assertEqual(res["fit"], 66.7)
        self.assertEqual(res["n_human"], 1)
        self.assertEqual(res["per_item"]["T-S-BQ-1"]["source"], "human")

    def test_human_nz_counts_as_zero_in_denom(self) -> None:
        # T-Sm-SF-1 is the allow_nz=true item.
        fb_answers.save_answer(cls="semi", miner_id="fus",
                                item_id="T-Sm-SF-1", value="nz")
        res = phase_t.phase_t_fit_with_answers("fus", "semi")
        # fus seeds on Semi: BQ-1=ja, BQ-2=ja, SF-1 was "ja" (now nz)
        # → 2 ja, 1 nz → max 3, points 2 → 66.7
        self.assertEqual(res["n_nz"], 1)
        self.assertEqual(res["n_ja"], 2)
        self.assertEqual(res["points"], 2)
        self.assertEqual(res["max"], 3)
        self.assertEqual(res["fit"], 66.7)

    def test_partial_pending_counts_only_answered(self) -> None:
        # Unseeded miner with one human answer: 1 answered, 2 pending → max=1.
        fb_answers.save_answer(cls="structured", miner_id="unknown-miner",
                                item_id="T-S-BQ-1", value="ja")
        res = phase_t.phase_t_fit_with_answers("unknown-miner", "structured")
        self.assertEqual(res["n_ja"], 1)
        self.assertEqual(res["n_pending"], 2)
        self.assertEqual(res["points"], 1)
        self.assertEqual(res["max"], 1)
        self.assertEqual(res["fit"], 100.0)
        self.assertFalse(res["complete"])

    def test_pure_fit_function_ignores_persisted_answers(self) -> None:
        fb_answers.save_answer(cls="structured", miner_id="imp",
                                item_id="T-S-BQ-1", value="nein")
        self.assertEqual(phase_t.phase_t_fit("imp", "structured")["fit"], 100.0)


class PhaseTAnswersPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        fb_answers.set_root(Path(self._tmp.name))

    def tearDown(self) -> None:
        fb_answers.set_root(None)
        self._tmp.cleanup()

    def test_load_missing_cell_returns_none(self) -> None:
        self.assertIsNone(
            fb_answers.load_answer("structured", "imp", "T-S-BQ-1"))

    def test_roundtrip(self) -> None:
        fb_answers.save_answer(cls="structured", miner_id="imp",
                                item_id="T-S-BQ-1", value="ja",
                                note="docs confirm")
        got = fb_answers.load_answer("structured", "imp", "T-S-BQ-1")
        self.assertEqual(got["value"], "ja")
        self.assertEqual(got["note"], "docs confirm")
        self.assertEqual(got["miner_id"], "imp")
        self.assertEqual(got["item_id"], "T-S-BQ-1")

    def test_nz_roundtrip(self) -> None:
        fb_answers.save_answer(cls="semi", miner_id="imp",
                                item_id="T-Sm-SF-1", value="nz")
        got = fb_answers.load_answer("semi", "imp", "T-Sm-SF-1")
        self.assertEqual(got["value"], "nz")

    def test_invalid_value_rejected(self) -> None:
        with self.assertRaises(ValueError):
            fb_answers.save_answer(cls="structured", miner_id="imp",
                                    item_id="T-S-BQ-1", value="maybe")

    def test_load_all_groups_by_miner_item(self) -> None:
        fb_answers.save_answer(cls="structured", miner_id="imp",
                                item_id="T-S-BQ-1", value="ja")
        fb_answers.save_answer(cls="structured", miner_id="decl",
                                item_id="T-S-BQ-1", value="nein")
        bundle = fb_answers.load_all_answers("structured")
        self.assertIn(("imp", "T-S-BQ-1"), bundle)
        self.assertIn(("decl", "T-S-BQ-1"), bundle)


if __name__ == "__main__":
    unittest.main()
