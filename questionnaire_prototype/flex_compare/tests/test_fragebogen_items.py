"""Item catalogue (YAML-backed) + log-class routing (T+E architecture)."""
from __future__ import annotations

import unittest

from flex_compare.fragebogen import config_loader, items
from flex_compare.fragebogen.items import (
    ITEMS,
    class_for_log,
    get_item,
    meta_for_class,
    phase_e_gate_for_class,
    phase_e_items_for_class,
    phase_t_items_for_class,
    phase_t_seed,
    stufe1_for_class,
)

_T_STRUCTURED = ["T-S-BQ-1", "T-S-BQ-2", "T-S-SF-1"]
_E_STRUCTURED = ["E-S-BQ-1", "E-S-BQ-2", "E-S-IN-1", "E-S-IN-2"]
_T_SEMI = ["T-Sm-BQ-1", "T-Sm-BQ-2", "T-Sm-SF-1"]
_E_SEMI = ["E-Sm-BQ-1", "E-Sm-BQ-2", "E-Sm-IN-1", "E-Sm-IN-2"]
_T_LOOSE = ["T-L-BQ-1", "T-L-BQ-2", "T-L-SF-1"]
_E_LOOSE = ["E-L-BQ-1", "E-L-BQ-2", "E-L-IN-1", "E-L-IN-2"]


class FragebogenItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config_loader.reload()
        items.refresh()

    def test_catalogue_has_every_t_and_e_item(self) -> None:
        expected = set(_T_STRUCTURED + _E_STRUCTURED
                       + _T_SEMI + _E_SEMI
                       + _T_LOOSE + _E_LOOSE)
        self.assertEqual(set(ITEMS), expected)

    def test_phase_t_items_per_class(self) -> None:
        self.assertEqual([i["id"] for i in phase_t_items_for_class("structured")],
                         _T_STRUCTURED)
        self.assertEqual([i["id"] for i in phase_t_items_for_class("semi")],
                         _T_SEMI)
        self.assertEqual([i["id"] for i in phase_t_items_for_class("loosely")],
                         _T_LOOSE)

    def test_phase_e_items_per_class(self) -> None:
        self.assertEqual([i["id"] for i in phase_e_items_for_class("structured")],
                         _E_STRUCTURED)
        self.assertEqual([i["id"] for i in phase_e_items_for_class("semi")],
                         _E_SEMI)
        self.assertEqual([i["id"] for i in phase_e_items_for_class("loosely")],
                         _E_LOOSE)

    def test_phase_e_gate_removed_from_all_classes(self) -> None:
        # The Semi E-Sm-Gate (and E-Sm-SF-1) were removed; Phase E is now four
        # items per class with no gate anywhere.
        for cls in ("structured", "semi", "loosely"):
            self.assertIsNone(phase_e_gate_for_class(cls))

    def test_phase_t_scale_is_yes_no(self) -> None:
        for cls in ("structured", "semi", "loosely"):
            for item in phase_t_items_for_class(cls):
                values = {row["value"] for row in item["scale"]}
                self.assertEqual(values, {"ja", "nein"}, item["id"])

    def test_phase_e_scale_is_012(self) -> None:
        for cls in ("structured", "semi", "loosely"):
            for item in phase_e_items_for_class(cls):
                scores = {row["score"] for row in item["scale"]}
                self.assertEqual(scores, {0, 1, 2}, item["id"])

    def test_get_item_injects_id_or_returns_none(self) -> None:
        item = get_item("T-S-BQ-1")
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], "T-S-BQ-1")
        self.assertEqual(item["phase"], "T")
        self.assertIsNone(get_item("does-not-exist"))

    def test_stufe1_paradigm_routing_exists(self) -> None:
        for cls in ("structured", "semi", "loosely"):
            ids = [s["id"] for s in stufe1_for_class(cls)]
            self.assertIn("S1.1", ids)

    def test_meta_exposes_phase_maxes(self) -> None:
        # Every class is now 3 Phase-T items (max 3) and 4 Phase-E items (max 8).
        for cls in ("structured", "semi", "loosely"):
            self.assertEqual(meta_for_class(cls)["phase_t_max"], 3)
            self.assertEqual(meta_for_class(cls)["phase_e_max"], 8)

    def test_phase_t_seed_carries_calibration_miners(self) -> None:
        seed = phase_t_seed("T-S-BQ-1")
        self.assertEqual(seed["imp"]["value"], "ja")
        self.assertEqual(seed["decl"]["value"], "ja")
        self.assertEqual(seed["fus"]["value"], "ja")
        self.assertEqual(seed["pm4-heuristics"]["value"], "nein")

    def test_phase_t_seed_nz_only_at_allow_nz(self) -> None:
        # T-Sm-SF-1 is the documented allow_nz=true item.
        seed = phase_t_seed("T-Sm-SF-1")
        self.assertEqual(seed["imp"]["value"], "nz")
        self.assertEqual(seed["decl"]["value"], "nz")
        self.assertEqual(seed["fus"]["value"], "ja")

    def test_class_for_log_routes_three_calibration_logs(self) -> None:
        self.assertEqual(
            class_for_log("/data/with-case-ids/Log01_structured.xes"),
            "structured")
        self.assertEqual(
            class_for_log("/data/with-case-ids/Log06_semiStructured.xes"),
            "semi")
        self.assertEqual(
            class_for_log("/data/with-case-ids/Log08_looselyStructured.xes"),
            "loosely")


if __name__ == "__main__":
    unittest.main()
