# Flex Compare

> Structuredness-aware process-discovery workbench.
> Pick an event log, classify its structuredness with the ARM algorithm
> (Andree et al. 2025), add discovery miners with their own configurations, run
> them under bounded concurrency, compare the resulting models side by side, and
> score each miner against a structuredness class with a two-phase questionnaire.

Flex Compare is the software artifact of the bachelor thesis *"Structuredness-Aware
Guidance for Process Discovery Miner Selection."* It is a standalone web
application that you start locally and use in the browser.

This README is also the implementation reference for the thesis. Section 1 sets
the scene for a reader who has never seen the tool. Section 2 walks through the
three tabs as a guided tour. Section 3 describes how the tool is built. The
remaining sections cover installation, running, layout, and the test suite.

---

## 1. The idea behind the tool

### The problem

Process discovery is the part of process mining that takes an **event log**, a
recording of what actually happened in a process (which activities ran, in which
order, for which cases), and reconstructs a **process model** from it. The program
that does this reconstruction is called a **miner**. Many miners exist, and they
disagree: given the same log, one produces a tidy flowchart, another a permissive
web of rules, a third an over-detailed tangle. There is no miner that is best
everywhere, and a practitioner facing a new log has little guidance on which one
to reach for.

This thesis proposes one answer. It looks at how **structured** the behavior in a
log is and uses that as a prior for choosing a miner. Intuitively, a rigid process
where every case follows nearly the same path is best served by a different kind
of miner than a flexible process where cases vary widely. The thesis makes that
intuition concrete with three classes, and Flex Compare is the tool that lets you
walk the whole argument on a real log: classify it, run miners on it, and judge
the results.

### The three vocabularies you will meet

Three small vocabularies run through the entire tool. Knowing them makes every
screen readable.

- **Structuredness classes.** Every log is sorted into exactly one of three
  classes: **Structured** (behavior is rigid and repetitive), **Semi-Structured**
  (locally rigid fragments coexist with flexible regions), and **Loosely
  Structured** (behavior is highly variable). These are produced by the ARM
  classifier in Tab 1.
- **Paradigms.** Miners come in three representational styles: **imperative**
  miners draw an explicit flowchart of allowed paths (for example the Inductive
  Miner), **declarative** miners list constraints that any valid run must respect
  (for example MINERful), and **hybrid** miners combine both (FusionMINERful). A
  miner's paradigm shapes what its output looks like and which metrics make sense
  for it.
- **The two scores.** When you judge a miner against a class, the tool records a
  **theoretical** score (what the miner is designed to do, read from its paper and
  documentation) and an **empirical** score (what the miner actually produced on
  the logs you ran). Both are reported per class, so a miner ends up with a profile
  rather than a single number.

### What you can do with it, in one sentence each

- Understand a log: classify its structuredness and see why.
- Discover models: run several miners on the same log and compare their output.
- Judge miners: score each miner against a structuredness class and read the
  resulting fit profile.

---

## 2. A guided tour of the three tabs

The application has three tabs arranged left to right in the order an analyst
works: first understand the log, then run miners on it, then score those miners.
The tour below follows one log through all three.

### Tab 1, Log & ARM: understand the log

You start by choosing a log. Either upload your own XES file or pick one from the
bundled corpus under `data/with-case-ids/`. Pressing *Run ARM Classifier* hands
the log to the ARM algorithm, a Rust program shipped inside the repo, and the tab
fills with three things.

The largest is an **activity-relation heatmap**. Each cell describes how one pair
of activities relates across the log, for example whether one always follows the
other, whether they exclude each other, or whether they run in parallel. The cell
carries the Andree code and the percentage of cases that exhibit the relation, so
the matrix is a compact fingerprint of the log's behavior.

Above it sits a **classification badge** that states the verdict in plain words,
one of `structured`, `semi-structured`, or `loosely-structured`, alongside the ARM
rules that fired to reach it. Below the badge, an **explainer** decomposes the
matrix into its existential fragment, choices, periphery, and parallel segments.
The point of the explainer is that the verdict is never a black box: you can trace
it back to the specific relations in the log that caused it.

By the end of Tab 1 you know which of the three classes your log belongs to. That
class is the thread you carry into the next two tabs.

> _Figure placeholder: Tab 1 with the ARM heatmap and the classification badge._

### Tab 2, Miners: discover and compare models

Tab 2 is where you run miners on the log. Pressing *+ Add Miner* drops a **miner
card** onto the page. Each card lets you pick a miner and then shows a
configuration form tailored to that miner: a slider here, a dropdown there,
appearing only because the chosen miner declares those options. You can add as
many cards as you like, including several copies of the same miner with different
settings, which is how you compare configurations against each other.

The miners available out of the box, grouped by paradigm, are:

- **imperative:** Inductive Miner, and the pm4py family (Heuristics, Alpha,
  Alpha+, Inductive, ILP, Genetic),
- **declarative:** MINERful, and pm4py's Declare and Log-Skeleton miners,
- **hybrid:** FusionMINERful.

If the miner you want is not in that list, two paths let you bring your own. The
**`custom-module`** path points the tool at any Python function with the signature
`(log_path, output_root, run_id, ...)`. The **`custom-exec`** path points it at
any binary or script that writes a model file in one of three standard formats:
**PNML** (replayed with pm4py for fitness, precision, and soundness),
**MINERful-native Declare-JSON** (read for constraint density and variability), or
**BPMN** (converted to PNML and then treated the same way). This bring-your-own
path is what lets the thesis later test its framework on a miner it was not built
around.

Pressing *Run* on a single card, or *Run all* across every card, discovers the
models. Each card then shows a rendered picture of its model plus a row of metric
pills. At the bottom, a **Comparison** strip lays every finished model next to the
others so the differences are visible at a glance. The strip carries a standing
warning: precision-style numbers from miners of different paradigms are not
directly comparable (the RC3 caveat from the thesis), so the tool refuses to
present, say, an imperative precision value next to a declarative one as if they
measured the same thing.

> _Figure placeholder: Tab 2 with two miner cards and the comparison strip._

### Tab 3, Questionnaire: score a miner against a class

The first two tabs produce observations. Tab 3 turns observations into a judged
score. It is a guided questionnaire that you fill in for one miner and one
structuredness class at a time, and it produces the two scores introduced earlier:
a theoretical score and an empirical score, each shown as a percentage, broken
down across three dimensions:

- **BQ, behavioural quality:** does the model reproduce the recorded behavior,
  while restricting itself to that behavior, while still allowing reasonable
  unobserved behavior,
- **IN, model interpretability:** how readable the model is for a human analyst,
- **SF, structural fit:** how well the miner's paradigm suits the kind of behavior
  the log actually has.

The tab opens on an **Overview** matrix. It lists the miners you have already
scored, one per row, with a small pair of donuts in each class column showing that
miner's theoretical and empirical fit for the class. An *+ Add miner* button
starts a fresh rating. A navigation bar offers five views: *Overview*, *New
rating*, *Theoretical*, *Empirical*, and *Result*.

A rating proceeds through them in order. In **New rating** you pick the miner and
one of the three classes. The **Theoretical** view then asks, item by item, what
the miner is designed to do. Each item is answered with a simple yes or no (or
"not applicable"), and the intended evidence is the miner's paper first, then its
documentation, then its source code. Answers save themselves the moment you click,
a table of contents ticks off what you have answered, and a progress bar tracks how
far you are. The **Empirical** view does the same for what the miner actually
produced: it scores the discovered model on each log on a 0, 1, or 2 scale, with
the model and its configuration shown on the left and the scoring questions on the
right. If some logs have not been discovered yet, a *Run all missing* button runs
them first. Finally, the **Result** view merges the two phases into a Theoretical
donut and an Empirical donut, a per-dimension breakdown, a coverage figure, and a
one-line suitability statement.

Everything you enter is written to disk, per miner, per class, and per item, so a
rating survives a restart and can be reproduced later from the saved files. The
tool records and aggregates your structured judgement; it does not decide the
miner choice for you.

> _Figure placeholder: Tab 3 Overview matrix and the Result donuts._

---

## 3. How it is built

Under the surface, Flex Compare is a thin, data-driven Dash front end over a set
of vendored upstream miners, with a single registry, a content-addressed cache,
and a dispatch layer that is deliberately honest about what each model can and
cannot tell you. Each design choice below answers a requirement the thesis places
on a defendable artifact (reproducibility, fair comparison, extensibility).

### Registry: one source of truth for miners

`miner_registry.MinerSpec` is the only place a miner is declared. Each entry
carries `id`, `label`, `paradigm`, `anchor_class`, `entry_point`,
`artifact_keys`, `config_schema`, and `runner_kind`. Adding a built-in miner is a
single entry, and the configuration form, the paradigm grouping, and the dispatch
route all follow from it automatically. The registry currently holds eleven
built-in entries.

`ParamSpec.kwarg_bundle` folds the flat schema fields shown in the form into the
nested dictionaries some adapters expect, for example
`{heuristics: ..., fusion: ...}` for FusionMINERful, so the form stays simple while
the adapter receives the shape it wants.

### Runner, cache, and reproducibility

Reproducibility is a thesis requirement, so runs are cached deterministically.
`stable_config_hash(config)` is `sha1(json.dumps(config, sort_keys=True))[:8]`,
which is stable across processes and restarts. A run is keyed on the combination of
the log (identified by a fast stat-hash of modification time and size), the miner
type, and that configuration hash. The cache slot is `<miner_type>__<config_hash>`
rather than a per-instance UUID, so removing a configured miner and adding it back
with the same settings is an instant cache hit instead of a recomputation.

`RunOutcome.status` distinguishes
`ok | timeout | nonzero | output_missing | parse_error | cancelled`, and each value
maps to a distinct pill on the card, so a failed run is diagnosable at a glance
rather than silently missing.

### Concurrency and cancellation

*Run all* dispatches through a single `ThreadPoolExecutor`. It runs three miners at
once by default, overridable with `FLEX_RUN_CONCURRENCY=N`. Custom-exec
subprocesses (Java miners, R scripts, and the like) are killable through the
*Cancel all* control, which terminates the child processes cooperatively so no
orphaned JVMs are left running.

### Honest metrics

`extract_metrics_by_paradigm(paradigm, result, source="imported")` is explicit
about what an imported model cannot carry. Structural metrics that need the native
discovery object, for example process-tree depth, extended Cardoso CFC, or the
flower-model flag, come back as `None` with an `_imported` marker rather than a
fabricated number, and the interface prints `n/a, imported model`. This stops the
comparison strip from inventing a value that the import path could never have
produced.

### Questionnaire backend

Tab 3 is configured per class in
`flex_compare/fragebogen/config/{structured,semi,loosely}.yaml`, which fixes the
item set, the per-phase maxima, and how the theoretical and empirical scores
combine. Theoretical answers persist through `phase_a_answers` (miner and item to
yes / no / not-applicable, plus a note), empirical answers through
`phase_e_answers` (log, item, and instance to 0 / 1 / 2 / not-applicable, plus a
note). The current selection (miner, class, view) lives in a browser-side store, so
moving between views never loses in-progress work.

---

## 4. Install

Requires **Python >= 3.11**, a working JDK (for the Java miners: MINERful,
FusionMINERful, and any custom Java executable), and the Rust toolchain only if you
want to recompile the ARM binary. The pre-built ARM binary is bundled.

```bash
git clone <repo-url> flex_compare
cd flex_compare
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Bundled assets (`tools/` and `data/`)

The repo is self-contained: every binary it needs is checked in. All paths below
are repo-root relative.

| Path | Purpose |
|---|---|
| `data/with-case-ids/*.xes` | The default log dropdown in Tab 1 |
| `tools/automated-process-classification/target/release/matrix_classifier` | ARM Rust binary |
| `tools/MINERful/{MINERful.jar, lib/, bin/, run-MINERful*.sh}` | MINERful JARs and launchers |
| `tools/ProM/{dist/, lib/, packages/}` | ProM-6.15 core plus the 47-package dependency closure for FusionMINERful |

The ProM closure is pinned by
`flex_compare/internal/fusion_miner/prom-lock.json`, and the upstream ZIP archives
sit at `flex_compare/internal/fusion_miner/vendor/prom-packages/*.zip`, so the
closure can be re-hydrated offline via
`python -m flex_compare.internal.fusion_miner.runtime`.

Override the project root entirely with `FLEX_PROJECT_ROOT=/some/path` (handy on CI
or scratch disks).

---

## 5. Run

```bash
DASH_PORT=8502 python -m flex_compare.app          # the long form
flex-compare                                        # console-script alias
```

Open <http://127.0.0.1:8502> and follow the three tabs:

1. **Log & ARM:** pick a log under `data/with-case-ids/` or upload a `.xes`, press
   *Run ARM Classifier*, read the heatmap and the classification badge.
2. **Miners:** press *+ Add Miner*, choose a built-in or custom miner, set its
   configuration, press *Run* or *Run all*. Read the per-card model and metric
   pills, then the comparison strip.
3. **Questionnaire:** press *+ Add miner*, pick a class, fill the *Theoretical*
   phase, run and fill the *Empirical* phase, read the merged *Result*.

### Useful environment variables

| Variable | Default | Effect |
|---|---|---|
| `DASH_PORT` | `8502` | HTTP port |
| `DASH_HOST` | `127.0.0.1` | Bind address |
| `DASH_DEBUG` | unset | Enable Dash debug mode (auto-reload) |
| `FLEX_PROJECT_ROOT` | repo root | Override where `tools/`, `.miner_cache/`, `.flex_compare/` live |
| `FLEX_RUN_CONCURRENCY` | `3` | Max simultaneous miner runs from *Run all* |
| `FLEX_COMPARE_LOG_LEVEL` | `INFO` | Python logging level |

---

## 6. Project layout

```
flex_compare/
├── pyproject.toml            # packaging (pip install -e .)
├── requirements.txt          # runtime deps (mirror of pyproject)
├── LICENSE                   # MIT plus upstream tool notices
├── README.md                 # this file
├── tools/                    # native binaries (symlinks or copies)
└── flex_compare/             # the Python package
    ├── app.py                # Dash app entry plus create_app()
    ├── state.py              # versioned, atomic .flex_compare/state.json
    ├── runner.py             # dispatch, RunOutcome, stable config-hash slots
    ├── format_import.py      # PNML / MINERful-JSON / BPMN ingest for custom-exec
    ├── fragebogen/           # Tab 3 questionnaire backend
    │   ├── config/           # per-class YAML (item set, maxima, T+E combination)
    │   ├── phase_a_answers.py# theoretical answers store
    │   └── phase_e_answers.py# empirical answers store
    ├── ui/                   # layout, ids, tabs, components, callbacks
    │   ├── layout.py
    │   ├── ids.py            # fc_id / fc_match helpers (typo-protected)
    │   ├── tabs/             # log_and_arm, miners, fragebogen
    │   ├── components/       # arm_view, miner_card, config_form, result_view
    │   └── callbacks/        # log, miner_list, config, run, fragebogen, zoom_modal
    ├── internal/             # vendored upstream dependencies
    │   ├── shared/           # registry, cache, metrics, arm_runner
    │   ├── imperative_miner/ # Inductive Miner adapter
    │   ├── declarative_miner/# MINERful adapter
    │   ├── declarative_evaluation/
    │   ├── fusion_miner/     # FusionMINERful adapter (plus Java facade)
    │   ├── pm4py_miner/      # pm4py adapter (Heuristics/Alpha/Inductive/ILP/...)
    │   └── experiment_reports.py
    └── tests/                # unit and integration tests; see Verify below
```

---

## 7. Verify

```bash
pytest                                          # all defaults, "not integration" marker
pytest -m integration                           # adds the smoke run that touches real adapters
```

The suite holds roughly 137 test functions across 16 files. The integration smoke
is opt-in because it spins up the JVM-backed miners.

---

## 8. Architecture notes (one line each)

- **`miner_registry.MinerSpec`** is the only registry: `id`, `paradigm`,
  `anchor_class`, `entry_point`, `config_schema`, `runner_kind`. Adding a built-in
  is one entry.
- **`ParamSpec.kwarg_bundle`** folds flat schema entries into nested dicts for
  adapters that expect `{heuristics: ..., fusion: ...}` (FusionMINERful today).
- **`stable_config_hash(config)`** is `sha1(json.dumps(sort_keys=True))[:8]`,
  stable across processes and restarts. The cache slot is `<type>__<cfg_hash>`, not
  the instance UUID, so remove-and-re-add of the same configured miner is an instant
  hit.
- **`RunOutcome.status`** distinguishes
  `ok | timeout | nonzero | output_missing | parse_error | cancelled`; each maps to
  a distinct UI pill.
- **`extract_metrics_by_paradigm(...)`** returns structural metrics for imported
  models as `None` with `_imported=True` rather than fabricating them.
- **Tab 3 questionnaire** produces a theoretical and an empirical score per class
  over the BQ, IN, and SF dimensions, configured per class under
  `fragebogen/config/*.yaml` and persisted item by item.

---

## 9. Limitations

- **ProM plugins other than FusionMINERful** are not wired in: the Java facade is
  bespoke. Use the bundled Heuristics / Alpha / Inductive via the `pm4py` adapter,
  or wrap an external Java miner via `custom-exec`.
- **Single log per session.** Batch-over-many-logs is intentionally out of scope.
- **Cross-paradigm metric comparisons are formally inadmissible (RC3).** The
  comparison strip surfaces a banner saying so; cross-paradigm comparison is only
  meant through the paradigm-neutral permissivity reference.
- **The questionnaire scores are an analyst's structured judgement, not an
  automated recommender.** The tool records and aggregates the answers; it does not
  decide the class-to-miner mapping for you.

---

## 10. License

MIT (see `LICENSE`). Bundled native binaries carry their own upstream licenses,
also documented in `LICENSE`.
