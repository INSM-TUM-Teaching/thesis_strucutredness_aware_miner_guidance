"""Phase-E (empirical, 0/1/2 + n.z. + Gate) scoring and persistence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flex_compare.fragebogen import config_loader, items, phase_e
from flex_compare.fragebogen import phase_e_answers as fb_scores


class _FakeInstance:
    def __init__(self, miner_id: str) -> None:
        # ``id`` mirrors how Tab 3 renders/saves (ephemeral instance id == spec
        # id); the read path resolves the slot by ``id``, so it must be present.
        self.id = miner_id
        self.spec_source = "registry"
        self.spec_id = miner_id
        self.config = {}


class _FakeState:
    def __init__(self, miner_id: str) -> None:
        self.instances = (_FakeInstance(miner_id),)


def _fake_log_id(log_path: Path) -> str:
    return f"{log_path.stem}__hash"


def _fake_slot_id(type_id: str, config: dict) -> str:
    return f"{type_id}__slot"


def _fake_type_id(inst) -> str:
    return inst.spec_id


class PhaseEScoresPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        fb_scores.set_root(Path(self._tmp.name))

    def tearDown(self) -> None:
        fb_scores.set_root(None)
        self._tmp.cleanup()

    def test_roundtrip_numeric_value(self) -> None:
        fb_scores.save_score(log_id="L__h", slot="imp__s",
                              item_id="E-S-BQ-2", value=2, note="OK")
        got = fb_scores.load_score("L__h", "imp__s", "E-S-BQ-2")
        self.assertEqual(got["value"], 2)
        self.assertEqual(got["note"], "OK")

    def test_nz_value_roundtrips(self) -> None:
        fb_scores.save_score(log_id="L__h", slot="decl__s",
                              item_id="E-S-BQ-1", value="nz")
        got = fb_scores.load_score("L__h", "decl__s", "E-S-BQ-1")
        self.assertEqual(got["value"], "nz")

    def test_gate_yesno_roundtrips(self) -> None:
        fb_scores.save_score(log_id="L__h", slot="imp__s",
                              item_id="E-Sm-Gate", value="nein")
        got = fb_scores.load_score("L__h", "imp__s", "E-Sm-Gate")
        self.assertEqual(got["value"], "nein")

    def test_invalid_value_rejected(self) -> None:
        with self.assertRaises(ValueError):
            fb_scores.save_score(log_id="L__h", slot="x", item_id="E-X",
                                  value=3)
        with self.assertRaises(ValueError):
            fb_scores.save_score(log_id="L__h", slot="x", item_id="E-X",
                                  value="maybe")
        with self.assertRaises(ValueError):
            fb_scores.save_score(log_id="L__h", slot="x", item_id="E-X",
                                  value=True)


class PhaseEFitTests(unittest.TestCase):
    def setUp(self) -> None:
        config_loader.reload()
        items.refresh()
        self._tmp = tempfile.TemporaryDirectory()
        fb_scores.set_root(Path(self._tmp.name))
        # Stub out runtime helpers and log discovery.
        self._patches = [
            patch.object(phase_e, "phase_e_logs",
                         return_value=[Path("Log01_structured.xes")]),
            patch("flex_compare.runner.slot_id", side_effect=_fake_slot_id),
            patch("flex_compare.runner._type_id", side_effect=_fake_type_id),
            patch.object(phase_e, "_safe_log_id", side_effect=_fake_log_id),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        fb_scores.set_root(None)
        self._tmp.cleanup()

    def test_unavailable_without_cells(self) -> None:
        res = phase_e.phase_e_fit("imp", "structured",
                                   state=_FakeState("imp"))
        self.assertFalse(res["available"])
        self.assertIsNone(res["fit"])
        self.assertEqual(res["n_pending"], 4)

    def test_all_twos_yields_100(self) -> None:
        slot = "imp__slot"
        log_id = "Log01_structured__hash"
        for item in ("E-S-BQ-1", "E-S-BQ-2", "E-S-IN-1", "E-S-IN-2"):
            fb_scores.save_score(log_id=log_id, slot=slot, item_id=item, value=2)
        res = phase_e.phase_e_fit("imp", "structured",
                                   state=_FakeState("imp"))
        self.assertTrue(res["available"])
        self.assertEqual(res["points"], 8)
        self.assertEqual(res["max"], 8)
        self.assertEqual(res["fit"], 100.0)
        self.assertTrue(res["complete"])

    def test_nz_counts_as_zero_in_denominator(self) -> None:
        slot = "decl__slot"
        log_id = "Log01_structured__hash"
        fb_scores.save_score(log_id=log_id, slot=slot,
                              item_id="E-S-BQ-1", value="nz")
        fb_scores.save_score(log_id=log_id, slot=slot,
                              item_id="E-S-BQ-2", value=2)
        fb_scores.save_score(log_id=log_id, slot=slot,
                              item_id="E-S-IN-1", value=2)
        fb_scores.save_score(log_id=log_id, slot=slot,
                              item_id="E-S-IN-2", value=2)
        res = phase_e.phase_e_fit("decl", "structured",
                                   state=_FakeState("decl"))
        # nz counts 0 in numerator, +1 item (worth 2 max) in denom.
        self.assertEqual(res["points"], 6)
        self.assertEqual(res["max"], 8)
        self.assertEqual(res["fit"], 75.0)
        self.assertEqual(res["n_nz"], 1)


class PhaseEMacroAverageTests(unittest.TestCase):
    """E-Fit(K) is the mean of the per-log Fits, not the pooled ratio."""

    def setUp(self) -> None:
        config_loader.reload()
        items.refresh()
        self._tmp = tempfile.TemporaryDirectory()
        fb_scores.set_root(Path(self._tmp.name))
        self._patches = [
            patch.object(phase_e, "phase_e_logs",
                         return_value=[Path("Log01_structured.xes"),
                                       Path("Log04_structured.xes")]),
            patch("flex_compare.runner.slot_id", side_effect=_fake_slot_id),
            patch("flex_compare.runner._type_id", side_effect=_fake_type_id),
            patch.object(phase_e, "_safe_log_id", side_effect=_fake_log_id),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        fb_scores.set_root(None)
        self._tmp.cleanup()

    def test_fit_is_mean_of_per_log_fits(self) -> None:
        slot = "imp__slot"
        # Log01: all four items = 2 → per-log fit 100.
        for item in ("E-S-BQ-1", "E-S-BQ-2", "E-S-IN-1", "E-S-IN-2"):
            fb_scores.save_score(log_id="Log01_structured__hash", slot=slot,
                                  item_id=item, value=2)
        # Log04: one item = 1, rest pending → per-log fit 50.
        fb_scores.save_score(log_id="Log04_structured__hash", slot=slot,
                              item_id="E-S-BQ-1", value=1)
        res = phase_e.phase_e_fit("imp", "structured", state=_FakeState("imp"))
        # Mean of per-log fits: (100 + 50) / 2 = 75, not pooled 9/10 = 90.
        self.assertEqual(res["fit"], 75.0)
        self.assertEqual(res["fit_pooled"], 90.0)
        self.assertEqual(res["n_logs_scored"], 2)
        self.assertEqual(res["per_log"]["Log01_structured"]["fit"], 100.0)
        self.assertEqual(res["per_log"]["Log04_structured"]["fit"], 50.0)
        self.assertEqual(res["per_log"]["Log04_structured"]["points"], 1)
        self.assertEqual(res["per_log"]["Log04_structured"]["max"], 2)


# The Semi E-Sm-Gate and E-Sm-SF-1 were removed from the methodology; Phase E
# is now four ungated items per class, so the former gate-forcing tests no
# longer apply.


if __name__ == "__main__":
    unittest.main()
