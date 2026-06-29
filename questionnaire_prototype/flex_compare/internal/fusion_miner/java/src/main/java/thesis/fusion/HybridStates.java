package thesis.fusion;

import gnu.trove.map.TObjectShortMap;
import gnu.trove.map.hash.TObjectShortHashMap;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;

import org.processmining.mixedparadigm.models.dfa.DeterministicFiniteAutomaton;
import org.processmining.mixedparadigm.models.mixedparadigm.DeclarativeArc;
import org.processmining.mixedparadigm.models.mixedparadigm.PetrinetWithAutomata;
import org.processmining.mixedparadigm.models.mixedparadigm.constraints.ConstraintType;
import org.processmining.models.graphbased.directed.petrinet.elements.Transition;

/**
 * Adapter around the MixedParadigm constraint-automata API. One DFA per
 * DeclarativeArc; combined state is a parallel short[] vector (same layout as
 * PAutomataHead / PILPDelegateAutomata). Strict mode: each DFA is reduced after
 * construction, so any step into a permanently violated state is simply not
 * allowed.
 */
final class HybridStates {

    /** Shared builder: returns an initial HybridState for the given PNWA. */
    static HybridState initialFor(PetrinetWithAutomata pnwa) {
        TObjectShortMap<Transition> trans2int = new TObjectShortHashMap<Transition>();
        short next = 0;
        for (Transition t : pnwa.getTransitions()) {
            trans2int.put(t, next++);
        }

        List<DeterministicFiniteAutomaton> automata = new ArrayList<DeterministicFiniteAutomaton>();
        for (DeclarativeArc constraint : pnwa.getConstraints()) {
            ConstraintType type = constraint.getType();
            DeterministicFiniteAutomaton dfa;
            if (type instanceof ConstraintType.Unary) {
                dfa = ((ConstraintType.Unary) type).getAutomaton(trans2int, constraint.getSource());
            } else if (type instanceof ConstraintType.Binary) {
                dfa = ((ConstraintType.Binary) type).getAutomaton(
                        trans2int, constraint.getSource(), constraint.getTarget());
            } else if (type instanceof ConstraintType.Branched) {
                Collection<Transition> sources = new ArrayList<Transition>(constraint.getSources());
                Collection<Transition> targets = new ArrayList<Transition>(constraint.getTargets());
                dfa = ((ConstraintType.Branched) type).getAutomaton(trans2int, sources, targets);
            } else {
                throw new IllegalStateException(
                        "Unsupported constraint type: " + (type == null ? "null" : type.getClass().getName()));
            }
            // Strict: drop permanently-violated states and their incoming transitions.
            dfa.reduce();
            automata.add(dfa);
        }

        short[] initialStates = new short[automata.size()];
        for (int i = 0; i < automata.size(); i++) {
            initialStates[i] = automata.get(i).getInitialState();
        }
        return new HybridState(trans2int, automata, initialStates);
    }

    private HybridStates() {
    }

    /** Immutable snapshot of the combined declarative state. */
    static final class HybridState {
        private final TObjectShortMap<Transition> trans2int;
        private final List<DeterministicFiniteAutomaton> automata;
        private final short[] states;

        private HybridState(
                TObjectShortMap<Transition> trans2int,
                List<DeterministicFiniteAutomaton> automata,
                short[] states) {
            this.trans2int = trans2int;
            this.automata = automata;
            this.states = states;
        }

        /**
         * Returns true iff firing the given transition is compatible with every
         * declarative constraint. Invisible/silent transitions are always
         * allowed — declarative semantics operate on visible activities.
         */
        boolean allowsStep(Transition t) {
            if (t.isInvisible()) {
                return true;
            }
            short id = transitionId(t);
            if (id < 0) {
                // Transition unknown to any constraint (safe default: allowed).
                return true;
            }
            for (int i = 0; i < automata.size(); i++) {
                if (!automata.get(i).isAllowed(states[i], id)) {
                    return false;
                }
            }
            return true;
        }

        /**
         * Returns the successor HybridState after firing the given visible
         * transition. For silent transitions, the declarative state must not
         * change — callers must therefore skip this method for invisible
         * transitions.
         */
        HybridState afterStep(Transition t) {
            if (t.isInvisible()) {
                return this;
            }
            short id = transitionId(t);
            if (id < 0) {
                return this;
            }
            short[] next = new short[states.length];
            for (int i = 0; i < automata.size(); i++) {
                next[i] = automata.get(i).getNextState(states[i], id);
            }
            return new HybridState(trans2int, automata, next);
        }

        /** True iff every declarative constraint is currently in an accepting state. */
        boolean allAccepting() {
            for (int i = 0; i < automata.size(); i++) {
                if (!automata.get(i).isAcceptingState(states[i])) {
                    return false;
                }
            }
            return true;
        }

        int constraintCount() {
            return automata.size();
        }

        @Override
        public String toString() {
            return "HybridState" + Arrays.toString(states);
        }

        private short transitionId(Transition t) {
            if (!trans2int.containsKey(t)) {
                return -1;
            }
            return trans2int.get(t);
        }
    }
}
