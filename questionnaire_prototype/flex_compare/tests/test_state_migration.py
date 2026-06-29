"""Schema migration of .flex_compare/state.json (T3.a).

Frozen fixtures live under ``tests/fixtures/state_v<N>.json``. A pre-version-0
file (no ``version`` field) is treated as v0 and migrated to current. Unknown
future versions fail loudly rather than silently dropping fields.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from flex_compare import state as fc_state
from flex_compare.state import CURRENT_VERSION, FlexState, StateError


_FIXTURES = Path(__file__).parent / "fixtures"


class StateMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        fc_state.set_state_dir(Path(self._tmp.name))

    def tearDown(self) -> None:
        fc_state.set_state_dir(None)
        self._tmp.cleanup()

    def _place(self, fixture_name: str) -> None:
        shutil.copy2(_FIXTURES / fixture_name,
                     fc_state.state_dir() / "state.json")
        fc_state.state_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy2(_FIXTURES / fixture_name,
                     fc_state.state_dir() / "state.json")

    def test_v0_migrates_to_current(self) -> None:
        self._place("state_v0.json")
        loaded = fc_state.load()
        self.assertEqual(loaded.version, CURRENT_VERSION)
        # Fields survive the migration.
        self.assertEqual(loaded.selected_log, "/path/to/Log01.xes")

    def test_v1_loads_without_migration(self) -> None:
        self._place("state_v1.json")
        loaded = fc_state.load()
        self.assertEqual(loaded.version, CURRENT_VERSION)
        self.assertEqual(loaded.selected_log, "/path/to/Log02.xes")
        self.assertEqual(len(loaded.instances), 1)
        self.assertEqual(loaded.instances[0].spec_id, "minerful")
        self.assertEqual(loaded.instances[0].config["support"], 0.04)

    def test_v99_fails_loudly(self) -> None:
        self._place("state_v99.json")
        with self.assertRaises(StateError) as cm:
            fc_state.load()
        self.assertIn("99", str(cm.exception))
        self.assertIn("CURRENT_VERSION", str(cm.exception))

    def test_save_round_trips_at_current_version(self) -> None:
        # Loading v0 then saving should write back the migrated v1 shape.
        self._place("state_v0.json")
        loaded = fc_state.load()
        fc_state.save(loaded)
        raw = json.loads((fc_state.state_dir() / "state.json").read_text())
        self.assertEqual(raw["version"], CURRENT_VERSION)


if __name__ == "__main__":
    unittest.main()
