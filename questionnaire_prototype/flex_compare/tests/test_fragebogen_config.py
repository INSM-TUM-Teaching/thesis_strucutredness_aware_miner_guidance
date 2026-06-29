"""YAML config loading + schema validation (T+E architecture)."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from flex_compare.fragebogen import config_loader, items
from flex_compare.fragebogen.config_loader import ConfigError


_VALID = """\
meta:
  class: structured
  phase_t_max: 1
  phase_e_max: 2
  combination: {mode: separate}
phase_t:
  - id: T-S-BQ-1
    axis: BQ
    title: t
    question: q
    doku_hint: hint
    allow_nz: false
    split_candidate: false
    scale:
      - {value: "ja",   label: a}
      - {value: "nein", label: b}
    phase_t_seed:
      imp: {value: "ja"}
phase_e:
  - id: E-S-BQ-1
    axis: BQ
    title: t
    question: q
    route: r
    allow_nz: true
    scale:
      - {score: 2, label: a}
      - {score: 1, label: b}
      - {score: 0, label: c}
"""


class _TempConfig:
    """Point the loader at a temp config dir, then restore on exit."""

    def __init__(self, **files: str) -> None:
        self.files = files

    def __enter__(self) -> Path:
        self._orig = config_loader.CONFIG_DIR
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        for name, content in self.files.items():
            (d / f"{name}.yaml").write_text(textwrap.dedent(content),
                                            encoding="utf-8")
        config_loader.CONFIG_DIR = d
        return d

    def __exit__(self, *exc) -> None:
        config_loader.CONFIG_DIR = self._orig
        self._tmp.cleanup()
        config_loader.reload()
        items.refresh()


class FragebogenConfigShippedTests(unittest.TestCase):
    """All three shipped class files load and carry the documented item counts."""

    def setUp(self) -> None:
        config_loader.reload()
        items.refresh()

    def test_three_classes_load(self) -> None:
        cfg = config_loader.load()
        self.assertEqual(set(cfg), {"structured", "semi", "loosely"})

    def test_structured_phase_t_has_three_yesno_items(self) -> None:
        s = config_loader.load()["structured"]
        ids = [i["id"] for i in s["phase_t"]]
        self.assertEqual(ids, ["T-S-BQ-1", "T-S-BQ-2", "T-S-SF-1"])
        for item in s["phase_t"]:
            values = {row["value"] for row in item["scale"]}
            self.assertEqual(values, {"ja", "nein"})

    def test_structured_phase_e_has_four_012_items(self) -> None:
        s = config_loader.load()["structured"]
        ids = [i["id"] for i in s["phase_e"]]
        self.assertEqual(ids,
                         ["E-S-BQ-1", "E-S-BQ-2", "E-S-IN-1", "E-S-IN-2"])
        for item in s["phase_e"]:
            scores = {row["score"] for row in item["scale"]}
            self.assertEqual(scores, {0, 1, 2})

    def test_semi_phase_t_three_phase_e_four_no_gate(self) -> None:
        sm = config_loader.load()["semi"]
        self.assertEqual(len(sm["phase_t"]), 3)
        self.assertEqual(len(sm["phase_e"]), 4)
        self.assertIsNone(sm["phase_e_gate"])

    def test_loosely_phase_t_three_phase_e_four(self) -> None:
        l = config_loader.load()["loosely"]
        self.assertEqual(len(l["phase_t"]), 3)
        self.assertEqual(len(l["phase_e"]), 4)
        self.assertIsNone(l["phase_e_gate"])

    def test_structured_meta_carries_phase_maxes(self) -> None:
        meta = config_loader.load()["structured"]["meta"]
        self.assertEqual(meta["phase_t_max"], 3)
        self.assertEqual(meta["phase_e_max"], 8)
        self.assertEqual(meta["combination"]["mode"], "weighted")

    def test_allow_nz_flags_match_doc(self) -> None:
        cfg = config_loader.load()
        nz_t = {i["id"] for cls in cfg.values()
                for i in cls["phase_t"] if i.get("allow_nz")}
        nz_e = {i["id"] for cls in cfg.values()
                for i in cls["phase_e"] if i.get("allow_nz")}
        self.assertEqual(nz_t, {"T-Sm-SF-1"})
        self.assertEqual(nz_e, {"E-S-BQ-1", "E-S-BQ-2"})

    def test_split_candidates_match_doc(self) -> None:
        cfg = config_loader.load()
        splits = {i["id"] for cls in cfg.values()
                  for i in cls["phase_t"] if i.get("split_candidate")}
        self.assertEqual(splits, {"T-Sm-SF-1", "T-Sm-BQ-1", "T-Sm-BQ-2"})


class FragebogenConfigSchemaTests(unittest.TestCase):
    def test_valid_temp_config_round_trips(self) -> None:
        with _TempConfig(structured=_VALID):
            config_loader.reload()
            cfg = config_loader.load()
            self.assertEqual([i["id"] for i in cfg["structured"]["phase_t"]],
                             ["T-S-BQ-1"])
            self.assertEqual([i["id"] for i in cfg["structured"]["phase_e"]],
                             ["E-S-BQ-1"])

    def test_missing_meta_raises(self) -> None:
        bad = "phase_t:\n  - {id: T-X}\n"
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_unknown_class_raises(self) -> None:
        bad = _VALID.replace("class: structured", "class: chaotic")
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_t_id_must_start_with_T(self) -> None:
        bad = _VALID.replace("id: T-S-BQ-1", "id: S-BQ-1")
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_e_id_must_start_with_E(self) -> None:
        bad = _VALID.replace("id: E-S-BQ-1", "id: B-S-BQ-1")
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_t_scale_must_be_yes_no(self) -> None:
        bad = _VALID.replace(
            '      - {value: "ja",   label: a}\n'
            '      - {value: "nein", label: b}\n',
            '      - {score: 2, label: a}\n'
            '      - {score: 1, label: b}\n'
            '      - {score: 0, label: c}\n')
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_e_scale_must_cover_2_1_0(self) -> None:
        bad = _VALID.replace("      - {score: 0, label: c}\n", "")
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_t_seed_nz_requires_allow_nz(self) -> None:
        bad = _VALID.replace('imp: {value: "ja"}',
                             'imp: {value: "nz"}')
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_combination_mode_weighted_is_valid(self) -> None:
        ok = _VALID.replace("mode: separate", "mode: weighted")
        with _TempConfig(structured=ok):
            config_loader.reload()
            meta = config_loader.load()["structured"]["meta"]
            self.assertEqual(meta["combination"]["mode"], "weighted")

    def test_combination_mode_unknown_raises(self) -> None:
        bad = _VALID.replace("mode: separate", "mode: chaotic")
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()

    def test_phase_e_gate_scored_true_raises(self) -> None:
        bad = _VALID + textwrap.dedent("""\
            phase_e_gate:
              id: E-X-Gate
              question: q
              scored: true
              scale:
                - {value: "ja",   label: a}
                - {value: "nein", label: b}
            """)
        with _TempConfig(broken=bad):
            with self.assertRaises(ConfigError):
                config_loader.reload()


if __name__ == "__main__":
    unittest.main()
