"""run_instance dispatches correctly, hits cache by config-hash slot."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flex_compare.internal.shared.cache import result_cache

from flex_compare import state as fc_state
from flex_compare.runner import (
    extract_metrics, RunOutcome, run_instance, slot_id, stable_config_hash,
)
from flex_compare.state import InlineSpec, MinerInstance, new_instance_id


def _stub_adapter(*, log_path, output_root, run_id, bearbeiter, export_pdf=False, **config):
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "success",
        "log_path": str(log_path),
        "output_dir": str(out_dir),
        "metrics": {
            "replay_fitness": 0.95,
            "etc_precision": 0.80,
            "process_tree_depth": 4,
        },
        "echoed_config": dict(config),
    }


def _stub_adapter_decl(*, log_path, output_root, run_id, bearbeiter, export_pdf=False, **config):
    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "success",
        "log_path": str(log_path),
        "output_dir": str(out_dir),
        "metrics": {
            "vacuity_rate": 0.10,
            "non_vacuous_satisfaction_rate": 0.92,
            "constraint_density": 1.4,
        },
    }


class RunnerDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_tmp = tempfile.TemporaryDirectory()
        fc_state.set_state_dir(Path(self._tmp.name))
        result_cache.set_cache_root(Path(self._cache_tmp.name))
        # Create a tiny "log file" — runner only checks for existence.
        self._log = Path(self._tmp.name) / "Log01.xes"
        self._log.write_text("<log/>")

    def tearDown(self) -> None:
        fc_state.set_state_dir(None)
        result_cache.set_cache_root(None)
        self._tmp.cleanup()
        self._cache_tmp.cleanup()

    def _registry_instance(self, spec_id: str = "imp",
                           config: dict | None = None) -> MinerInstance:
        return MinerInstance(
            id=new_instance_id(), spec_source="registry", spec_id=spec_id,
            label=spec_id, config=config or {"noise_threshold": 0.0},
        )

    def test_module_dispatch_hits_cache_on_second_call(self) -> None:
        inst = self._registry_instance()
        with patch("flex_compare.internal.shared.registry.miner_registry.get") as mock_get:
            spec = type("S", (), {
                "id": "imp", "label": "Imp", "short": "Imp",
                "paradigm": "imperativ", "anchor_class": "structured",
                "entry_point": "tests.fake:run", "runner_kind": "module",
                "artifact_keys": (), "config_schema": (),
                "fixed_kwargs": (),
            })()
            mock_get.return_value = spec
            with patch("flex_compare.runner._import_entry_point",
                       return_value=_stub_adapter):
                outcome1 = run_instance(inst, self._log)
                outcome2 = run_instance(inst, self._log)

        self.assertEqual(outcome1.status, "ok")
        self.assertFalse(outcome1.cache_hit)
        self.assertEqual(outcome2.status, "ok")
        self.assertTrue(outcome2.cache_hit)

    def test_remove_and_readd_with_same_config_hits_cache(self) -> None:
        inst_a = self._registry_instance(config={"noise_threshold": 0.0})
        inst_b = self._registry_instance(config={"noise_threshold": 0.0})  # new uuid, same cfg
        self.assertNotEqual(inst_a.id, inst_b.id)

        # The slot is keyed on (type_id, config_hash) only — not on instance.id.
        self.assertEqual(slot_id("imp", inst_a.config), slot_id("imp", inst_b.config))

        with patch("flex_compare.runner._import_entry_point",
                   return_value=_stub_adapter):
            first = run_instance(inst_a, self._log)
            second = run_instance(inst_b, self._log)

        self.assertEqual(first.status, "ok")
        self.assertFalse(first.cache_hit)
        self.assertEqual(second.status, "ok")
        self.assertTrue(second.cache_hit)

    def test_force_bypasses_cache(self) -> None:
        inst = self._registry_instance()
        with patch("flex_compare.runner._import_entry_point",
                   return_value=_stub_adapter):
            run_instance(inst, self._log)
            forced = run_instance(inst, self._log, force=True)
        self.assertFalse(forced.cache_hit)

    def test_two_configs_get_separate_slots(self) -> None:
        inst1 = self._registry_instance(config={"noise_threshold": 0.0})
        inst2 = self._registry_instance(config={"noise_threshold": 0.5})
        with patch("flex_compare.runner._import_entry_point",
                   return_value=_stub_adapter):
            o1 = run_instance(inst1, self._log)
            o2 = run_instance(inst2, self._log)
        self.assertFalse(o1.cache_hit)
        self.assertFalse(o2.cache_hit, "different config must not collide with first slot")

    def test_extract_metrics_paradigm_dispatch(self) -> None:
        # Imperative paradigm picks up replay_fitness from result["metrics"].
        inst_imp = self._registry_instance("imp")
        m = extract_metrics(inst_imp, {"metrics": {"replay_fitness": 0.7,
                                                    "etc_precision": 0.6}})
        self.assertAlmostEqual(m["replay_fitness"], 0.7)
        self.assertAlmostEqual(m["etc_precision"], 0.6)

        # Declarative paradigm uses the vacuity-family keys instead.
        inst_decl = self._registry_instance("decl")
        m2 = extract_metrics(inst_decl, {"metrics": {"vacuity_rate": 0.15,
                                                      "non_vacuous_satisfaction_rate": 0.9}})
        self.assertAlmostEqual(m2["vacuity_rate"], 0.15)
        self.assertAlmostEqual(m2["non_vacuous_satisfaction_rate"], 0.9)

    def test_imported_source_marks_unrecoverable_keys(self) -> None:
        inst = self._registry_instance("imp")
        m = extract_metrics(inst, {"metrics": {"replay_fitness": 0.7,
                                                "process_tree_depth": 4},
                                    "_imported": True})
        # Replay survives, tree-depth gets nullified, _imported flag is set.
        self.assertAlmostEqual(m["replay_fitness"], 0.7)
        self.assertIsNone(m["process_tree_depth"])
        self.assertIsNone(m["extended_cardoso_cfc"])
        self.assertTrue(m["_imported"])


if __name__ == "__main__":
    unittest.main()
