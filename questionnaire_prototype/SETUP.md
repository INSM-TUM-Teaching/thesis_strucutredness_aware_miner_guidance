# Setup — questionnaire_prototype (Prototype Tool - Structuredness-Aware Miner Guidance)

This subdirectory is a self-contained copy of the **Prototype Tool - Structuredness-Aware
Miner Guidance**. All paths
resolve relative to this folder (`PROJECT_ROOT` in
`flex_compare/internal/shared/paths.py` points here automatically). See `README.md`
for the full tool documentation.

## Install & run

```bash
cd questionnaire_prototype
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

python -m flex_compare.app        # http://127.0.0.1:8502
# or: miner-guidance
```

Requires **Python >= 3.11** and a **JDK** (for the Java miners MINERful and
FusionMINERful). Runtime caches (`.miner_cache/`, `.flex_compare/`) are created
inside this folder and are git-ignored.

## Platform note (macOS-arm64 binaries)

Two checked-in native binaries are built for **macOS-arm64** and must be rebuilt on
other platforms:

- `tools/automated-process-classification/target/release/matrix_classifier`
  (ARM classifier, Rust)
- `flex_compare/internal/fusion_miner/java/native/lpsolve-macos-arm64`
  (lp_solve native lib for FusionMINERful)

## Omitted: `vendor/prom-packages`

The 192 MB of ProM source ZIP archives were **not** copied — they are only needed to
rebuild `tools/ProM/` offline, never on the runtime classpath. FusionMINERful runs
from the extracted closure in `tools/ProM/`. If you ever need to re-hydrate the
closure, run:

```bash
python -m flex_compare.internal.fusion_miner.runtime --download-archives
```

which re-downloads the archives from the URLs pinned in
`flex_compare/internal/fusion_miner/prom-lock.json`.
