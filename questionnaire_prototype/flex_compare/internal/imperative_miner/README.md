# Imperative Miner Evaluation

This folder contains the thesis-oriented evaluation workflow for imperative process discovery with PM4Py.

## Purpose

The implementation is centered on the Inductive Miner and supports a compact but reproducible workflow:

1. Load an event log from XES.
2. Discover a process tree with the Inductive Miner.
3. Convert the process tree into a Petri net.
4. Derive quantitative evaluation metrics from the log and the discovered model.
5. Build a compact report table for notebook display and CSV export.
6. Write a central Excel workbook with exactly one row per log name.

## Structure

- `evaluation.py`
  Main implementation for discovery, quantitative evaluation, soundness handling, and report generation.
- `__init__.py`
  Re-exports the public API used by the notebook.

## Quantitative Metrics

The raw result schema produced by `mine_process_models(...)` includes:

- `fitness_primary`
- `fitness_average_trace`
- `fitness_percentage_fitting_traces`
- `fitness_log`
- `precision`
- `f1`
- `n_places`
- `n_transitions`
- `n_silent_transitions`
- `n_arcs`
- `discovery_runtime_sec`
- `conformance_runtime_sec`
- `total_runtime_sec`
- `is_wf_net`
- `is_sound`
- `soundness_status`
- `soundness_raw`
- `soundness_diagnostics`
- `soundness_error`

The qualitative fields remain intentionally open for manual coding:

- `readability_rating`
- `readability_note`
- `structural_fidelity_rating`
- `structural_fidelity_note`

## Soundness Handling

PM4Py can return different shapes for `pm4py.analysis.check_soundness(net, im, fm)` depending on version:

- `bool`
- `(bool, diagnostics)`

The implementation handles both cases robustly:

- tuple -> `is_sound` is the first element, `soundness_diagnostics` the second
- bool -> `is_sound` is the value, `soundness_diagnostics = None`

The resulting status is set as follows:

- `"sound"` if the net is a workflow net and `is_sound is True`
- `"not_sound"` if the net is a workflow net and `is_sound is False`
- `"not_checkable_as_sound_wf_net"` otherwise

## Recommended Log Import

In this project setup, the notebook should load logs via:

```python
from pm4py.objects.log.importer.xes import importer as xes_importer
log = xes_importer.apply("data/original/Log01_structured.xes")
```

This import path yields PM4Py `EventLog` objects and matches the tested workflow in this repository.

## Minimal Example

```python
from pm4py.objects.log.importer.xes import importer as xes_importer
from miners.imperative_miner import make_report_dataframe, mine_process_models, set_log_name

log = xes_importer.apply("data/original/Log01_structured.xes")
set_log_name(log, "Log01_structured")

results = mine_process_models([log], conformance_method="alignments")
report_df = make_report_dataframe(results, digits=3)

print(report_df.to_string(index=False))
report_df.to_csv("imperative_miner_report.csv", index=False)
```

## Notebook Usage

The notebook can import the package with:

```python
from miners.imperative_miner import evaluation as evaluation_imperative
```

and then call:

```python
results = evaluation_imperative.mine_process_models(logs_structured)
report_df = evaluation_imperative.make_report_dataframe(results, digits=3)
```

## Ergebnisbericht Generator

To create a filled markdown report (plus visual artifacts) for one log:

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python -m miners.imperative_miner.pilot_sheet \
  --log-path /Users/leonbei/BachelorThesis/data/original/Log01_structured.xes \
  --output-root /Users/leonbei/BachelorThesis/Experimente \
  --bearbeiter "Leon Bei" \
  --conformance-method alignments
```

Optional PDF export (requires `pandoc`):

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python -m miners.imperative_miner.pilot_sheet \
  --log-path /Users/leonbei/BachelorThesis/data/original/Log01_structured.xes \
  --output-root /Users/leonbei/BachelorThesis/Experimente \
  --export-pdf
```

The generated bundle contains:

- `ergebnisbericht.md`
- `result_data.json`
- `assets/process_tree.png`
- `assets/petri_net.png`
- `assets/bpmn.png` (if BPMN conversion succeeds)

## Central Excel Export

Every successful run updates a central workbook at:

```text
<output_root>/imperative_miner_quantitative_metrics.xlsx
```

Rules:

- exactly one row per `log_name`
- `structuredness_class` is stored alongside each log row
- the row is identified by the XES file stem, e.g. `Log01_structured`
- rerunning the same log replaces the existing row instead of appending a duplicate
- numeric values from `log_stats`, `result_align`, and `result_token` are written with stable prefixes such as `log_`, `align_`, and `token_`

The workbook contains two sheets:

- `metrics`
  One row per log with raw quantitative values.
- `summary`
  Aggregated statistics for the numeric metrics with an Excel dropdown for `structuredness_class` (`all`, `structured`, `semi`, `loosely`).

The markdown/JSON artifact folder for a run is still written to:

```text
<output_root>/<klasse>/<log_name>/inductive_miner/
```

## Optional Dependency

PM4Py may warn that the SciPy-based solution for soundness checking can be unstable. For more reliable Woflan-related computations, install:

```bash
/Users/leonbei/BachelorThesis/.venv/bin/pip install pulp
```

For `.xlsx` support in local environments, make sure `openpyxl` is installed:

```bash
/Users/leonbei/BachelorThesis/.venv/bin/pip install openpyxl
```
