# Adding a custom ("unseen") miner

flex_compare ships with a fixed set of registry miners (Inductive, Heuristics,
ILP, MINERful, FusionMINERful, …). Beyond those, you can plug in a miner the app
has never seen before without touching the registry or writing a Python adapter.
This is the **custom-exec** path: you point the app at an external command, and
it ingests whatever model that command writes.

This document describes the input/output contract, walks through a full worked
example (a standalone Heuristics Miner), and explains how the set of supported
output formats can be extended.

---

## 1. The two extension paths

A custom miner is an `InlineSpec` ([`flex_compare/state.py`](flex_compare/state.py))
with one of two `runner_kind`s:

| `runner_kind` | How it runs | You supply |
|---|---|---|
| `"executable"` | external process (any language) | a **command template** + output format/pattern |
| `"module"` | in-process Python call | an **entry point** `module:function` |

The `"executable"` path is the general "plug in any miner" mechanism and is what
the rest of this document covers. Dispatch lives in
[`runner._dispatch_executable`](flex_compare/runner.py) and
[`format_import`](flex_compare/format_import.py).

---

## 2. The contract

An executable miner must satisfy three things.

### Input

The input is always an **XES event log**. The app passes it to your command via
placeholders that are substituted in `format_import._format_template`:

| Placeholder | Replaced with |
|---|---|
| `{log}` | absolute path to the XES log |
| `{outdir}` | absolute path to a per-run output directory |
| `{<param>}` | any key from the miner card's `config` JSON |

Anything your command needs beyond the log (thresholds, flags) travels through
`config` and its own `{...}` placeholder. A leftover, unsubstituted `{key}` is a
hard error, so every placeholder in the template must have a matching config key.

### Output

Your command must write its discovered model **as a file inside `{outdir}`**. The
app then parses that file. Exactly three model formats are understood
(`OutputFormat` in `format_import.py`):

| `output_format` | File | Paradigm | Metrics computed on import |
|---|---|---|---|
| `pnml` | Petri net (PNML) | `imperativ` | `replay_fitness`, `etc_precision`, `soundness_passed`, `is_wf_net` |
| `bpmn` | BPMN XML | `imperativ` | converted to a Petri net, then as PNML |
| `declare-json` | **MINERful-native** JSON | `deklarativ` | `constraint_density`, `constraint_variability`, `n_constraints`, … |

Notes and limits:

- `declare-json` accepts **only** the MINERful dialect
  (`{"processSchema": {"constraints": [...]}, "activities": [...]}`). Foreign
  Declare dialects (RuM, ConDec, generic Declare4Py) are rejected with a clear
  `ValueError` rather than silently mis-parsed.
- Metrics that need *discovery-internal* information (process-tree depth, CFC,
  flower detection, vacuity rate) cannot be recovered from an imported model.
  They stay `None` and are marked `source="imported"` — an imported miner is
  scored on fewer metrics than a natively integrated one.

### Exit and file presence

Exit code `0` means success. The run then maps to a status pill:

| Situation | Status |
|---|---|
| exit 0, output file present, parses | `ok` |
| non-zero exit | `nonzero` |
| exceeds `timeout_sec` | `timeout` |
| exit 0 but `output_pattern` file missing | `output_missing` |
| file present but unparseable | `parse_error` |

stdout + stderr are captured to `<outdir>/_exec.log` for debugging.

---

## 3. Worked example — a standalone Heuristics Miner

[`flex_compare/examples/heuristics_miner_cli.py`](flex_compare/examples/heuristics_miner_cli.py)
is a complete, self-contained executable miner. It reads an XES log, runs pm4py's
Heuristics Miner, and writes `model.pnml`. The app never imports it — it only runs
it as a subprocess.

### Run it directly

```bash
python flex_compare/examples/heuristics_miner_cli.py \
    --log data/with-case-ids/Log01_structured.xes \
    --out /tmp/hm_out \
    --dependency-threshold 0.5
# → wrote /tmp/hm_out/model.pnml
```

### Register it in the app

In the **Miners** tab, "Add miner" → pick a `custom-exec` type and fill in the
inline-spec fields ([`flex_compare/ui/tabs/miners.py`](flex_compare/ui/tabs/miners.py)):

| Field | Value |
|---|---|
| Paradigm | `imperativ` |
| Command template | `python flex_compare/examples/heuristics_miner_cli.py --log {log} --out {outdir} --dependency-threshold {dependency_threshold}` |
| Output format | `PNML` |
| Output file pattern | `model.pnml` |
| Config parameters (JSON) | `{"dependency_threshold": 0.5}` |

The `{dependency_threshold}` placeholder is filled from the config JSON. Change
the slider/JSON value and the app re-runs the miner; an identical config hits the
result cache instead. Drop the flag from the template to use pm4py's default.

Once added, the card runs like any built-in miner: the discovered net is replayed
against the log and you get `replay_fitness`, `etc_precision`, soundness, and a
rendered Petri-net PNG, all through the same comparison strip as the registry
miners.

> The point of the example is the *plug-in path*, not the algorithm — pm4py's
> Heuristics Miner is also available as a native registry miner. Swap the command
> template for any external tool (a Java `.jar`, a ProM CLI, your own script) that
> honours the `{log}`/`{outdir}` contract and writes one of the three formats.

---

## 4. Can the output format be extended (e.g. PNG)?

Two different questions hide here.

### PNG as a *model* format — no

`output_format` names the **source model** the app parses to compute quality
metrics. A PNG (or any raster image) carries no analysable structure: you cannot
replay a log against a picture, so there is no fitness, precision, or soundness to
read from it. Adding `png` as an `output_format` would not make sense.

Note the app **already produces a PNG** — on the visualisation side. When a PNML
is imported, `import_pnml` renders `petri_net.png` from the parsed net via
`pm4py.save_vis_petri_net`. So the picture you want is generated *from* the model,
not consumed *as* one.

### A genuinely new *model* format — yes, cleanly

If you have a miner that emits a model type the app cannot yet read (for example a
process tree `.ptml`, a raw pm4py `.dfg`, or a new declarative dialect), adding it
is a four-step change, all in
[`flex_compare/format_import.py`](flex_compare/format_import.py):

1. **Extend the type.** Add the name to
   `OutputFormat = Literal["pnml", "declare-json", "bpmn"]`.
2. **Write an importer** `import_<format>(artifact_path, log_path, output_dir=...)`
   that returns a result dict shaped like `import_pnml`'s: a `status`, an
   `imported_from` tag, a `metrics` sub-dict, and any artifact paths. Populate the
   metrics you can derive; leave the rest `None`.
3. **Register it in the dispatcher** `import_by_format`, and map its paradigm in
   `paradigm_for_format`.
4. **Expose it in the UI** dropdown in
   [`flex_compare/ui/tabs/miners.py`](flex_compare/ui/tabs/miners.py)
   (`ADD_MODAL_INLINE_OUTPUT_FORMAT`).

The paradigm you return decides which metric proxies run
(`extract_metrics_by_paradigm`), so a new imperative format reuses the Petri-net
metric set and a new declarative one reuses the constraint metric set. No change
to `runner.py` or `state.py` is needed — the dispatch is data-driven off
`output_format`.
