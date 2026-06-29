# ARM-Coverage (SF-2): Modell → Relationen → native/forced/missing

Dokumentation der ARM-Coverage-Pipeline: **wie ein entdecktes Modell (imperativ,
deklarativ, hybrid) in ein gemeinsames Relationen-Vokabular übersetzt und gegen
die Activity-Relationship-Matrix (ARM) eines Logs klassifiziert wird** — und wie
das Ergebnis als qualitative **SF-2-Evidenz** in die Comparison-App einfließt.

> **Wichtig vorweg:** Auf der imperativen Seite wird **kein Petri-Netz**
> umgewandelt, sondern der **Process Tree** (Operator-Baum von IMf). Das ist
> Absicht — siehe [§2 „Warum Process Tree, nicht Petri-Netz"](#2-warum-process-tree-nicht-petri-netz).

---

## Inhalt

1. [Zweck & Gesamtfluss](#1-zweck--gesamtfluss)
2. [Warum Process Tree, nicht Petri-Netz](#2-warum-process-tree-nicht-petri-netz)
3. [Das gemeinsame Tag-Vokabular](#3-das-gemeinsame-tag-vokabular)
4. [ARM-Seite: Zellen → ExpectedRelation](#4-arm-seite-zellen--expectedrelation)
5. [Modell-Seite: die drei Extraktoren](#5-modell-seite-die-drei-extraktoren)
   - [5.1 Imperativ — Process-Tree-Footprint](#51-imperativ--process-tree-footprint)
   - [5.2 Deklarativ — Declare-Templates](#52-deklarativ--declare-templates)
   - [5.3 Fusion — Netz + Overlay (zonen-aware)](#53-fusion--netz--overlay-zonen-aware)
6. [Klassifikation: native / forced / missing / …](#6-klassifikation-native--forced--missing-)
7. [Score & Dominanz-Filter](#7-score--dominanz-filter)
8. [Integration in die App](#8-integration-in-die-app)
9. [Recompute & Caching](#9-recompute--caching)
10. [Methodischer Vorbehalt (§7)](#10-methodischer-vorbehalt-7)
11. [CLI & Tests](#11-cli--tests)
12. [Scope / Autorenschaft](#12-scope--autorenschaft)

---

## 1. Zweck & Gesamtfluss

SF-2 fragt: *Bildet ein Miner die dominanten ARM-Beziehungen eines Logs
**strukturtreu (nativ)** ab oder nur **erzwungen** (über einen Workaround)?*

Die ARM (Andree et al. 2025) ist die paradigma-neutrale **Ground-Truth** der
Log-Struktur: pro Aktivitätspaar ein `(temporal, existential)`-Urteil. Ein
entdecktes Modell drückt jedes Paar entweder idiomatisch (nativ), umständlich
(forced) oder gar nicht (missing) aus. Genau das misst die Pipeline.

```
                    ┌──────────────────────────────────────────────┐
   Log (.xes) ──►   │  matrix_classifier (Rust, Andree et al.)     │ ── ARM cells
                    └──────────────────────────────────────────────┘
                                        │
                                        ▼
              build_expected_relations(arm)   ── Richtung normalisiert ──►  ExpectedRelation[]
                                        │
   Modell (JSON) ──► load_model_index(miner, result_data)  ──►  ModelRelationIndex
       imp:  process_tree_structure  (Operator-Baum)             { (src,tgt): {tags} }
       decl: MINERful-Constraints JSON
       fus:  hybrid_model.json (+ pnwa_model.json)
                                        │
                                        ▼
                 classify_relation(rel, idx, paradigm)  ──►  RelationVerdict
                                        │
                                        ▼
                 map_coverage(...)  ──►  CoverageReport { verdicts, counts, coverage_score }
```

Alle drei Modellquellen werden in **dasselbe gerichtete Tag-Vokabular**
normalisiert, sodass die Übersetzungstabelle (`TRANSLATION`) weitgehend
paradigma-**unabhängig** ist. Die einzige Paradigma-Asymmetrie steckt in einem
einzigen Set: `PARADIGM_IMPOSSIBLE`.

**Engine:** `miners/shared/arm_coverage.py`
**ARM-Runner:** `miners/shared/arm_runner.py` (Subprozess + Datei-Cache `.miner_cache/arm/`)

---

## 2. Warum Process Tree (imperativ), und was R1 wirklich verbietet

Harte Modulregel **R1: kein Parsing von PNG-/Bild-Artefakten.** Jede Modellaussage
stammt aus **JSON/Text**. R1 verbietet *Bilder*, nicht *Netze-aus-JSON* — ein
Petri-Netz aus `pnwa_model.json` zu lesen ist R1-konform (siehe Fusion, §5.3).

Für den **imperativen** Miner ist der Process Tree die natürliche Quelle:

| Quelle | imperativ | Konsequenz |
|---|---|---|
| Petri-Netz | bräuchte Reachability, um directly-/eventually-follows zu bestimmen | hier unnötig — IM liefert den Baum direkt |
| **Process Tree** | Verhaltensrelationen folgen **direkt aus der Operator-Semantik** | exakt, deterministisch, ohne Solver |

IMf liefert ohnehin einen Process Tree; dessen Operatoren (`→ X + * O`) kodieren
Reihenfolge, Auswahl, Nebenläufigkeit und Schleifen **explizit**. Ein Footprint
(directly/eventually-follows, parallel, exclusive) lässt sich daraus rein
strukturell ableiten. Der Baum kommt aus `metrics.process_tree_structure`; fehlt
er (alter Cache), wird er via `pm4py.discover_process_tree_inductive` aus dem Log
nachgerechnet (`_backfill_process_tree`).

> Für **Fusion** gibt es keinen Process Tree, aber ein **PNWA-Petri-Netz** (JSON).
> Dort *wird* ein Netz-Footprint via beschränkter Reachability berechnet — das ist
> R1-konform und liefert XOR/AND korrekt (§5.3). Reachability ist also kein Tabu;
> sie ist nur für IM unnötig.

---

## 3. Das gemeinsame Tag-Vokabular

Jedes Modell wird zu einem `ModelRelationIndex`: `by_pair[(src,tgt)] -> {tags}`,
**gerichtet** (Ausnahme: symmetrische Tags werden beidseitig gespeichert).

| Tag | Bedeutung | symmetrisch? |
|---|---|---|
| `TAG_CHAIN` | direkte Nachfolge `x → y` (unmittelbar) | nein |
| `TAG_ORDER` | irgendwann-Nachfolge `x … y` | nein |
| `TAG_PARALLEL` | Nebenläufigkeit | ja |
| `TAG_COEXIST` | Ko-Auftreten ohne Ordnung | ja |
| `TAG_EXCLUSIVE` | wechselseitiger Ausschluss (XOR) | ja |
| `TAG_RESP_EXIST` | `x vorhanden ⇒ y vorhanden`, keine Ordnung | nein |
| `TAG_NEG_ORDER` | Reverse-Order-Evidenz aus einem `Not*`-Constraint | nein |

---

## 4. ARM-Seite: Zellen → ExpectedRelation

Die ARM speichert **beide** Richtungen (`a→b` *und* `b→a`).
`build_expected_relations(arm)` kollabiert jedes ungeordnete Paar zu **einer**
`ExpectedRelation` (kein Doppelzählen):

1. **Richtungsnormalisierung** (`_orient`): Temporal-Ordnung (`Forward`/`Backward`)
   legt `source → target` fest; ohne Temporal-Ordnung entscheidet die
   existenzielle Implikationsrichtung; sonst deterministische Sortierung.
2. **Kind-Ableitung** (`_relation_kind`): das `(temporal, existential)`-Paar wird
   auf eine kanonische Relationsart abgebildet, z. B. `eventual_implication`,
   `none_negated_equivalence`, `direct_equivalence`, … `NegatedEquivalence`/`Nand`
   (Ausschluss) dominiert dabei jede Temporal-Angabe.
3. `none_none`-Paare bleiben mit `is_present=False` als **`correctly_absent`-Kandidaten** erhalten.

---

## 5. Modell-Seite: die drei Extraktoren

### 5.1 Imperativ — Process-Tree-Footprint

`extract_relations_imperative` ruft `_tree_footprint` (rekursiv) und mappt die
Footprint-Mengen auf Tags.

**Operator-Semantik** (`_tree_footprint`):

| Operator | Wirkung auf den Footprint |
|---|---|
| `→` Sequence | für jedes Kind *i* vor Kind *j*: **eventually** (alle Aktivitäten von *i* × alle von *j*); zwischen `ends(i)` und `starts(i+1)`: **directly** |
| `X` XOR | alle Kreuzpaare zwischen Kindern: **exclusive** (beidseitig) |
| `+` Parallel | alle Kreuzpaare: **parallel** (beidseitig) |
| `*` Loop(do, redo) | `ends(do)→starts(redo)` & `ends(redo)→starts(do)`: **directly**; `do × redo`: **eventually** (beidseitig) |
| `O` Optional / unbekannt | Kinder als Alternativen ohne Ordnung |

`tau`-Blätter (`label=None`) werden ignoriert. `eventually ⊇ directly`.

**Mapping auf Tags** (`extract_relations_imperative`):

```
directly   → TAG_CHAIN + TAG_ORDER
eventually → TAG_ORDER
parallel   → TAG_PARALLEL
exclusive  → TAG_EXCLUSIVE
```

**Worked example** — der reale Log01-Baum `→(a, b, X(c, +(d, e)), f)`:

```
a→b           directly  →  CHAIN+ORDER
b→c, b→d, b→e directly  →  CHAIN+ORDER      (X startet mit {c,d,e})
c→f, d→f, e→f directly  →  CHAIN+ORDER      (X endet mit {c,d,e})
a→c,a→d,a→e,a→f, b→f     eventually → ORDER (nicht-adjazent)
c↔d, c↔e      exclusive →  EXCLUSIVE        (XOR-Zweige)
d↔e           parallel  →  PARALLEL         (AND-Block)
```

Gegen die zugehörige ARM ergibt das `coverage_score = 1.0` (alles nativ) —
siehe Test `test_log01_shaped_tree_all_native`.

### 5.2 Deklarativ — Declare-Templates

`extract_relations_declarative` liest die MINERful-Constraints-JSON und mappt
jedes binäre Template (`_declare_tags`) auf gerichtete Tags:

Parameter-Konvention: `parameters = [[base], [implied]]` → `(a,b)` mit
`a=base, b=implied`; positive Ordnungs-Templates bedeuten `base → implied`.

| Template | Tags |
|---|---|
| `ChainSuccession/ChainResponse/ChainPrecedence` | `CHAIN + ORDER` auf `(a,b)` |
| `Succession/Response/Precedence` (+ `Alternate*`) | `ORDER` auf `(a,b)` |
| `CoExistence` | `COEXIST` (beidseitig) |
| `RespondedExistence` | `RESP_EXIST` auf `(a,b)` |
| `NotCoExistence` | `EXCLUSIVE` (beidseitig) |
| `NotSuccession/NotChainSuccession/NotResponse/NotChainResponse/`<br>`NotPrecedence/NotChainPrecedence` | `NEG_ORDER` auf `(b,a)` |
| unär (`Init/End/Participation/AtMost/AtLeast/Absence`) | — (kein Paar) |

> **Richtung der negativen Templates (verifiziert am MINERful-Quellcode):** Alle
> `Not*`-Ordnungs-Templates verbieten die Ordnung `base→implied` und sind daher
> Reverse-Evidenz für `implied→base` → `NEG_ORDER` auf `(b,a)`. Beleg:
> `NotSuccession(base,implied)` zerfällt in seine Forward-Hälfte
> `NotResponse(base,implied)` **und** Backward-Hälfte `NotPrecedence(base,implied)`
> — beide auf derselben `(base,implied)`-Reihenfolge (MINERful
> `NotSuccession.java:getPossibleForward/BackwardConstraint`). Ein früherer Bug
> mappte `NotPrecedence` fälschlich auf `(a,b)` (seit 2026-06-03 gefixt).

**Verifikation (erschöpfend, alle 29 Specs):**
- **Parsing:** alle Parameter sind `(1,)` oder `(1,1)` — keine Multi-Activity-
  Branches, nichts malformed; alle Constraint-Aktivitäten ⊆ `tasks`.
- **Vollständigkeit:** alle 10 im Datensatz vorkommenden binären Templates werden
  übersetzt — keines wird verschluckt.
- **Label-Konsistenz:** 0 Mismatches Spec↔ARM (jede Aktivität existiert in der
  ARM → Tags landen auf realen Paaren).
- **Positive Ordnung:** 19/19 stimmen mit der ARM-Temporalrichtung überein
  (base→implied = Forward), 0 Widersprüche.
- **Negative Ordnung:** 39 `implied→base` + 30 `no order` konsistent; die 3
  scheinbaren Widersprüche sind alle `NotChain*` gegen *eventual*-Ordnung
  (chain ≠ eventual → erlaubt), also keine echten.

### 5.3 Fusion — PNWA-Petri-Netz-Footprint + Overlay

`extract_relations_fusion(hybrid, pnwa=None)` wählt die Kontrollfluss-Quelle in
dieser Reihenfolge:

1. **PNWA-Petri-Netz** (`pnwa` mit `places`/`transitions`/`arcs`) — die
   strukturtreue Quelle. Sein Behavioral-Footprint wird per **beschränkter
   Marking-Reachability** abgeleitet (`_fusion_net_entries` → `_net_footprint`):
   - **XOR** (Place mit mehreren Ausgangs-Transitionen) → `EXCLUSIVE`
   - **AND** (τ-Split/Join über mehrere Places) → `PARALLEL`
   - directly-follows (nur τ dazwischen) → `CHAIN + ORDER`; strikte Weak-Order → `ORDER`
   - **Tote Transitionen** (kein Arc / nie feuerbar, z. B. entropy-abstrahierte
     Aktivitäten) erhalten **kein** Tag — sie würden sonst fälschlich als
     `EXCLUSIVE` (XOR) gewertet. `EXCLUSIVE` gilt nur, wenn **beide** Aktivitäten
     real feuern, aber nie in derselben Ausführung.
   - Fallback auf `None` bei **unsafe / zyklischen (Loop-) / zu großen** Netzen
     (`_NET_MARKING_CAP`) — dann greift Schritt 2.
2. **Flacher prozeduraler Graph** (`hybrid['procedural']` nodes/edges) — eine
   verlustbehaftete Projektion, die XOR/AND **nicht** von Sequenz unterscheiden
   kann. Nur Fallback (`_fusion_procedural_entries`).

Auf **beiden** Pfaden wird der **deklarative Overlay** (existenziell/negativ:
`hybrid.declarative` + binäre PNWA-Constraints, `+`-Suffix gestrippt)
oben drauf gemerged (`_fusion_declarative_entries`).

**Warum das wichtig ist (Worked Example, Log01):** Der flache prozedurale Graph
des Fusion-Runs ist degeneriert (Senke fälschlich `d` statt `f`) → Coverage
**0.6** (9 native, 6 missing). Das PNWA-Netz rekonstruiert dagegen exakt
`→(a, b, X(c, +(d,e)), f)` (identisch zum IM-Process-Tree) → Coverage **1.0** (15
native). Der frühere niedrige Wert war ein **Artefakt der falschen Repräsentation**,
kein echter Strukturverlust von Fusion.

> **R1-konform:** Das PNWA-Netz wird als **JSON** (`places`/`transitions`/`arcs`)
> gelesen, nicht als Bild. Die Reachability ist bei diesen kleinen, sound
> block-strukturierten Netzen beschränkt und sicher; Loops/unsafe Netze fallen
> bewusst auf den Flachgraphen zurück (Behavioral-Profile würde Wiederholung mit
> Nebenläufigkeit verwechseln).

`PARADIGM_IMPOSSIBLE["fusion"]` ist leer (Fusion kann jede ARM-Art ausdrücken);
„nativ" entsteht nur, wenn der passende Tag (z. B. `EXCLUSIVE` für XOR) vorliegt.

---

## 6. Klassifikation: native / forced / missing / …

`classify_relation(rel, idx, paradigm)` mit `tags = idx.tags(rel.source, rel.target)`:

| Bedingung | Verdict |
|---|---|
| `rel` nicht present (`none_none`) **und** Modell hat Tags | `spurious` (Über-Struktur) |
| `rel` nicht present **und** Modell hat keine Tags | `correctly_absent` |
| `rel.kind ∈ PARADIGM_IMPOSSIBLE[paradigm]` | `not_applicable` (fair ausgeschlossen) |
| `tags ∩ TRANSLATION[kind]["native"]` ≠ ∅ | `native` |
| `tags ∩ TRANSLATION[kind]["forced"]` ≠ ∅ | `forced` |
| sonst | `missing` |

`TRANSLATION` definiert pro ARM-Kind, welche Tags es **idiomatisch** (`native`)
vs. per **Workaround** (`forced`) ausdrücken. Beispiel `eventual_implication`:
`native = {ORDER, CHAIN}`, `forced = {RESP_EXIST, NEG_ORDER, COEXIST}`.

`PARADIGM_IMPOSSIBLE` kodiert die **Fairness-Asymmetrie**: ein Process Tree kann
keine *order-freie existenzielle Implikation* (`none_implication`) ausdrücken →
für `imperative` `not_applicable` statt `missing`. Declarative/Fusion: leer.

> **Richtung zählt:** `tags` werden gerichtet (`source→target`) nachgeschlagen.
> Eine ARM-Relation `a→b`, die das Modell nur als `b→a` ordnet, ist `missing`.

---

## 7. Score & Dominanz-Filter

`compute_sf3_score(counts)` (Name historisch, Dimension ist SF-2):

```
coverage_score    = (native + 0.5·forced) / (native + forced + missing)
absence_precision = correctly_absent / (correctly_absent + spurious)
```

`not_applicable` zählt nie in den Nenner. Beide `None`, wenn ihr Nenner 0 ist.

**Dominanz-Filter** (`map_coverage(..., dominant_only=True)`): SF-2 wertet nur die
**dominanten** Relationen des Logs — `is_present == True`, also present **oberhalb
der ARM-Schwellen**. ARM-Zellen tragen real **kein** Support-/Frequenz-Feld
(verifiziert), darum **sind die `temporal`/`existential`-Thresholds der
Dominanz-Regler**; ein erfundenes Frequenz-Maß gibt es nicht. Nicht-dominante
(`none_none`-)Paare werden aus `verdicts`/`counts`/Score entfernt und separat unter
`counts["excluded_non_dominant"]` ausgewiesen. Der Default (`dominant_only=False`)
ist unverändert (Regressionstest).

---

## 8. Integration in die App

| Stelle | Datei | Was |
|---|---|---|
| **Resolver (Kern)** | `comparison_app/ui/arm_coverage_proxies.py` | `dominant_coverage_report(...)` (voller Report) + `arm_coverage_proxies(...)` (flache Keys). lru-gecacht, **defensiv** (`None` statt Exception). |
| **ARM-Tab Panel** | `comparison_app/ui/components/tabs/arm.py` | Pro gecachtem Miner: Zähler + Tabelle der dominanten Relationen (`source/target/kind/verdict/construct/rationale`), §7-Caveat, Thresholds als Dominanz-Regler. |
| **Validation SF-2-Callout** | `comparison_app/ui/components/validation_page.py` | `_proxy_callout` mergt `arm_*`-Chips + **unverbindlichen** Kategorie-Vorschlag + §7-Caveat. Setzt `grade` **nie** automatisch. |
| **Session-Daten** | `comparison_app/app.py` | `_miner_session_entry` mergt die `arm_*`-Keys (ARM wird einmal berechnet, wiederverwendet). |
| **Key-Deklaration** | `comparison_app/ui/metric_proxies.py` | deklariert die `arm_*`-Keys als `None` — **subprozessfrei**, rechnet nichts. |
| **Fragebogen** | `qualitative_eval/characteristics_config.yaml` | S-/Sm-/L-SF-2 `proxy.metrics` um die `arm_*`-Keys erweitert. |

**Flache Evidenz-Keys** (alle `None` bei Nichtverfügbarkeit):
`arm_native_ratio`, `arm_forced_ratio`, `arm_missing_ratio` (Summe 1 über
`arm_dominant_n` = native+forced+missing), `arm_coverage_score`,
`arm_suggested_category` (String aus der SF-2-`grade_scale`, **nur Vorschlag**).

Subprozess-Disziplin: Das Rust-ARM-Binary läuft **ausschließlich** im gecachten
Resolver; `_extract_item_metrics` bleibt rein.

---

## 9. Recompute & Caching

Drei Cache-Schichten mit unterschiedlicher Invalidierung:

| Schicht | Key | Invalidierung |
|---|---|---|
| ARM-Matrix (`arm_runner.run_arm`) | `(log-content-hash, temporal, existential)` | nur bei Log- oder Threshold-Änderung |
| Miner-Result (`result_cache`) | `(log_id, miner)`, `log_id = stem + sha1(log)[:8]` | jeder Miner-Run **überschreibt** atomar |
| Proxy-Memo (`_proxies_cached`) | `(miner, log_path, cache_version)` | `cache_version` = mtime der `result_data.json` |

**Was passiert, wenn du ein neues Fusion-Modell rechnest** (Button „Run Fusion"):

1. `run_miners._run_one("fus", …)` erzeugt das neue Hybrid-Modell und ruft
   `result_cache.store("fus", log_id, result)`. **`log_id` bleibt gleich** (das Log
   ist unverändert → gleicher Content-Hash); der Eintrag unter `<log_id>/fus/`
   wird **atomar überschrieben**. Die neue `result_data.json` trägt den
   aktualisierten `run_data.hybrid_model_path`.
2. **Die ARM selbst wird NICHT neu gerechnet** — sie ist eine Eigenschaft des
   *Logs*, nicht des Modells. Coverage = *gleiche* ARM × *neuer* Modell-Index.
3. **ARM-Tab:** `dominant_coverage_report(..., arm=result)` läuft bei jedem Render
   frisch (nicht memoisiert) → rehydriert die neue `result_data.json` → liest das
   neue `pnwa_model.json` → frische Coverage. ✔
4. **Validation-Page SF-2-Chips:** gehen über `_proxies_cached`. Der
   `cache_version`-Token (mtime der frisch geschriebenen `result_data.json`)
   ändert sich beim Store → Cache-Miss → **Recompute**. ✔
   *(Ohne diesen Token wäre die Coverage im selben Prozess veraltet — genau diese
   recompute-awareness ist bewusst eingebaut.)*

**Wie der neue Modell-Index gelesen wird** (`load_model_index`):

| Miner | Quelle in `result_data.json` | Fallback |
|---|---|---|
| `imp` | `metrics.process_tree_structure` | aus Log via `pm4py` nachrechnen (`_backfill_process_tree`) |
| `decl` | `metrics.json_path` (MINERful-Spec) | — |
| `fus` | `run_data.pnwa_model_path` (Petri-Netz, bevorzugt) → sonst `hybrid_model_path` (Flachgraph) | Flachgraph wenn kein/unsafe/zyklisches Netz |

> ✅ **Fragilität behoben (2026-06-03):** Die Modell-JSONs (`pnwa_model.json`,
> `hybrid_model.json`, MINERful-`json_path`) werden jetzt beim Store in den
> Cache-`artifacts/`-Ordner **kopiert** (`result_cache.ARTIFACT_PATH_KEYS`); die
> `result_data.json` zeigt nach Rehydrate auf die *Cache*-Kopie. Damit überlebt
> die Coverage eine Regenerierung/Löschung der Original-`Experimente/`-Dateien
> (Test: `test_model_jsons_survive_original_deletion`).
>
> ⚠️ **Migration:** Cache-Einträge, die **vor** dem Fix gestored wurden, zeigen
> noch auf die Originale — sie werden erst durch einen erneuten Miner-Lauf (oder
> ein Re-Store) migriert. Bis dahin kann `load_model_index` für solche Alt-
> Einträge `FileNotFoundError` werfen → `dominant_coverage_report` gibt `None` →
> Coverage `n/a` (kein Crash). Imperativ war nie betroffen (`process_tree_structure`
> liegt inline in der `result_data.json`, plus pm4py-Backfill).

---

## 10. Methodischer Vorbehalt (§7)

> *„ARM-Coverage = qualitativer Struktur-Hinweis. Die ARM ist
> Input/Ground-Truth; ihre Nutzung als Prüfmaßstab ist eine offene Spannung (§7)
> — kein harter Score."*

Die ARM ist zugleich Eingabe **und** Referenz für native/forced — eine
methodische Zirkularität. Darum: **kein Auto-Grade, keine numerische Schwelle
entscheidet** (e2-measurement-spec §0.3). Die UI zeigt Evidenz-Chips + einen
explizit unverbindlichen *Vorschlag*; die Einordnung (`grade`) bleibt
rater-gesetzt. Niedrige Diskriminierung (z. B. MINERful auf einem strukturierten
Log: viel `missing`) ist ein **Befund**, kein Bug — die Schwellen wurden bewusst
**nicht** auf die Kalibrierungsminer getunt.

---

## 11. CLI & Tests

```bash
# Debug-CLI: Coverage-Report für ein Log + Miner
.venv/bin/python -m miners.shared.arm_coverage --log Log01_structured --miner imp --verbose

# Tests
.venv/bin/python -m pytest miners/shared/tests/test_arm_coverage.py -q
.venv/bin/python -m pytest miners/comparison_app/tests/test_arm_coverage_proxies.py -q
```

Tests sind hermetisch (konstruierte ARM-Zellen + Bäume/Constraints, kein Cache,
kein Java/pm4py nötig); ein Golden-Block nutzt reale `Log01_structured`-Artefakte,
falls vorhanden (sonst automatisch übersprungen).

---

## 12. Scope / Autorenschaft

- **Übersetzungs-Kern** (`arm_coverage.py`: die drei Extraktoren, `TRANSLATION`,
  `PARADIGM_IMPOSSIBLE`, Klassifikation, Score) ist die **vorbestehende Engine** —
  wiederverwendet, nicht dupliziert.
- **Additiv ergänzt:** der `dominant_only`-Filter in `map_coverage` (nicht-brechend).
- **Neu für die SF-2-Integration:** der gecachte Resolver
  `arm_coverage_proxies.py`, die UI-Verdrahtung (ARM-Tab-Panel,
  SF-2-Proxy-Callout, Session-Merge), die Config-Aktualisierung und die Tests.
- **Bewusste Scope-Erweiterung (Fusion-Fix):** `extract_relations_fusion` nutzt
  jetzt das **PNWA-Petri-Netz** statt des kaputten Flachgraphen
  (`_fusion_net_entries`/`_net_footprint`). Die ursprüngliche „kein Reachability-
  Solver"-Leitplanke wurde dafür gezielt aufgeweicht — beschränkt auf kleine,
  sound block-strukturierte Netze, mit Fallback auf den Flachgraphen. **Achtung:**
  dies **ändert alle Fusion-SF-2-Zahlen**; ältere Fusion-Coverage-Werte (z. B.
  Log01 = 0.6) sind veraltet und durch den Netz-Wert (1.0) ersetzt.
- **Korrektur (Declarative-Richtung):** `_declare_tags` mappte `NotPrecedence`
  fälschlich auf `(a,b)` statt `(b,a)`; nun konsistent mit `NotResponse`/
  `NotSuccession` und um `NotChainPrecedence` ergänzt (am MINERful-Quellcode
  verifiziert, §5.2). Numerischer Effekt auf den aktuellen Datensatz minimal
  (`NotPrecedence` kommt 1× vor, auf einem nicht-dominanten Paar).

**Out of scope (weiterhin bewusst nicht getan):** zweite Paradigmen→ARM-
Übersetzung, Play-out, Footprint für **zyklische/unsafe** Netze (Fallback),
**PNG-/Bild**-Parsing, automatisches Setzen von `grade`.
