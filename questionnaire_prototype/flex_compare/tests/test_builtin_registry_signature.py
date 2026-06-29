"""Always-on registry self-consistency (T4.b).

For each built-in :class:`MinerSpec`:

* import the ``entry_point`` (typo-protected — a stale string would only
  surface on first manual run otherwise),
* check the adapter signature accepts every ``ParamSpec.key`` plus the
  required adapter kwargs (``log_path``, ``output_root``, ``run_id``),
* check ``paradigm`` is in the legal set,
* check :func:`extract_metrics_by_paradigm` is callable with the paradigm
  string without KeyError-drift.
"""
from __future__ import annotations

import importlib
import inspect
import unittest

from flex_compare.internal.shared.metrics.metric_proxies import extract_metrics_by_paradigm
from flex_compare.internal.shared.registry import miner_registry


_LEGAL_PARADIGMS = {"imperativ", "deklarativ", "hybrid"}
_REQUIRED_ADAPTER_KWARGS = {"log_path", "output_root", "run_id"}

# Kwargs the runner always supplies in ``_dispatch_module`` regardless of schema.
# Keep this set in sync with the literal call in ``flex_compare/runner.py``.
_RUNNER_STANDARD_KWARGS = {
    "log_path", "output_root", "run_id", "bearbeiter",
    "export_pdf", "preprocessing_note",
}


def _resolve(entry_point: str):
    module_path, _, func_name = entry_point.partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _accepted_kwargs(func) -> tuple[set[str], bool]:
    """Return (named kwargs, has_var_kwargs)."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return set(), True
    named: set[str] = set()
    has_var_kwargs = False
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_var_kwargs = True
        else:
            named.add(name)
    return named, has_var_kwargs


def _required_kwargs(func) -> tuple[set[str], bool]:
    """Return (kwargs without a default, has_var_kwargs)."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return set(), True
    required: set[str] = set()
    has_var_kwargs = False
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_var_kwargs = True
        elif param.default is inspect.Parameter.empty:
            required.add(name)
    return required, has_var_kwargs


class BuiltinRegistrySignatureTests(unittest.TestCase):
    def test_every_entry_point_resolves(self) -> None:
        for spec in miner_registry.miner_specs():
            if not spec.entry_point:
                continue
            with self.subTest(miner=spec.id):
                func = _resolve(spec.entry_point)
                self.assertTrue(callable(func),
                                f"{spec.entry_point!r} did not resolve to a callable")

    def test_adapter_accepts_required_kwargs(self) -> None:
        for spec in miner_registry.miner_specs():
            if not spec.entry_point:
                continue
            with self.subTest(miner=spec.id):
                func = _resolve(spec.entry_point)
                named, has_var = _accepted_kwargs(func)
                if has_var:
                    continue  # **kwargs accepts anything
                missing = _REQUIRED_ADAPTER_KWARGS - named
                self.assertFalse(
                    missing,
                    f"{spec.id}: adapter signature missing required kwargs: {missing}",
                )

    def test_adapter_accepts_every_schema_key(self) -> None:
        # A schema entry that carries ``kwarg_bundle="foo"`` arrives at the
        # adapter as part of ``foo={...}``; only the bundle name has to appear
        # in the signature, not the inner keys. Schema entries with no bundle
        # must each match an adapter kwarg directly.
        for spec in miner_registry.miner_specs():
            if not spec.entry_point or not spec.config_schema:
                continue
            with self.subTest(miner=spec.id):
                func = _resolve(spec.entry_point)
                named, has_var = _accepted_kwargs(func)
                if has_var:
                    continue
                flat_keys = {p.key for p in spec.config_schema if not p.kwarg_bundle}
                bundle_names = {p.kwarg_bundle for p in spec.config_schema if p.kwarg_bundle}
                expected = flat_keys | bundle_names
                missing = expected - named
                self.assertFalse(
                    missing,
                    f"{spec.id}: adapter rejects {missing}",
                )

    def test_adapter_required_kwargs_covered_by_runner(self) -> None:
        # Guard against the failure mode where an adapter declares a required
        # keyword-only parameter that neither the runner's hardcoded standard
        # kwargs nor the registered schema supplies. Such a drift turns ▶ Run
        # into ``adapter signature mismatch`` at first click.
        for spec in miner_registry.miner_specs():
            if not spec.entry_point:
                continue
            with self.subTest(miner=spec.id):
                func = _resolve(spec.entry_point)
                required, has_var = _required_kwargs(func)
                if has_var:
                    continue
                schema_supplied = {p.kwarg_bundle or p.key
                                    for p in spec.config_schema}
                # A bundled spec arrives under its bundle name, never a required
                # kwarg on its own — bundles are always optional in practice.
                uncovered = required - _RUNNER_STANDARD_KWARGS - schema_supplied
                self.assertFalse(
                    uncovered,
                    f"{spec.id}: adapter has required kwargs neither the runner "
                    f"nor the schema supply: {sorted(uncovered)}",
                )

    def test_paradigm_is_legal(self) -> None:
        for spec in miner_registry.miner_specs():
            with self.subTest(miner=spec.id):
                self.assertIn(spec.paradigm, _LEGAL_PARADIGMS)

    def test_extract_metrics_by_paradigm_callable(self) -> None:
        for spec in miner_registry.miner_specs():
            with self.subTest(miner=spec.id):
                # Empty result must produce a dict skeleton without KeyError.
                metrics = extract_metrics_by_paradigm(spec.paradigm, {}, source="native")
                self.assertIsInstance(metrics, dict)
                self.assertIn("replay_fitness", metrics)

    def test_extract_metrics_imported_marks_unrecoverable_keys(self) -> None:
        for spec in miner_registry.miner_specs():
            with self.subTest(miner=spec.id):
                metrics = extract_metrics_by_paradigm(spec.paradigm, {},
                                                      source="imported")
                self.assertTrue(metrics.get("_imported"))
                self.assertIsNone(metrics.get("process_tree_depth"))
                self.assertIsNone(metrics.get("extended_cardoso_cfc"))


if __name__ == "__main__":
    unittest.main()
