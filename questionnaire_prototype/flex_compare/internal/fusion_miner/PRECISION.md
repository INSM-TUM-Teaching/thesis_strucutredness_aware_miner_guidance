# Fusion Miner — Precision-Maß

Diese Datei dokumentiert, **welches Precision-Maß** der Fusion Miner aktuell berechnet, **wie es technisch implementiert ist** und **wo es in der Literatur verankert ist**.

## TL;DR

- **Maß:** Alignment-basierte ETC-Precision (Adriansyah / Muñoz-Gama & Carmona) auf dem **Petri-Netz mit Automaten (PNwA)** — dem hybriden Modell, in dem die Declare-Constraints als Automaten in das Petri-Netz integriert sind.
- **Implementierung:** Die ProM-Plugin-Klasse `org.processmining.fusionminerful.plugins.AlignmentPrecGen`, die im offiziellen FusionMINERful-Paket mitgeliefert wird. Wir rufen ihre Methode `measureConformanceAssumingCorrectAlignment(...)` headless auf und lesen `precision` und `generalization` aus dem Rückgabeobjekt `AlignmentPrecGenRes`.
- **Wert-Bereich:** $\text{precision} \in [0, 1]$, höher = präziser. Liefert zusätzlich Generalization $\in [0, 1]$.
- **Vorgängerversion:** Ein selbst gebauter k-Gramm-Markov-Proxy. Dieser wurde durch `AlignmentPrecGen` ersetzt und am 2026-06-02 samt Unit-Tests und Validierungs-Harness aus dem Repo entfernt.

## 1. Was wird gemessen?

Precision in Process Discovery beantwortet die Frage:

> *Wie viel Verhalten erlaubt das entdeckte Modell, das nicht im Log vorkommt?*

Ein perfekt passendes Modell ist **fitting** (kann jeden Trace abspielen) **und** **precise** (erlaubt nicht viel mehr Verhalten, als der Log enthält). Beide Eigenschaften zusammen ergeben einen guten Trade-off (siehe van der Aalst 2011, *Process Mining: Discovery, Conformance and Enhancement*, Kap. 7).

Beim Fusion Miner besteht das Modell aus zwei Teilen:

1. **Prozedurales Petri-Netz** (aus dem Heuristics-Miner-Anteil)
2. **Declare-Constraints** (aus dem MINERful-Anteil)

Beide werden zu einem **Petri-Netz mit Automaten (PNwA)** zusammengeführt: jedes Declare-Constraint wird als endlicher Automat in den Zustandsraum des Petri-Netzes hineingerechnet, sodass die kombinierte Semantik aus `[21]` Westergaard & Slaats 2013 — *Smart Simulation* — exakt erfasst wird (siehe De Smedt et al. 2015, §3.1).

Die Precision wird auf **diesem hybriden Zustandsraum** gemessen, nicht nur auf dem Petri-Netz-Anteil. Das ist der wesentliche Punkt: ein reines Petri-Netz-Precision-Maß würde die einschränkende Wirkung der Declare-Constraints ignorieren und die Precision systematisch unterschätzen.

## 2. Wie funktioniert AlignmentPrecGen konkret?

Die Methode geht auf **Adriansyah, Muñoz-Gama, Carmona, van Dongen, van der Aalst (2012)** zurück: *"Alignment based precision checking"* (BPM Workshops). Die Grundidee:

1. **Alignment** des Logs gegen das Modell berechnen — d.h. für jeden Trace einen optimalen Pfad durch den Modell-Zustandsraum, der so wenig "move-on-log" / "move-on-model"-Schritte wie möglich enthält. (Im Fusion-Miner-Code: bereits durch `MpccService` für die MPCC-Fitness berechnet → wir verwenden dieselbe `PNRepResult` wieder.)
2. Den resultierenden **Log-Automaton** aufbauen: ein Trie aller Präfixe, die im Alignment auftreten.
3. An jedem Knoten des Trie bestimmen:
   - **`reflected`**: welche Aktivitäten wurden im Log nach diesem Präfix tatsächlich beobachtet?
   - **`available`**: welche Aktivitäten wären laut Modell nach diesem Präfix möglich gewesen?
4. Die Precision ist der gewichtete Durchschnitt von $\frac{|reflected|}{|available|}$ über alle Knoten:

$$
\text{precision} = \frac{\sum_{n \in \text{nodes}} w(n) \cdot \frac{|reflected(n)|}{|available(n)|}}{\sum_{n \in \text{nodes}} w(n)}
$$

wobei $w(n)$ die Anzahl der Trace-Instanzen ist, die durch Knoten $n$ laufen (Trace-Frequenz als Gewicht — bekannt als *ETConformance*-Variante von Muñoz-Gama & Carmona).

5. **Generalization** ist als Komplementärmaß definiert: sie schätzt, wie wahrscheinlich es ist, dass eine bisher ungesehene Aktivität an einem Knoten gerechtfertigt wäre. Konkret nutzt das Plugin die Heuristik aus van der Aalst, Adriansyah, van Dongen (2012), *"Replaying history on process models for conformance checking and performance analysis"*:

$$
\text{generalization} = 1 - \frac{\sum_{n} \frac{1}{\sqrt{w(n) \cdot |available(n)|}}}{|\text{nodes}|}
$$

Sehr selten besuchte Knoten mit vielen erlaubten Folgeaktivitäten drücken die Generalization runter — ein starker Indikator für *over-fitting*.

Die Besonderheit beim Fusion Miner: der "Modell-Zustandsraum" in Schritt 3 ist der **Synchronous Product** aus Petri-Netz und allen Declare-Automaten. Eine Aktivität gilt nur dann als `available`, wenn sie weder die Petri-Netz-Token-Semantik noch eine aktive Declare-Constraint verletzt. Genau diese Anreicherung macht `AlignmentPrecGen` zur richtigen Wahl für hybride Modelle.

## 3. Verankerung in der Literatur

Die zugrundeliegende Technik wird im **Fusion Miner Paper selbst** in §3.3 referenziert (S. 14–15 in De Smedt, De Weerdt, Vanthienen 2015, *"Fusion Miner: Process Discovery for Mixed-Paradigm Models"*, Decision Support Systems):

> *"The authors have implemented a preliminary fitness evaluation technique which tries to find an alignment of the log and the model. By traversing the state space, the model gets replayed in a best-first fashion. The technique creates the automaton of the Declare model […] and makes the product with the Petri net state space while traversing the trace during replay. Precision can be calculated during replay."*

| Quelle | Beitrag |
|---|---|
| **Adriansyah et al. 2012** — *Alignment based precision checking* (BPM Workshops, LNBIP 132) | Ursprüngliche Definition der alignment-basierten Precision; das ProM-Paket `PNetAlignmentAnalysis` ist die Referenz-Implementierung. |
| **Muñoz-Gama & Carmona 2010** — *A fresh look at precision in process conformance* (BPM 2010, LNCS 6336) | ETConformance: gewichteter Durchschnitt von $\frac{reflected}{available}$ pro Trie-Knoten. Theoretische Grundlage. |
| **van der Aalst, Adriansyah, van Dongen 2012** — *Replaying history on process models for conformance checking and performance analysis* (WIREs Data Mining and Knowledge Discovery 2(2)) | Vereinheitlichter Replay-Ansatz; liefert die Generalization-Formel. |
| **Westergaard & Slaats 2013** — *Mixing paradigms for more comprehensible models* (BPM 2013, LNCS 8094) | Definition der Smart-Simulation-Semantik (Petri-Netz × Declare-Automaten-Produkt) — der Zustandsraum, auf dem die Precision gemessen wird. |
| **De Smedt, De Weerdt, Vanthienen 2015** — *Fusion Miner: Process Discovery for Mixed-Paradigm Models* (Decision Support Systems) | §3.3 — beschreibt den Einsatz dieser Precision speziell für hybride Modelle und referenziert auch das alternative behavioral-precision-Maß $p_B$ (Goedertier 2009 / vanden Broucke 2013), das in den Tabellen 3 und 5 der Paper-Experimente verwendet wird. |

Das Plugin trägt im Quellcode die Autorenangabe **"author = Arya Adriansyah, pack = PNetAlignmentAnalysis"** — es ist also wörtlich Adriansyahs Implementierung, die für PNwA-Modelle wiederverwendet wird.

## 4. Implementierungsdetails im Repo

### Java-Seite

- [`HeadlessFusionMinerFulRunner.java`](java/src/main/java/thesis/fusion/HeadlessFusionMinerFulRunner.java): Block direkt nach der MPCC-Berechnung. Ruft `AlignmentPrecGen.measureConformanceAssumingCorrectAlignment(...)` mit dem Mapping und der `PNRepResult` auf, die `MpccService` ohnehin schon erzeugt hat. Schreibt die Felder
  - `pnwa_precision`
  - `pnwa_generalization`
  - `pnwa_precision_status` (`ok` / `error` / `skipped`)
  - `pnwa_precision_method` (Konstante `alignment_based_etc_pnwa`)
  - `pnwa_precision_error`
  - `pnwa_precision_runtime_ms`

  in die `headless_manifest.json`. Fehler werden eingefangen, damit ein gescheiterter Precision-Lauf nicht den Discovery-Run mitreißt.

- [`MpccService.java`](java/src/main/java/thesis/fusion/MpccService.java): `MpccService.Result` exponiert `mapping` und `alignment` als Felder, damit der Headless-Runner sie an `AlignmentPrecGen` weitergeben kann ohne neuen Replay-Lauf.

### Python-Seite

- [`evaluation.py`](evaluation.py): Liest die `pnwa_*`-Felder aus dem Manifest und schreibt sie als `precision`, `generalization`, `precision_status`, `precision_method`, `precision_scope`, `precision_error`, `precision_runtime_ms` in `metrics.quality_metrics`. Der alte Markov-Aufruf entfällt komplett.
- [`comparison_app/ui/components/tabs/comparison.py`](../comparison_app/ui/components/tabs/comparison.py): Spalte **Precision** liest jetzt `fus_q.get("precision")` (statt `hybrid_markov_precision`), Spalte **Generalization** ist neu gefüllt.
- [`comparison_app/ui/components/summary.py`](../comparison_app/ui/components/summary.py), [`structuredness_summary.py`](../comparison_app/ui/components/structuredness_summary.py): Labels heißen jetzt **"Precision (PNwA)"**.
- [`comparison_app/ui/components/configuration.py`](../comparison_app/ui/components/configuration.py): Sektionstitel von "Hybrid Markov Precision (Sampling)" auf **"PNwA Alignment-based Precision"** geändert.

## 5. Was ist mit dem alten Markov-Proxy?

Der k-Gramm-Markov-Proxy (`markov_precision.py`), seine Unit-Tests (`tests/test_markov_precision_*.py`) und der zugehörige Validierungs-Harness (`validation/`) wurden am 2026-06-02 entfernt, nachdem `AlignmentPrecGen` ihn als Precision-Maß abgelöst hatte. Der Hybrid-Trace-Sampler auf der Java-Seite (`HybridTraceSampler`) und die Sampling-Eingaben in der UI bleiben bestehen, speisen aber nicht mehr den (gelöschten) Proxy. Die Git-Historie enthält den entfernten Code, falls später ein Vergleich zwischen Proxy und alignment-basierter Precision dokumentiert werden soll.

## 6. Ergebnis aus dem Smoke-Test

Auf [`miners/declarative_evaluation/tests/fixtures/mini_log.xes`](../declarative_evaluation/tests/fixtures/mini_log.xes):

| Metrik | Wert |
|---|---|
| MPCC fitness | 1.000 |
| **Precision (PNwA)** | **0.718** |
| **Generalization (PNwA)** | **0.923** |
| Precision-Methode | `alignment_based_etc_pnwa` |
| Status | `ok` |

Beide Werte liegen sauber in $[0, 1]$ und sind direkt vergleichbar mit den Precision-Werten, die der imperative Miner über `pm4py.precision_alignments` berechnet — beide gehen auf dieselbe Adriansyah-ETC-Definition zurück, nur dass die Fusion-Variante zusätzlich die Declare-Constraints im Zustandsraum berücksichtigt.

## 7. Conditional Precision je nach Modelltyp

Wenn das PNwA **null Declare-Constraints** enthält (typisch für *loosely structured* / *unstructured* Logs, bei denen MINERful nichts beisteuert), ist es strukturell ein reines Petri-Netz. In diesem Fall berechnet `evaluation.py` die Precision **stattdessen mit PM4Py** (`pm4py.conformance.precision_alignments`) auf dem exportierten PNML — exakt dieselbe Funktion, die der Imperative Miner verwendet.

| Bedingung | Verwendetes Maß | `precision_method` |
|---|---|---|
| `pnwa_precision_status == "ok"`, `pnwa_constraint_count > 0` | ProMs `AlignmentPrecGen` auf PNwA | `alignment_based_etc_pnwa` |
| `pnwa_precision_status == "ok"`, `pnwa_constraint_count == 0` | PM4Py `precision_alignments` auf reinem Netz | `alignment_based_etc_pure_net_pm4py` |
| `pnwa_precision_status != "ok"` (Fallback) | PM4Py `precision_alignments` auf reinem Netz | `alignment_based_etc_pure_net_pm4py_fallback` |

**Fallback-Pfad** (Stand: Log 13 / semi-strukturiert): wenn `AlignmentPrecGen` auf der Java-Seite einen Fehler oder `skipped`-Status meldet (typischerweise weil der MixedParadigm-Replayer kein `PNRepResult` liefert und damit kein Alignment für die ETC-Berechnung existiert), exportiert der Python-Pfad den **Pure-Net-PM4Py-Wert** als primäre Precision — mit `precision_method = alignment_based_etc_pure_net_pm4py_fallback` und `precision_scope = pure_net_fallback`. Die UI rendert das mit dem Hinweis *"pure net / PM4Py (fallback — AlignmentPrecGen unavailable)"* und hängt eine Warnung an, wenn `precision_pure_net_meaningful == False` (d.h. Pure-Net-Fitness < 0.95). Damit ist die Tabellenspalte nie leer, aber Konsumenten erkennen am Method-String, dass der Wert auf einem anderen Zustandsraum gemessen wurde (kein Declare-Automaton).

**Symmetrischer Fitness-Fallback**: dieselbe Logik gilt für `fitness`. Wenn `mpcc_status != "success"`, fällt `quality_metrics.fitness` auf die PM4Py-Alignment-Fitness des reinen Petri-Netzes zurück, mit `fitness_method = alignment_based_pure_net_pm4py_fallback` und `fitness_scope = pure_net_fallback`. `quality_metrics.mpcc_fitness` bleibt unverändert `null`, sodass Methodik und Rohwert klar getrennt bleiben.

**Warum?** Auf Log03_looselyStructured liefern Imperative und Fusion strukturell identische Petri-Netze (12 Plätze, 14 Transitionen, 8 Tau, 34 Kanten, Fitness = 1.0, 0 Constraints) — aber unterschiedliche Precision-Werte (0.7441 vs 0.5228), weil zwei verschiedene ETC-Implementierungen verglichen werden (PM4Py-Python vs ProM-Java). Die wahrscheinlichste Quelle der Lücke ist die unterschiedliche Behandlung der 8 Tau-Transitionen im `available`-Set (PM4Py "silent closure" vs ProM Synchronous-Product-Reachability).

**Folge:** Sobald MINERful keine Constraints liefert, ist Fusion algorithmisch ein Inductive Miner (gleiches Skelett, gleiche Tau-Labels `tau split` / `tau join` / `tau from tree`) — die Precision sollte dann auch denselben Wert wie der Imperative Miner liefern. Mit dem PM4Py-Override wird das erfüllt.

**Was bleibt zur Transparenz erhalten?** Die Felder

- `quality_metrics.precision_pnwa_alignmentprecgen` — der ursprüngliche AlignmentPrecGen-Wert auf PNwA,
- `quality_metrics.precision_pure_net_pm4py` — der PM4Py-Wert auf reinem Netz (nur gesetzt, wenn der Override aktiv war),
- `quality_metrics.precision_method` — zeigt an, welche Implementierung in `precision` landet,

sind immer im Manifest sichtbar.

**Caveat:** Aggregate (Mittelwert, Median) der Precision-Spalte über strukturierte und unstrukturierte Logs hinweg mischen implizit zwei Implementierungen. Die Skala ($[0,1]$) und die Interpretation bleiben identisch, aber Tabellen mit beiden Log-Typen sollten den `precision_method` mitführen.

## 8. Vollständiges Metrik-Inventar (UI-Legende)

Die zentrale, jederzeit aktuelle Übersicht aller im Tool gemessenen Metriken — pro Metrik mit exakter Definition, Tool/Library, Literaturquelle, Scope und Vorbehalten — ist in der Comparison-App als ausklappbare Legende unter der Vergleichstabelle eingebunden. Die Implementierung liegt in [`comparison_app/ui/components/metrics_legend.py`](../comparison_app/ui/components/metrics_legend.py) und ist nach den vier Behavioral-Quality-Dimensionen aus **Augusto et al. 2019** strukturiert:

1. **Fitness / Replayability** — Adriansyah 2014, Rozinat 2008, Maggi 2011, De Smedt 2015
2. **Precision / Behavioral Restrictiveness** — Adriansyah 2012, Muñoz-Gama & Carmona 2010, De Smedt 2015 + Westergaard/Slaats 2013
3. **Generalization** — van der Aalst, Adriansyah, van Dongen 2012 (Heuristik)
4. **Behavioral Diagnostics** — Hybrid-spezifisch (PNwA constraint count, Hybrid Precision Lift Δ — siehe §9) und Declare-Constraint-Diagnostik (Maggi 2011, Burattin/Maggi/Sperduti 2012)
5. **Structural Complexity** — Cardoso 1990 / Mendling 2008 (CFC), di Ciccio & Mecella 2015 (constraint density)

Diese §8 ist die schriftliche Doppelung des UI-Inhalts; sie sollte mit dem `_LEGEND_MD`-Block in `metrics_legend.py` synchron gehalten werden.

## 9. Hybrid Precision Lift Δ (Phase B)

**Definition:** $\text{lift}_\Delta = \text{precision}_{\text{PNwA}} - \text{precision}_{\text{pure-net}}$

mit $\text{precision}_{\text{PNwA}}$ aus AlignmentPrecGen (De Smedt 2015) und $\text{precision}_{\text{pure-net}}$ aus PM4Py `precision_alignments` (Adriansyah 2012). **Beide Operanden teilen die ETC-Maß-Definition**, aber operieren auf unterschiedlichen Zustandsräumen (PNwA vs Pure Petri-Netz). Der Lift ist deshalb ein **Indikator** für die durch Declare-Constraints zusätzlich induzierte Behavioral Restrictiveness — **keine** paradigm-neutrale Precision-Differenz.

**Sichtbarkeitsregel** in der UI und im Manifest: das Feld `quality_metrics.hybrid_precision_lift` wird **nur** gesetzt, wenn:
- `pnwa_precision_status == "ok"` (AlignmentPrecGen erfolgreich) UND
- `precision_pure_net_pm4py` ist nicht `None` UND
- `precision_pure_net_meaningful == True` (siehe Threshold unten).

In allen anderen Fällen: `None`, in der UI als "—" dargestellt.

**Threshold `precision_pure_net_meaningful`:** der Boolean wird gesetzt auf $\text{fitness}_{\text{pure-net}} \geq 0.95$. Die Schwelle ist eine **heuristische Wahl** mit folgender Begründung: PM4Py ETC-Precision kollabiert bei niedriger Fitness systematisch auf Werte nahe 0, weil Alignments mit vielen Log-only-Moves den `available`-Trie verschmutzen — ab ca. 95% Trace-Coverage werden diese Verzerrungen empirisch klein. Die Schwelle ist willkürlich (kein Literatur-Standard), wird aber an dieser Stelle dokumentiert und kann via Konstante in [fusion_miner/evaluation.py](evaluation.py) angepasst werden.

**Tooltip-Text in der UI** (in `metrics_legend.py` und als `title=`-Attribut auf der Tabellenzeile):

> *"Difference between PNwA precision (AlignmentPrecGen on Petri-net × Declare-automata; De Smedt 2015) and pure-net PM4Py precision (Adriansyah 2012) for the same FusionMINERful result. Interpreted as an indicator of behavioral restriction added by constraints, not as a paradigm-neutral precision gain. Shown only when both values are present and pure-net fitness ≥ 0.95."*
