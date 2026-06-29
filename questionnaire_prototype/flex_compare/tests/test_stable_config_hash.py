"""Stable config hash is process- and restart-independent (CQ1.a).

Python's default ``hash()`` is salted via ``PYTHONHASHSEED``, so a dict's
``hash(...)`` differs across processes. The runner needs a deterministic
value because the same configured miner should hit the same cache slot
across restarts. The hash is checked across a subprocess boundary to make
sure no in-process accident hides a regression.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from flex_compare.runner import stable_config_hash, slot_id


_SUBPROCESS_HASH = (
    "import json, sys\n"
    "from flex_compare.runner import stable_config_hash\n"
    "cfg = json.loads(sys.argv[1])\n"
    "print(stable_config_hash(cfg))\n"
)


def _hash_in_subprocess(cfg: dict) -> str:
    import json

    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_HASH, json.dumps(cfg)],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


class StableConfigHashTests(unittest.TestCase):
    def test_same_config_same_hash_in_process(self) -> None:
        self.assertEqual(
            stable_config_hash({"a": 1, "b": 2}),
            stable_config_hash({"a": 1, "b": 2}),
        )

    def test_key_order_does_not_matter(self) -> None:
        self.assertEqual(
            stable_config_hash({"a": 1, "b": 2}),
            stable_config_hash({"b": 2, "a": 1}),
        )

    def test_different_configs_different_hashes(self) -> None:
        h1 = stable_config_hash({"a": 1, "b": 2})
        h2 = stable_config_hash({"a": 1, "b": 3})
        self.assertNotEqual(h1, h2)

    def test_hash_stable_across_subprocesses(self) -> None:
        cfg = {"support": 0.04, "confidence": 0.85, "trace_support": 0.125}
        h_here = stable_config_hash(cfg)
        h_sub_1 = _hash_in_subprocess(cfg)
        h_sub_2 = _hash_in_subprocess(cfg)
        self.assertEqual(h_here, h_sub_1)
        self.assertEqual(h_sub_1, h_sub_2)

    def test_slot_id_shape(self) -> None:
        slot = slot_id("pm4py", {"algorithm": "heuristics"})
        self.assertTrue(slot.startswith("pm4py__"))
        self.assertEqual(len(slot.split("__")[1]), 8)


if __name__ == "__main__":
    unittest.main()
