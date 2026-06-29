"""Each built-in MinerSpec renders a valid Dash form (CQ2.a coverage)."""
from __future__ import annotations

import unittest

from dash.development.base_component import Component

from flex_compare.internal.shared.registry import miner_registry
from flex_compare.internal.shared.registry.param_schema import ParamSpec

from flex_compare.ui.components.config_form import render_config_form


def _all_components(node):
    if isinstance(node, Component):
        yield node
        children = getattr(node, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                yield from _all_components(child)
        else:
            yield from _all_components(children)


class BuiltinSchemaRenderTests(unittest.TestCase):
    def test_every_builtin_renders_without_error(self) -> None:
        for spec in miner_registry.miner_specs():
            with self.subTest(miner=spec.id):
                # Render with default values from the schema.
                values = {p.key: p.default for p in spec.config_schema}
                rendered = render_config_form(spec.config_schema, f"inst_{spec.id}", values)
                self.assertIsInstance(rendered, Component)

    def test_widget_ids_carry_instance_and_key(self) -> None:
        # Spot-check pm4py-heuristics — slider + dropdown.
        spec = miner_registry.get("pm4-heuristics")
        values = {p.key: p.default for p in spec.config_schema}
        rendered = render_config_form(spec.config_schema, "inst_xyz", values)
        seen_keys: set[str] = set()
        for comp in _all_components(rendered):
            cid = getattr(comp, "id", None)
            if isinstance(cid, dict) and cid.get("type") == "fc-config":
                self.assertEqual(cid.get("instance"), "inst_xyz")
                seen_keys.add(cid.get("key"))
        for p in spec.config_schema:
            self.assertIn(p.key, seen_keys)

    def test_grouping_emits_subheaders(self) -> None:
        spec = miner_registry.get("fus")
        rendered = render_config_form(
            spec.config_schema, "fus_test",
            {p.key: p.default for p in spec.config_schema},
        )
        # Walk children for the group label strings.
        text_blob: list[str] = []
        for comp in _all_components(rendered):
            children = getattr(comp, "children", None)
            if isinstance(children, str):
                text_blob.append(children)
        seen = "|".join(text_blob)
        self.assertIn("Heuristics Net", seen)
        self.assertIn("Fusion Parameters", seen)

    def test_visible_when_initially_hides_mismatched_field(self) -> None:
        # Synthetic schema mimicking the old pm4 pattern: ``noise_threshold``
        # only visible when ``algorithm == "inductive"``. The real pm4py entries
        # are now per-algorithm so this is a unit-level check on the renderer.
        from flex_compare.internal.shared.registry.param_schema import ParamSpec

        schema = (
            ParamSpec("algorithm", "Algorithm", "dropdown", "heuristics",
                      options=(("Heuristics", "heuristics"), ("Inductive", "inductive"))),
            ParamSpec("noise_threshold", "Noise threshold", "slider", 0.0,
                      min=0.0, max=1.0, step=0.05,
                      visible_when=(("algorithm", "inductive"),)),
        )
        values = {p.key: p.default for p in schema}
        rendered = render_config_form(schema, "inst_t", values)
        hidden_seen = False
        for comp in _all_components(rendered):
            cid = getattr(comp, "id", None)
            if isinstance(cid, dict) and cid.get("type") == "fc-config-wrapper" \
                    and cid.get("key") == "noise_threshold":
                style = getattr(comp, "style", None) or {}
                if style.get("display") == "none":
                    hidden_seen = True
        self.assertTrue(hidden_seen, "noise_threshold wrapper should be hidden by default")


if __name__ == "__main__":
    unittest.main()
