"""Golden fixtures for format_import (T1.a).

PNML and MINERful-native Declare-JSON round-trips: hand-built fixtures are
parsed, structural properties asserted, and the integration with
:func:`extract_metrics_by_paradigm` is exercised so importer / metric-proxy
drift fails fast.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from flex_compare.internal.shared.metrics.metric_proxies import extract_metrics_by_paradigm

from flex_compare import format_import


_PNML = """<?xml version="1.0" encoding="UTF-8"?>
<pnml>
  <net id="n1" type="http://www.pnml.org/version-2009/grammar/pnmlcoremodel">
    <name><text>fake</text></name>
    <page id="p1">
      <place id="p_start"><name><text>start</text></name><initialMarking><text>1</text></initialMarking></place>
      <place id="p_mid"><name><text>mid</text></name></place>
      <place id="p_end"><name><text>end</text></name></place>
      <transition id="t_a"><name><text>A</text></name></transition>
      <transition id="t_b"><name><text>B</text></name></transition>
      <arc id="a1" source="p_start" target="t_a"/>
      <arc id="a2" source="t_a" target="p_mid"/>
      <arc id="a3" source="p_mid" target="t_b"/>
      <arc id="a4" source="t_b" target="p_end"/>
    </page>
    <finalmarkings><marking><place idref="p_end"><text>1</text></place></marking></finalmarkings>
  </net>
</pnml>
"""

_MINERFUL_JSON = {
    "processSchema": {
        "constraints": [
            {"template": "Response",
             "parameters": [["A"], ["B"]],
             "support": 0.95, "confidence": 0.95},
            {"template": "Precedence",
             "parameters": [["A"], ["B"]],
             "support": 1.0, "confidence": 1.0},
            {"template": "Init",
             "parameters": [["A"]],
             "support": 1.0, "confidence": 1.0},
        ]
    },
    "activities": ["A", "B", "C"],
}

_RUM_JSON = {
    "ruleSets": [{"id": "ruleset1", "rules": []}],
}


class FormatImportPnmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._pnml = self._dir / "model.pnml"
        self._pnml.write_text(_PNML)
        self._log = self._find_log()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _find_log(self) -> Path | None:
        from flex_compare.internal.shared.paths import PROJECT_ROOT

        for candidate in sorted((PROJECT_ROOT / "data" / "with-case-ids").glob("Log01_*.xes")):
            return candidate
        return None

    def test_pnml_roundtrip_marks_imported_keys_as_none(self) -> None:
        if self._log is None:
            self.skipTest("no XES log available")
        try:
            import pm4py  # noqa: F401
        except Exception:
            self.skipTest("pm4py not available")

        result = format_import.import_pnml(self._pnml, self._log, output_dir=self._dir)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["imported_from"], "pnml")
        m = result["metrics"]
        # Recoverable metrics get real values.
        self.assertIsInstance(m["replay_fitness"], float)
        self.assertIsInstance(m["etc_precision"], float)
        # Imported-source path null-out is the paradigm-proxy's job.
        metrics = extract_metrics_by_paradigm("imperativ", result, source="imported")
        self.assertIsNone(metrics["process_tree_depth"])
        self.assertIsNone(metrics["extended_cardoso_cfc"])
        self.assertTrue(metrics["_imported"])


class FormatImportDeclareJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._json = self._dir / "model.json"
        self._json.write_text(json.dumps(_MINERFUL_JSON))
        self._log = self._dir / "Log01.xes"
        self._log.write_text("<log/>")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_minerful_json_yields_density_and_variability(self) -> None:
        result = format_import.import_declare_json(self._json, self._log,
                                                    output_dir=self._dir)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["imported_from"], "declare-json")
        m = result["metrics"]
        # 3 constraints / 3 activities = 1.0
        self.assertAlmostEqual(m["constraint_density"], 1.0)
        # 3 distinct templates / 3 constraints = 1.0
        self.assertAlmostEqual(m["constraint_variability"], 1.0)
        self.assertEqual(m["n_constraints"], 3)
        self.assertEqual(m["n_activities"], 3)

    def test_foreign_dialect_rejected_loudly(self) -> None:
        rum_path = self._dir / "rum_model.json"
        rum_path.write_text(json.dumps(_RUM_JSON))
        with self.assertRaises(ValueError) as cm:
            format_import.import_declare_json(rum_path, self._log,
                                               output_dir=self._dir)
        self.assertIn("dialect not supported", str(cm.exception))

    def test_paradigm_extract_marks_imperative_metrics_as_none(self) -> None:
        result = format_import.import_declare_json(self._json, self._log,
                                                    output_dir=self._dir)
        metrics = extract_metrics_by_paradigm("deklarativ", result, source="imported")
        self.assertTrue(metrics["_imported"])
        # Structural imperative metrics stay None for declarative imports.
        self.assertIsNone(metrics["process_tree_depth"])
        self.assertIsNone(metrics["extended_cardoso_cfc"])


if __name__ == "__main__":
    unittest.main()
