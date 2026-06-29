"""FlexState round-trip + atomic-write semantics."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from flex_compare import state as fc_state
from flex_compare.state import (
    CURRENT_VERSION, FlexState, InlineSpec, MinerInstance, new_instance_id,
)
from flex_compare.internal.shared.registry.param_schema import ParamSpec


class FlexStateRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        fc_state.set_state_dir(Path(self._tmp.name))

    def tearDown(self) -> None:
        fc_state.set_state_dir(None)
        self._tmp.cleanup()

    def test_empty_state_round_trip(self) -> None:
        s = FlexState()
        path = fc_state.save(s)
        self.assertTrue(path.is_file())
        loaded = fc_state.load()
        self.assertEqual(loaded.selected_log, None)
        self.assertEqual(loaded.instances, [])
        self.assertEqual(loaded.version, CURRENT_VERSION)

    def test_registry_instance_round_trip(self) -> None:
        inst = MinerInstance(
            id=new_instance_id(),
            spec_source="registry",
            spec_id="minerful",
            label="My MINERful",
            config={"support": 0.05, "confidence": 0.9},
        )
        s = FlexState(selected_log="/foo/Log01.xes",
                      arm_thresholds={"temporal": 0.8, "existential": 0.9},
                      instances=[inst])
        fc_state.save(s)
        loaded = fc_state.load()
        self.assertEqual(loaded.selected_log, "/foo/Log01.xes")
        self.assertEqual(loaded.arm_thresholds["temporal"], 0.8)
        self.assertEqual(len(loaded.instances), 1)
        self.assertEqual(loaded.instances[0].id, inst.id)
        self.assertEqual(loaded.instances[0].config["confidence"], 0.9)

    def test_inline_module_instance_round_trip(self) -> None:
        inline = InlineSpec(
            label="My script", paradigm="imperativ",
            runner_kind="module", entry_point="my_pkg:run",
            config_schema=(ParamSpec("foo", "Foo", "number", 1),),
        )
        inst = MinerInstance(
            id=new_instance_id(), spec_source="inline", label="My script",
            inline_spec=inline, config={"foo": 42},
        )
        s = FlexState(instances=[inst])
        fc_state.save(s)
        loaded = fc_state.load()
        self.assertEqual(loaded.instances[0].inline_spec.entry_point, "my_pkg:run")
        # config_schema must round-trip back into ParamSpec instances.
        schema = loaded.instances[0].inline_spec.config_schema
        self.assertEqual(len(schema), 1)
        self.assertEqual(schema[0].key, "foo")

    def test_inline_executable_with_options_round_trip(self) -> None:
        # Options round-trip through JSON as lists; the loader must coerce
        # back to tuples so ParamSpec stays hashable.
        inline = InlineSpec(
            label="MyExec", paradigm="imperativ", runner_kind="executable",
            command_template="java -jar m.jar --log {log} --out {outdir}",
            output_format="pnml", output_pattern="model.pnml",
            config_schema=(ParamSpec(
                "algo", "Algo", "dropdown", "x",
                options=(("X", "x"), ("Y", "y")),
                visible_when=(("other", 1),),
            ),),
        )
        inst = MinerInstance(
            id=new_instance_id(), spec_source="inline", label="MyExec",
            inline_spec=inline, config={"algo": "y"},
        )
        s = FlexState(instances=[inst])
        fc_state.save(s)
        loaded = fc_state.load()
        spec = loaded.instances[0].inline_spec.config_schema[0]
        self.assertEqual(spec.options, (("X", "x"), ("Y", "y")))
        self.assertEqual(spec.visible_when, (("other", 1),))

    def test_save_is_atomic_no_partial_files(self) -> None:
        s = FlexState(selected_log="/foo")
        fc_state.save(s)
        # No leftover .tmp-* files.
        leftovers = list(fc_state.state_dir().glob("*.tmp-*"))
        self.assertEqual(leftovers, [])

    def test_mutation_helpers(self) -> None:
        s = FlexState()
        inst1 = MinerInstance(id="a", spec_source="registry", spec_id="imp",
                              label="A", config={"noise_threshold": 0.0})
        inst2 = MinerInstance(id="b", spec_source="registry", spec_id="decl",
                              label="B", config={"support": 0.05})
        fc_state.add_instance(s, inst1)
        fc_state.add_instance(s, inst2)
        self.assertEqual([i.id for i in s.instances], ["a", "b"])
        fc_state.update_instance_config(s, "a", {"noise_threshold": 0.2})
        self.assertEqual(fc_state.find_instance(s, "a").config["noise_threshold"], 0.2)
        fc_state.remove_instance(s, "a")
        self.assertEqual([i.id for i in s.instances], ["b"])


if __name__ == "__main__":
    unittest.main()
