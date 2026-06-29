# Hybrid Trace Sampler — Spike-Ergebnis (Phase 0)

**Ergebnis: Fall A** — MixedParadigm liefert eine produktionsreife Constraint-Progression-API. Der `HybridTraceSampler` ist ein dünner Adapter, kein template-spezifischer DFA-Nachbau.

## API-Oberfläche (alles vorhanden)

- `pnwa.getConstraints() → Collection<DeclarativeArc>`
- `DeclarativeArc.getType() → ConstraintType` (`Binary`, `Unary`, `Branched`)
- `ConstraintType.getAutomaton(TObjectShortMap<Transition,Short>, ...) → DeterministicFiniteAutomaton`
- Auf dem DFA:
  - `getInitialState() → short`
  - `isAllowed(state, activityId) → boolean`
  - `getNextState(state, activityId) → short`
  - `isAcceptingState(state) → boolean`

## Folgen für die Umsetzung

- `HybridStates` hält pro `DeclarativeArc` genau einen `short`-Zustand (Array-Parallelprojektion wie `PAutomataHead`).
- Schritt-Progression in `afterStep`: für jeden Constraint `states[i] = dfa[i].getNextState(states[i], activityId)`.
- Erlaubtheit in `allowsStep`: Alle `dfa[i].isAllowed(states[i], activityId)` müssen gelten.
- Akzeptanz in `allAccepting`: alle `dfa[i].isAcceptingState(states[i])`.
- **Silent transitions**: kein `afterStep`-Aufruf, kein Progression-Update — Declare reagiert nur auf sichtbare Aktivitäten (plan-konform).

## Referenzen in ProM

- `org.processmining.mixedparadigm.models.mixedparadigm.PetrinetWithAutomata`
- `org.processmining.mixedparadigm.models.mixedparadigm.DeclarativeArc`
- `org.processmining.mixedparadigm.models.mixedparadigm.ConstraintType`
- `org.processmining.mixedparadigm.models.dfa.DeterministicFiniteAutomaton`
- `org.processmining.mixedparadigm.algorithms.replayer.PILPDelegateAutomata` (State-Vektor-Vorbild)

## Templates (real von FusionMINERful erzeugt)

Alle unterstützt — kein Eigenbau nötig:

- **Binary (14):** Response, Precedence, Succession, CoExistence, RespondedExistence, ChainSuccession, ChainResponse, ChainPrecedence, AlternateResponse, AlternatePrecedence, AlternateSuccession, NotSuccession, NotCoExistence, NotChainSuccession
- **Branched (5):** BranchedResponse, BranchedPrecedence, BranchedRespondedExistence, BranchedAlternatePrecedence, Choice/ExclusiveChoice
- **Unary (4):** Init, ExistenceN, AbsenceN, ExactlyN
