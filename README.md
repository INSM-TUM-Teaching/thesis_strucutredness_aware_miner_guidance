# Structuredness-Aware Guidance for Process Discovery Miner Selection

This repository holds the software and result artifacts of the bachelor thesis
*"Structuredness-Aware Guidance for Process Discovery Miner Selection."*

## Repository layout

Three artifacts, one per top-level directory. They correspond to the three things the
thesis produces: the tool, the miner runs it was built on, and the filled-in
questionnaire from the evaluation.

| Directory | What it is | Corresponds to |
|-----------|------------|----------------|
| [`questionnaire_prototype/`](questionnaire_prototype/) | The prototype tool (Flex Compare): a standalone web app that classifies a log, runs miners on it, compares the models, and scores each miner against a structuredness class. | Chapter 6, Implementation |
| [`phase_b_results/`](phase_b_results/) | The Phase B miner runs. Self-contained HTML reports of the models discovered by the three construction-set miners (IMf, FusionMINERful, MINERful) across the event-log corpus. | Chapter 5, empirical grounding |
| [`miner_questionaire_results/`](miner_questionaire_results/) | The filled-in questionnaire scores from the evaluation, one PDF per miner (InductiveMiner, FusionMINERful, HeuristicsMiner). | Chapter 7, Evaluation |

`index.html` at the repository root is a small landing page linking the three Phase B
model reports.

### `questionnaire_prototype/` (the tool)

The software artifact. It is a local web application with three tabs, worked left to
right: understand a log (ARM classification), discover and compare models (run miners),
and score a miner against a class (the two-phase questionnaire). It ships with a 24-log
synthetic corpus under `data/with-case-ids/` and integrates the Inductive Miner (via
ProM/PM4Py), MINERful, and FusionMINERful.

Run it:

```bash
cd questionnaire_prototype
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
python -m flex_compare.app        # http://127.0.0.1:8502
```

Requires Python >= 3.11 and a JDK (for the Java miners). Full documentation, including
the three tabs, the architecture, how each miner is integrated, and how to add a miner,
is in [`questionnaire_prototype/README.md`](questionnaire_prototype/README.md); setup
details are in [`questionnaire_prototype/SETUP.md`](questionnaire_prototype/SETUP.md).

### `phase_b_results/` (the miner runs)

The models discovered during Phase B, when the three construction-set miners were applied
to the classified corpus to ground the per-class requirement profiles empirically. Each
HTML file is a self-contained report for one miner and can be opened directly in a
browser:

- `InductiveMiner.html` (IMf, imperative)
- `FusionMinerful.html` (FusionMINERful, hybrid)
- `Minerful.html` (MINERful, declarative)

### `miner_questionaire_results/` (evaluation answers)

The questionnaire applied and scored, exported as one PDF per miner. These record the
theoretical and empirical fit per structuredness class produced by the instrument during
the evaluation, including the miner introduced outside the construction set to check that
the items and scoring logic transfer unchanged:

- `InductiveMiner.pdf`
- `FusionMINERful.pdf`
- `HeuristicsMiner.pdf` (evaluation miner, outside the construction set)


## License

See [`questionnaire_prototype/LICENSE`](questionnaire_prototype/LICENSE).
