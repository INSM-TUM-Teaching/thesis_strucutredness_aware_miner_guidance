# Control-Flow Complexity (CFC)

## Zweck

CFC ist eine strukturelle Komplexitätsmetrik für Prozessmodelle, die das
Verzweigungsverhalten gewichtet zusammenfasst. Sie ergänzt die existierenden
Größen-Metriken (`n_places`, `n_transitions`, `n_arcs`, `n_constraints`) um
einen Wert, der zwischen einer linearen Sequenz (CFC = 0) und einem stark
verzweigten Modell unterscheidet.

## Definition

Cardoso (2005, 2008) definiert CFC ursprünglich für Modellsprachen mit
expliziten Gateways (BPMN, EPC):

```
CFC = Σ split-Beitrag(g)   über alle Splits g
```

mit

| Split-Typ | Beitrag |
|-----------|---------|
| XOR-Split mit n ausgehenden Branches | n |
| OR-Split mit n ausgehenden Branches  | 2^n − 1 |
| AND-Split                            | 1 |

Mendling (2008) überträgt die Metrik auf Petri-Netze. Da Standard-Petri-Netze
keine OR-Splits kennen, vereinfacht sich die Formel zu:

```
CFC = Σ |p•|   über alle Places p mit |p•| > 1   (XOR-Split-Beitrag)
    + Σ 1      über alle Transitions t mit |t•| > 1  (AND-Split-Beitrag)
```

Dabei sind `p•` die ausgehenden Transitions eines Place und `t•` die
ausgehenden Places einer Transition. **Joins** (mehrere eingehende Arcs)
tragen nicht zur CFC bei — die Metrik misst ausschließlich Splits.

τ-Transitions werden mitgezählt: Inductive-Miner-Output verwendet stille
Splits, um Verzweigungslogik zu kodieren; sie ignorieren würde echte
Komplexität verbergen.

Höhere CFC-Werte deuten auf mehr Entscheidungs- und Synchronisations-Logik
und damit empirisch auf schwerer verständliche Modelle hin
(Mendling 2008, Kapitel 3).

## Anwendbarkeit auf die drei Miner

| Miner | Modell-Typ | CFC sinnvoll? |
|-------|------------|---------------|
| Imperative (PM4Py, Inductive Miner) | Petri-Netz | ✅ direkt berechenbar |
| Fusion (FusionMINERful) | Hybrid: PNwA + DECLARE-Constraints | ⚠️ nur prozeduraler Anteil (PNML) |
| Declarative (MINERful) | DECLARE-Constraints | ❌ nicht definiert |

**Begründung Declarative:** DECLARE-Modelle haben keine expliziten Gateways.
Eine Konvertierung zu Petri-Netz (z. B. via DFA) würde die Komplexität der
Konvertierung statt die des Modells messen und wäre nicht mehr mit den
anderen Minern vergleichbar.

**Begründung Fusion:** Die deklarative Constraint-Schicht eines Fusion-Modells
hat keine Gateway-Semantik und bleibt bewusst unberücksichtigt. Der
ausgewiesene CFC-Wert misst nur den prozeduralen PNML-Backbone und ist
deshalb in der UI mit dem Hinweis „procedural part only" gekennzeichnet.

## Implementierung

### Berechnungsfunktion

[`shared/complexity_metrics.py`](complexity_metrics.py):

```python
def compute_cfc(net) -> int:
    cfc = 0
    for place in net.places:
        out_deg = len(place.out_arcs)
        if out_deg > 1:
            cfc += out_deg
    for transition in net.transitions:
        if len(transition.out_arcs) > 1:
            cfc += 1
    return cfc
```

### Integration

| Ort | Änderung |
|-----|----------|
| [`imperative_miner/evaluation.py`](../imperative_miner/evaluation.py) | `cfc` in `_extract_net_stats(net)` aufgenommen; landet im `row`-Dict |
| [`fusion_miner/evaluation.py`](../fusion_miner/evaluation.py) | Lädt PNML in `_compute_metrics` über `pm4py.read_pnml` und schreibt `metrics["cfc"]` |
| [`comparison_app/ui/components/tabs/comparison.py`](../comparison_app/ui/components/tabs/comparison.py) | Neue Tabellenzeile „Control-Flow Complexity (CFC)" mit `fus_note: "procedural part only"`; Declarative-Spalte zeigt `—` |

### Cache

Kein Bump von `CACHE_VERSION` nötig — alte Cache-Einträge geben für
`imp_m.get("cfc")` einfach `None` zurück und das UI zeigt `—`. Aktuelle Werte
nach Re-Run oder Löschen von `.miner_cache/`.

## Tests

[`tests/test_complexity_metrics.py`](../tests/test_complexity_metrics.py)
prüft hand-konstruierte Petri-Netze:

- Sequenz (keine Splits) → CFC = 0
- XOR-Split mit n Branches → CFC = n (für n = 2, 3, 5)
- AND-Split → CFC = 1
- Kombination aus XOR(3) + AND(2) → CFC = 4
- XOR-Join (kein Split) → CFC = 0

## Empirische Plausibilitäts-Prüfung

Imperative Miner auf allen 24 Logs unter `data/with-case-ids/`
(Token-Replay-Konformanz):

| Strukturklasse | n | Mean CFC | Median |
|----------------|---:|---------:|-------:|
| structured        | 7 | 4.57 | 5.0 |
| semiStructured    | 7 | 7.14 | 6.0 |
| looselyStructured | 7 | **10.57** | 10.0 |
| unstructured      | 3 | 4.33 | 5.0 |

Beobachtungen:
- Monotoner Anstieg `structured → semi → loose`, wie nach Mendling 2008
  erwartet.
- Konkretes Vergleichspaar: `Log01_structured` CFC = 3 vs.
  `Log03_looselyStructured` CFC = 12 (Faktor 4×).
- Die `unstructured`-Klasse fällt zurück, weil der Inductive Miner auf
  chaotischen Logs kollabierte Modelle erzeugt (Log09: 5 Transitions, CFC = 1).
  Diese Discovery-Limitation ist als Fußnote in der Thesis zu nennen.

## Wissenschaftliche Einschränkungen (für die Thesis)

1. **CFC misst nur Splits, nicht Joins.** Komplexe Synchronisation
   (mehrfache Joins) trägt nicht bei.
2. **CFC ist sprach-spezifisch.** Der Wert für ein Petri-Netz ist nur
   bedingt mit dem für ein BPMN-/EPC-Modell vergleichbar — OR-Splits
   existieren in einer Klasse nicht.
3. **Discovery-Algorithmus prägt das Ergebnis.** Inductive Miner erzeugt
   block-strukturierte Netze mit τ-Splits; Heuristics Miner liefert oft
   freier strukturierte Netze. CFC misst stets das *erzeugte* Modell, nicht
   die *inhärente* Log-Komplexität.
4. **Nicht für Declarative anwendbar.** Wie oben begründet.

## Referenzen

### Direkt für Definition und Implementierung verwendet

- **Cardoso, J. (2005).** *Control-Flow Complexity Measurement of Processes
  and an Empirical Study.* In: Workflow Handbook 2005, S. 17–29.
  → Originaldefinition von CFC mit den Beiträgen XOR = n, OR = 2^n − 1,
  AND = 1.
- **Cardoso, J. (2008).** *Business Process Control-Flow Complexity: Metric,
  Evaluation, and Validation.* International Journal of Web Services Research
  5 (2), S. 49–76.
  → Erweiterte Validierung der Metrik gegen Weyukers neun
  Software-Engineering-Axiome; Grundlage für die Verwendung von CFC als
  vergleichbare strukturelle Komplexitätsgröße.
- **Mendling, J. (2008).** *Metrics for Process Models — Empirical Foundations
  of Verification, Error Prediction, and Guidelines for Correctness.* Lecture
  Notes in Business Information Processing, Bd. 6, Springer.
  → Kapitel 3 überträgt CFC auf Petri-Netze: XOR-Split = Place mit
  \|p•\| > 1, AND-Split = Transition mit \|t•\| > 1. Diese Variante ist die
  hier implementierte Formel.

### Empirische Schwellenwerte und Verständlichkeit

- **Mendling, J., Reijers, H. A., Cardoso, J. (2007).** *What Makes Process
  Models Understandable?* In: BPM 2007, LNCS 4714, S. 48–63.
  → Empirischer Nachweis, dass strukturelle Komplexitätsmetriken (inkl. CFC)
  mit menschlicher Verständlichkeit korrelieren — wichtigste Begründung,
  warum CFC für die Thesis-Vergleichstabelle relevant ist.
- **Sánchez-González, L., García, F., Mendling, J., Ruiz, F., Piattini, M.
  (2010).** *Prediction of Business Process Model Quality Based on Structural
  Metrics.* In: ER 2010, LNCS 6412, S. 458–463.
  → Liefert empirische Schwellenwerte für CFC und verwandte Metriken;
  Grundlage für eine Diskussion „ab wann ist ein CFC-Wert hoch?".

### Methodisches Umfeld der Thesis (für die Begründung „CFC nicht für DECLARE")

- **Pesic, M., Schonenberg, H., van der Aalst, W. M. P. (2007).** *DECLARE:
  Full Support for Loosely-Structured Processes.* In: EDOC 2007, S. 287–300.
  → Definition deklarativer Constraint-Modelle ohne explizite Gateways —
  begründet, warum CFC dort strukturell nicht definiert ist.
- **Di Ciccio, C., Mecella, M. (2015).** *On the Discovery of Declarative
  Control Flows for Artful Processes.* ACM Transactions on Management
  Information Systems 5 (4), Art. 24.
  → MINERful-Algorithmus, der die deklarativen Constraints im
  `declarative_miner/` und `fusion_miner/` produziert.
- **Leemans, S. J. J., Fahland, D., van der Aalst, W. M. P. (2013).**
  *Discovering Block-Structured Process Models from Event Logs — A
  Constructive Approach.* In: PETRI NETS 2013, LNCS 7927, S. 311–329.
  → Inductive Miner, der die Petri-Netze des `imperative_miner/` erzeugt;
  erklärt das Auftreten stiller τ-Split-Transitionen, die in der CFC
  bewusst mitgezählt werden.

### Tooling

- **Berti, A., van Zelst, S. J., van der Aalst, W. M. P. (2019).** *Process
  Mining for Python (PM4Py): Bridging the Gap Between Process- and Data
  Science.* In: ICPM Demo Track 2019, arXiv:1905.06169.
  → PM4Py liefert die `PetriNet`-Datenstruktur (`net.places`,
  `net.transitions`, `place.out_arcs`), auf der `compute_cfc` operiert,
  sowie `pm4py.read_pnml` für den Fusion-Miner.
- **van der Aalst, W. M. P. (2016).** *Process Mining: Data Science in
  Action.* 2. Aufl., Springer.
  → Standard-Lehrbuchreferenz für Petri-Netz-Notation, Workflow-Netze und
  den Discovery-Begriff, auf den die gesamte Comparison App aufbaut.
