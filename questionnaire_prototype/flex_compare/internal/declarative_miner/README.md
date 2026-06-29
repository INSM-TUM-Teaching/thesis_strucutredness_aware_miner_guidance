# Declarative MINERful Evaluation

Dieses Modul implementiert den Ergebnisbericht-v1-Flow fuer MINERful mit:

- Pflichtmetriken
- deklarativen Komplexitaetsmetriken (`Size`, `Density`, `Separability`, `Constraint Variability`)
- versionierter Entropiebasis (`T_lang_values`, `T_lang_version`)
- strenger Modellvalidierung (`valid`, `valid_with_fallback`, `invalid`)

Qualitaetsmetriken `Fitness`, `Precision`, `Generalisation` bleiben in v1 bewusst `n/a`.

## CLI Ergebnisbericht (ein Log)

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python -m miners.declarative_miner.pilot_sheet \
  --log-path /Users/leonbei/BachelorThesis/data/with-case-ids/Log03_looselyStructured.xes \
  --minerful-dir /Users/leonbei/BachelorThesis/tools/MINERful \
  --output-root /Users/leonbei/BachelorThesis/Experimente
```

Outputs:

- `ergebnisbericht.md`
- `result_data.json`
- `assets/specifications/<logname>.json` (MINERful-Discovery-Output, unveraendert)
- `assets/specifications/<logname>.fitness.csv` (MINERful FitnessChecker CSV: per-constraint `FullSatisfactions/VacuousSatisfactions/Violations` plus Modell-Aggregate `Avg-fitness/Trace-fit-ratio`)
- `assets/visuals/declare_model_declare_js.html` (interaktive, selbstenthaltende declare-js Ansicht)
- `assets/visuals/declare_model_declare_js.png` (PNG-Snapshot derselben declare-js Ansicht fuer `ergebnisbericht.md`)
- optional `ergebnisbericht.pdf` (`--export-pdf`)

## Conformance via MINERful Fitness Check

Conformance-Werte (`Avg-fitness`, `Trace-fit-ratio`, per-Constraint `FullSatisfactions/VacuousSatisfactions/Violations`) stammen aus `minerful.MinerFulFitnessCheckStarter` (selbe `MINERful.jar`, die auch die Discovery macht). Modell-Eingabe ist die unveraenderte MINERful-Discovery-JSON via `-iSE json`. Es findet **keine** Format-Uebersetzung (kein `.decl`-Zwischenformat) statt — Discovery- und Conformance-Tool sind dieselbe Codebasis.

Die abgeleiteten Quotienten im Bericht (`trace_fulfillment_rate`, `trace_violation_rate`, `mean_trace_non_violation_rate`, ...) sind reine Reporting-Operationen: Zaehler **und** Nenner sind tool-emittierte Zaehlungen. Keine Conformance-Logik in der Python-Schicht. Siehe [tools/MINERful/minerful-lock.json](../../tools/MINERful/minerful-lock.json) fuer JAR-Hash und Java-Anforderung (Java 24).

Visualisierung ist jetzt strikt `declare_js`:

- Es gibt keine Engine-Auswahl (`edd/native/auto` entfernt).
- Bei Render-Fehler wird der Run als Fehler beendet (kein stiller Fallback).
- Visualisierungs-Metadaten in `result_data.json`:
  - `declare_visualization_engine = "declare_js"`
  - `declare_visualization_kind = "html+png"`
  - `declare_visualization_path`
  - `declare_visualization_png_path`
  - `declare_visualization_layout_applied = "auto_layout_via_gear"`
  - `declare_visualization_snapshot_stage = "post_auto_layout"`

MINERful-Kompatibilitaet fuer declare-js:

- benoetigt Python-Playwright + Chromium (`pip install playwright && playwright install chromium`)
- Pipeline nutzt MINERful-CSV als Primarinput (erste Spalte `Constraint`, Semikolon-separiert)
- declare-js kann generell auch `txt`/`json` importieren, im Run-Flow wird jedoch ausschliesslich MINERful-CSV verwendet
- PNG-Snapshot wird nach automatischem `AUTO_LAYOUT`-Trigger (Zahnrad-Aequivalent) erzeugt

## Nur Visualisierung (declare-js)

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python - <<'PY'
from pathlib import Path
from miners.declarative_miner.visualize_declare_js import render_declare_js_html, render_declare_js_png

csv_path = Path("/Users/leonbei/BachelorThesis/tools/MINERful/specifications/Log03_looselyStructured.csv")
html_out = Path("/Users/leonbei/BachelorThesis/tools/MINERful/specifications/Log03_looselyStructured.declare_js.html")
png_out = Path("/Users/leonbei/BachelorThesis/tools/MINERful/specifications/Log03_looselyStructured.declare_js.png")

render_declare_js_html(csv_path=csv_path, html_output_path=html_out, title="Declare Model: Log03")
render_declare_js_png(html_path=html_out, png_output_path=png_out)
print(html_out)
print(png_out)
PY
```

## Batch-Run

```bash
/Users/leonbei/BachelorThesis/.venv/bin/python -m miners.declarative_miner.run_declarative
```

Batch-Report:

- `/Users/leonbei/BachelorThesis/results/summaries/declarative_miner_report.csv`

Kompatibilitaet:

- `/Users/leonbei/BachelorThesis/scripts/run_minerful.py` bleibt als Wrapper erhalten.
