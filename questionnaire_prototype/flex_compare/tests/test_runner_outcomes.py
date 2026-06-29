"""custom-exec subprocess failure modes (T2.a).

Each fake-miner Python script under ``tests/fixtures/fake_miners/`` simulates
one failure mode; ``run_instance`` is exercised end-to-end and the returned
:class:`RunOutcome.status` is asserted against the expected discriminator.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from flex_compare.internal.shared.cache import result_cache

from flex_compare import state as fc_state
from flex_compare.runner import RunOutcome, run_instance
from flex_compare.state import InlineSpec, MinerInstance, new_instance_id


_FIXTURES = Path(__file__).parent / "fixtures" / "fake_miners"


def _exec_instance(
    script_name: str,
    timeout_sec: int = 600,
    output_pattern: str = "model.pnml",
    output_format: str = "pnml",
) -> MinerInstance:
    script = _FIXTURES / script_name
    template = f"{sys.executable} {script} --log {{log}} --out {{outdir}}"
    return MinerInstance(
        id=new_instance_id(),
        spec_source="inline",
        label=script_name,
        config={},
        inline_spec=InlineSpec(
            label=script_name,
            paradigm="imperativ",
            runner_kind="executable",
            command_template=template,
            output_format=output_format,
            output_pattern=output_pattern,
        ),
        timeout_sec=timeout_sec,
    )


class RunnerOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_tmp = tempfile.TemporaryDirectory()
        fc_state.set_state_dir(Path(self._tmp.name))
        result_cache.set_cache_root(Path(self._cache_tmp.name))
        self._log = Path(self._tmp.name) / "Log01.xes"
        self._log.write_text("<log/>")

    def tearDown(self) -> None:
        fc_state.set_state_dir(None)
        result_cache.set_cache_root(None)
        self._tmp.cleanup()
        self._cache_tmp.cleanup()

    def test_timeout(self) -> None:
        inst = _exec_instance("timeout.py", timeout_sec=2)
        outcome = run_instance(inst, self._log)
        self.assertEqual(outcome.status, "timeout")
        self.assertIn("timed out", outcome.error_summary)
        self.assertIsNotNone(outcome.exec_log_path)

    def test_nonzero_exit(self) -> None:
        inst = _exec_instance("exit1.py")
        outcome = run_instance(inst, self._log)
        self.assertEqual(outcome.status, "nonzero")
        self.assertIn("exit code 1", outcome.error_summary)
        self.assertTrue(outcome.exec_log_path.is_file())
        # stderr ends up in _exec.log
        log_text = outcome.exec_log_path.read_text()
        self.assertIn("intentional failure", log_text)

    def test_output_missing(self) -> None:
        inst = _exec_instance("no_output.py")
        outcome = run_instance(inst, self._log)
        self.assertEqual(outcome.status, "output_missing")
        self.assertIn("not found", outcome.error_summary)

    def test_parse_error(self) -> None:
        inst = _exec_instance("bad_pnml.py")
        outcome = run_instance(inst, self._log)
        self.assertEqual(outcome.status, "parse_error")
        # The original exception type leaks into the summary so we can debug.
        self.assertTrue(any(t in outcome.error_summary
                            for t in ("Exception", "Error", "Parse")))

    def test_ok_with_pnml(self) -> None:
        # pm4py is heavy + slow → only attempt if available.
        try:
            import pm4py  # noqa: F401
        except Exception:
            self.skipTest("pm4py not available")
        # Need a real XES log so pm4py can do replay.
        real_log = self._find_real_log()
        if real_log is None:
            self.skipTest("no real XES log available for ok-path replay")
        inst = _exec_instance("ok.py")
        outcome = run_instance(inst, real_log)
        self.assertEqual(outcome.status, "ok", f"summary: {outcome.error_summary}")
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.result.get("imported_from"), "pnml")

    def _find_real_log(self) -> Path | None:
        from flex_compare.internal.shared.paths import PROJECT_ROOT

        for candidate in sorted((PROJECT_ROOT / "data" / "with-case-ids").glob("Log01_*.xes")):
            return candidate
        return None


if __name__ == "__main__":
    unittest.main()
