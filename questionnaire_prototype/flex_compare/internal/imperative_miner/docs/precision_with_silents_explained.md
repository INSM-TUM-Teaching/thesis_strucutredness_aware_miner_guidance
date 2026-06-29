# Warum hohe Precision trotz vieler τ-Transitionen?

Diese Notiz erklärt, warum Petri-Netze des `imperative_miner` mit vielen
**stillen (τ-)Transitionen** in der Auswertung *trotzdem* hohe Precision-Werte
liefern — obwohl die Intuition sagt, dass viele τ-Transitionen ein "fast alles
erlaubendes" Modell erzeugen müssten und die Precision damit nahe Null sein
sollte.

Kurzantwort: **Die τ-Anzahl ist eine *strukturelle* Größe (Operator-Plumbing
des Prozessbaums), keine Aussage über behaviorale Permissivität.** Inductive-
Miner-Netze sind block-strukturiert; jede τ-Transition hat eine lokale,
operator-spezifische Aufgabe. `precision_alignments` misst auf diesen Netzen
genau das, was es soll — und liefert deshalb berechtigt hohe Werte.

---

## 1. Beobachtung

Beim Auswerten von `imperative_miner`-Läufen tritt regelmäßig folgende
Konstellation auf:

- `n_silent_transitions` ist groß (oft in derselben Größenordnung wie
  `n_transitions`/2 oder höher),
- `precision` (Default: `precision_alignments`) liegt trotzdem hoch
  (typisch ≥ 0.8).

Naheliegende Vermutung: *Wenn das Modell strukturell so viele τ-Übergänge
zulässt, dann sollte es behavioural fast jede Aktivitätsfolge akzeptieren —
also müsste Precision niedrig sein.*

Diese Vermutung greift hier nicht. Der Grund liegt in (a) der Klasse von
Petri-Netzen, die der Inductive Miner produziert, und (b) dem genauen
Funktionsprinzip von `precision_alignments`.

---

## 2. Naive Erwartung — und für welches Modell sie korrekt wäre

Die Intuition "viele τ ⇒ alles erlaubt" stimmt für genau eine Modellklasse:
das **Flower Model**.

Ein Flower Model besteht aus *einem* zentralen Place, an dem alle Aktivitäten
$a \in \Sigma$ als Schleife hängen. Seine Sprache ist $\Sigma^{*}$, also jede
beliebige Aktivitätsfolge. ETC-Precision liefert hier am laufenden Knoten:

$$
\frac{|reflected(n)|}{|available(n)|} \;=\; \frac{|reflected(n)|}{|\Sigma|}
$$

Da $|reflected(n)|$ in der Regel viel kleiner als $|\Sigma|$ ist, geht
Precision $\to 0$. Soweit korrekt.

**Der Punkt ist nur:** Inductive-Miner-Netze sind keine Flower Models, auch
wenn sie viele τ-Transitionen enthalten.

---

## 3. Warum die Intuition für IM-Netze nicht greift

Der `imperative_miner` ruft den Inductive Miner aus PM4Py:

- [imperative_miner/evaluation.py:332-333](../evaluation.py:332)
  ```python
  process_tree = pm4py.discovery.discover_process_tree_inductive(log)
  net, im, fm = pm4py.convert.convert_to_petri_net(process_tree)
  ```

Der Inductive Miner erzeugt zuerst einen **Prozessbaum** und übersetzt diesen
operator-weise in ein **block-strukturiertes Workflow-Netz**. Jede
τ-Transition entsteht in einem dieser Operator-Blöcke und hat genau dort eine
lokale Funktion:

- **`×` (Exclusive Choice) mit Skip:** ein τ aktiviert genau den leeren
  Branch — die übrigen Branches bleiben erst aktivierbar, wenn ihr lokaler
  Vorgänger-Place markiert ist.
- **`⟲` (Loop):** ein τ-Redo schließt den Loop-Body und reaktiviert seinen
  Anfangs-Place; ein τ-Exit gibt den Token an die Nachfolger weiter.
- **`∧` (Parallel):** ein τ-Split fächert Tokens auf parallele Branches auf,
  ein τ-Join synchronisiert sie wieder.

Entscheidend: **Keine dieser τ-Transitionen "öffnet das Netz global"**. Sie
operieren ausschließlich auf den lokalen Places ihres Operator-Blocks. Die
Sprache des entstandenen Netzes ist die Sprache des Prozessbaums — also
typischerweise eine *strikte* Teilmenge von $\Sigma^{*}$.

Skizze (XOR mit Skip — fünf Aktivitäten, je eine τ-Skip-Kante; zählt als
fünf τ-Transitionen):

```
              τ  ──────────────────────►
              τ  ─────────►(■ a ■)─────►
   p_in ──┬──►τ  ─────────►(■ b ■)─────►──┬── p_out
          │   τ  ─────────►(■ c ■)─────►  │
          │   τ  ─────────►(■ d ■)─────►  │
          └──►τ  ─────────►(■ e ■)─────►──┘
```

An `p_in` ist die *visible-enabled*-Menge `{a, b, c, d, e}` — und das ist
*alles*. Die fünf τ-Transitionen vergrößern diese Menge nicht; sie sind nur
das Plumbing für den Skip-Branch.

In einem Flower-Model wäre die visible-enabled-Menge an *jedem* Marking
identisch $\Sigma$. In einem IM-Netz hängt sie streng vom lokalen Block ab und
ist meistens deutlich kleiner.

Dass `_count_silent_transitions(net)` (
[imperative_miner/evaluation.py:110-112](../evaluation.py:110)) viele τ findet,
sagt also nur etwas über die *Operator-Tiefe* und *-Breite* des Prozessbaums
aus, nicht über behaviorale Freizügigkeit.

---

## 4. Was `precision_alignments` tatsächlich misst

Der Default-Pfad in
[imperative_miner/evaluation.py:144](../evaluation.py:144) ist:

```python
precision_value = pm4py.conformance.precision_alignments(log, net, im, fm)
```

Das ist die **Alignment-basierte ETC-Precision** nach Adriansyah, Muñoz-Gama,
Carmona et al. (BPM Workshops 2012, *"Alignment based precision checking"*).
Schritte:

1. Für jeden Trace im Log ein optimales Alignment auf das Modell berechnen.
2. Aus den Alignment-Präfixen einen Log-Automaten (Trie) bilden.
3. An jedem Knoten $n$ zwei Mengen bestimmen:
   - $reflected(n)$: Aktivitäten, die im Log nach diesem Präfix beobachtet
     wurden,
   - $available(n)$: Aktivitäten, die das Modell nach diesem Präfix
     ausführen *könnte*.
4. Precision als gewichteter Durchschnitt:

$$
\text{precision} \;=\; \frac{\sum_n w(n) \cdot \frac{|reflected(n)|}{|available(n)|}}{\sum_n w(n)}
$$

**Silent-Closure und visible-enabled.** Bei der Bestimmung von $available(n)$
folgt PM4Py von der aktuellen Markierung aus *alle* erreichbaren τ-Pfade
(silent closure) und sammelt dann die *sichtbaren* Transitionen, die an einem
dieser Folgemarkings feuern können. Die Größe von $available(n)$ ist also die
Anzahl **sichtbarer** Aktivitäten, die im aktuellen Block-Kontext gerade legal
sind — nicht die Anzahl τ-Transitionen, die unterwegs passiert werden.

Das ist der Hebel: **viele τ "passieren" zu können, vergrößert
$|available(n)|$ in einem block-strukturierten Netz nicht**, weil jede
τ-Transition strukturell auf ihren eigenen Block beschränkt ist und am Ende
nur eine kleine Menge sichtbarer Folge-Aktivitäten enthüllt.

In Folge:

- **Flower Model:** $|available(n)| = |\Sigma|$ konstant ⇒ Precision niedrig.
- **IM-Netz mit vielen τ:** $|available(n)|$ entspricht der Verzweigung des
  jeweiligen Subtrees — meist klein und nahe an $|reflected(n)|$ ⇒
  Precision hoch.

Beides ist rechentechnisch **korrekt** und beides ist genau die Aussage, die
ETC-Precision treffen soll.

---

## 5. Wann die Intuition trotzdem zutrifft

Die ursprüngliche "viele τ ⇒ niedrige Precision"-Intuition wird *richtig* in
genau diesen Regimen:

- **Flower Model** (Definition oben).
- **Inductive Miner — Infrequent (IMf)** mit sehr aggressiven
  Filter-Schwellen: Filtert IMf so viele Kanten heraus, dass nur noch
  Choice-Reste übrig bleiben, nähert sich das resultierende Netz strukturell
  einem Flower Model an. Precision *fällt* dann tatsächlich.
- **Sehr kleine / sehr diverse Logs**, in denen $|reflected(n)|$ am
  Wurzelknoten klein im Verhältnis zu $|\Sigma|$ ist.

Der Default-Pfad des `imperative_miner` (`discover_process_tree_inductive`,
ohne aggressive Filterung) befindet sich nicht in diesem Regime, deshalb
greift die Intuition nicht.

---

## 6. Zur Token-Replay-Variante

[imperative_miner/evaluation.py:147](../evaluation.py:147) erlaubt optional
`method="token_replay"`:

```python
precision_value = pm4py.conformance.precision_token_based_replay(log, net, im, fm)
```

Das ist die "escaping-edges"-Precision von Muñoz-Gama & Carmona (2010). Sie
ist auf Loops mit τ-Transitionen **optimistischer** als die alignment-basierte
Variante, weil übersprungene unsichtbare Schritte nicht als escaping edges
gezählt werden. Wer also auf "der τ-Anteil müsste die Precision drücken"
hofft, bekommt mit Token-Replay einen *höheren*, nicht niedrigeren Wert.

Die alignment-basierte Variante ist die rigorosere — und ist genau deshalb
der Default in dieser Thesis.

---

## 7. Abgrenzung: Was *nicht* die Ursache ist

- **PNML-Round-Trip-Artefakte.** Auf der Fusion-Seite müssen
  τ-Transitionen, die nach dem Schreiben/Lesen eines PNML-Files Labels wie
  `"tau split"`, `"tau join"`, `"tau from tree"` tragen, explizit wieder auf
  `label = None` gesetzt werden — siehe
  [fusion_miner/evaluation.py:425-429](../../fusion_miner/evaluation.py:425).
  Auf dem `imperative_miner`-Pfad gibt es **keinen** PNML-Round-Trip; das
  Petri-Netz bleibt als PM4Py-Objekt im Speicher. τ-Transitionen behalten
  korrekt `label is None`, und die silent closure funktioniert ohne weiteren
  Eingriff. Dieses Risiko besteht hier also nicht.
- **Diskrepanz zwischen PM4Py- und ProM-Precision** (siehe
  [fusion_miner/PRECISION.md §7](../../fusion_miner/PRECISION.md)). Das ist
  ein Effekt der unterschiedlichen `available`-Definition zwischen PM4Py
  (silent closure) und ProM (Synchronous-Product-Reachability) und betrifft
  nur den Fusion-Pfad.

---

## 8. Fazit für die Thesis

1. **τ-Anzahl und Precision sind nicht invers korreliert** — sie messen
   unterschiedliche Dinge. Die τ-Anzahl reflektiert die Operator-Struktur
   des Prozessbaums (`×`, `⟲`, `∧`); Precision reflektiert die behaviorale
   Spezifität gegenüber dem Log.
2. Es ist **legitim und erwartbar**, dass IM-Netze mit zweistelliger
   τ-Anzahl hohe Precision-Werte zeigen.
3. Beide Größen sollten im Reporting **unabhängig nebeneinander** stehen:
   - `n_silent_transitions` als strukturelle Komplexitätsgröße,
   - `precision` als behaviorale Konformitätsgröße.
4. Wer eine Modellklasse mit "viele τ + niedrige Precision" demonstrieren
   will, muss entweder ein Flower Model konstruieren oder IMf mit extremen
   Filter-Schwellen konfigurieren — nicht den Default des
   `imperative_miner`.

---

## Quellen

- Leemans, Fahland, van der Aalst (2013): *"Discovering Block-Structured
  Process Models from Event Logs — A Constructive Approach"*. ATPN.
  → Konstruktion und Sound-Workflow-Net-Eigenschaft des IM.
- Adriansyah, Muñoz-Gama, Carmona, van Dongen, van der Aalst (2012):
  *"Alignment based precision checking"*. BPM Workshops, LNBIP 132.
  → Definition und Motivation von ETC-Alignment-Precision.
- Muñoz-Gama, Carmona (2010): *"A fresh look at precision in process
  conformance"*. BPM.
  → Token-Replay-/Escaping-Edges-Variante.
- van der Aalst (2011): *Process Mining: Discovery, Conformance and
  Enhancement*, Kap. 7.
  → Allgemeine Precision-Definition und Trade-off mit Fitness.
- PM4Py-Dokumentation:
  `pm4py.conformance.precision_alignments`,
  `pm4py.conformance.precision_token_based_replay`.
