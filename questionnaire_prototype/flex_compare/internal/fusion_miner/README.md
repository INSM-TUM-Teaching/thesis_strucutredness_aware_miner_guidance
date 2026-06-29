# FusionMINERful Headless Evaluation

This module adds a local, headless FusionMINERful runtime on top of the
existing ProM installation in `tools/ProM`.

It does not use ProM's CLI as the execution path. Instead, it compiles and runs
its own Java facade that:

- creates a `UIContext` without launching the GUI
- loads an XES log
- runs the FusionMINERful core directly
- exports raw, normalized, and rendered artifacts
- writes a canonical `run.json`

Rendering now prefers ProM's GraphViz stack from Java (`Dot` / `Dot2Image`).
The Python `rendering.py` module remains as a fallback renderer if Java-side
SVG generation is unavailable.

Visualizer classes available in the ProM packages include:

- `org.processmining.mixedparadigm.plugins.MPVisualizer`
- `org.processmining.fusionminerful.visualization.FusionMINERfulVisualization`
- `org.processmining.fusionminerful.visualization.FusionMINERfulProMVisualization`

## Launch a Single Run

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python -m miners.fusion_miner.pilot_sheet \
  --log-path /Users/leonbei/BachelorThesis/data/with-case-ids/Log03_looselyStructured.xes \
  --output-root /Users/leonbei/BachelorThesis/Experimente
```

## Launch the Streamlit UI

```bash
streamlit run miners/fusion_miner/ui_app/app.py
```

## Main Outputs

- `run.json`
- `result_data.json`
- `ergebnisbericht.md`
- `assets/raw/model.fusion_result.json`
- `assets/raw/model.pnwa.dpnml` when PNWA is available
- `assets/raw/model.pnml` when a Petri net is available
- `assets/normalized/hybrid_model.json`
- `assets/normalized/pnwa_model.json`
- `assets/rendered/hybrid_model.png` (ProM-like visualizer output, preferred when available)
- `assets/rendered/pnwa_model.png` (ProM-like visualizer output, preferred when available)
- `assets/rendered/hybrid_model.svg` (GraphViz fallback)
- `assets/rendered/pnwa_model.svg` (GraphViz fallback)

## Runtime Lock

The module maintains:

- `miners/fusion_miner/prom-lock.json`
- `miners/fusion_miner/vendor/prom-packages/`

These files pin the local ProM-based runtime used by the headless facade.
