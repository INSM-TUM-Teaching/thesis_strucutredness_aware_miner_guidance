package thesis.fusion;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

import org.processmining.fusionminerful.result.FusionMINERfulResult;
import org.processmining.mixedparadigm.models.mixedparadigm.PetrinetWithAutomata;
import org.processmining.models.graphbased.directed.petrinet.elements.Transition;
import org.processmining.models.semantics.petrinet.EfficientPetrinetSemantics;
import org.processmining.models.semantics.petrinet.Marking;
import org.processmining.models.semantics.petrinet.impl.EfficientPetrinetSemanticsImpl;

import thesis.fusion.HybridStates.HybridState;

/**
 * Uniform random hybrid-trace sampler: walks the PetrinetWithAutomata while
 * respecting the combined Declare automata state. Produces a fixed number of
 * <i>valid</i> traces (capped by a hard attempt ceiling) for downstream
 * Markovian precision estimation.
 *
 * <p>Silent transitions advance the Petri-net marking only; the Declare state
 * is not updated (Declare semantics operate on visible activities).
 *
 * <p>A sample is <b>valid</b> when (a) no legal step remains and the marking is
 * accepting and every Declare automaton is accepting, or (b) the trace hits
 * {@code maxTraceLength} while already in an accepting state
 * (counted separately as {@code nTruncatedAtFinal}).
 */
final class HybridTraceSampler {

    static final class Params {
        int nValidSamples = 5000;
        int maxAttempts = 20 * 5000;
        int maxTraceLength = 200;
        long seed = 42L;
    }

    static final class Stats {
        int nRequestedValid;
        int nValid;
        int nAttempts;
        int nRejectedDeadlock;
        int nRejectedTooLong;
        int nTruncatedAtFinal;
        long runtimeMs;
    }

    List<List<String>> sample(FusionMINERfulResult fusion, Params p, Stats out) {
        PetrinetWithAutomata pnwa = fusion.getPetriNetWithAutomata();
        if (pnwa == null) {
            pnwa = fusion.createPetriNetWithAutomata();
        }
        Marking initialMarking = fusion.getInitialMarking();
        Marking finalMarking = fusion.getFinalMarking();
        if (initialMarking == null) {
            initialMarking = new Marking();
        }

        long t0 = System.currentTimeMillis();
        out.nRequestedValid = p.nValidSamples;

        if (pnwa == null || pnwa.getTransitions().isEmpty()) {
            out.runtimeMs = System.currentTimeMillis() - t0;
            return new ArrayList<List<String>>();
        }

        EfficientPetrinetSemantics semantics = new EfficientPetrinetSemanticsImpl(pnwa, initialMarking);
        HybridState initialHybridState = HybridStates.initialFor(pnwa);

        Random rng = new Random(p.seed);
        List<List<String>> accepted = new ArrayList<List<String>>(p.nValidSamples);

        while (accepted.size() < p.nValidSamples && out.nAttempts < p.maxAttempts) {
            out.nAttempts++;
            semantics.setStateAsMarking(initialMarking);
            HybridState hs = initialHybridState;
            List<String> trace = new ArrayList<String>();

            while (true) {
                Collection<Transition> enabled = semantics.getExecutableTransitions();
                List<Transition> legal = filterLegal(enabled, hs);
                boolean atAccepting = isAcceptingMarking(semantics.getStateAsMarking(), finalMarking)
                        && hs.allAccepting();

                if (legal.isEmpty()) {
                    if (atAccepting) {
                        accepted.add(trace);
                        out.nValid++;
                    } else {
                        out.nRejectedDeadlock++;
                    }
                    break;
                }
                if (trace.size() >= p.maxTraceLength) {
                    if (atAccepting) {
                        accepted.add(trace);
                        out.nValid++;
                        out.nTruncatedAtFinal++;
                    } else {
                        out.nRejectedTooLong++;
                    }
                    break;
                }

                Transition chosen = legal.get(rng.nextInt(legal.size()));
                try {
                    semantics.executeExecutableTransition(chosen);
                } catch (Exception e) {
                    out.nRejectedDeadlock++;
                    break;
                }
                if (!chosen.isInvisible()) {
                    trace.add(stripLifecycleMarker(chosen.getLabel()));
                    hs = hs.afterStep(chosen);
                }
            }
        }

        out.runtimeMs = System.currentTimeMillis() - t0;
        return accepted;
    }

    private static List<Transition> filterLegal(Collection<Transition> enabled, HybridState hs) {
        List<Transition> legal = new ArrayList<Transition>(enabled.size());
        for (Transition t : enabled) {
            if (hs.allowsStep(t)) {
                legal.add(t);
            }
        }
        return legal;
    }

    /**
     * FusionMINERful exposes a single final marking (not a set). Accepting iff
     * current marking equals that final marking. When no final marking is
     * declared, fall back to "no enabled step" as the acceptance condition — in
     * that case a deadlock counts as acceptance only if the caller treated it
     * as such, which we achieve by returning true so the empty-legal branch
     * above becomes the successful stop.
     */
    private static boolean isAcceptingMarking(Marking current, Marking finalMarking) {
        if (finalMarking == null || finalMarking.isEmpty()) {
            return true;
        }
        return finalMarking.equals(current);
    }

    static void writeCsv(Path out, List<List<String>> traces) throws IOException {
        Files.createDirectories(out.getParent());
        try (BufferedWriter w = Files.newBufferedWriter(out, StandardCharsets.UTF_8)) {
            w.write("trace_id,step,activity\n");
            for (int i = 0; i < traces.size(); i++) {
                List<String> tr = traces.get(i);
                for (int s = 0; s < tr.size(); s++) {
                    w.write(Integer.toString(i));
                    w.write(',');
                    w.write(Integer.toString(s));
                    w.write(',');
                    w.write(csvEscape(tr.get(s)));
                    w.write('\n');
                }
            }
        }
    }

    static Map<String, Object> statsToJson(Stats s, Params p) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("n_requested_valid", Integer.valueOf(s.nRequestedValid));
        m.put("n_valid", Integer.valueOf(s.nValid));
        m.put("n_attempts", Integer.valueOf(s.nAttempts));
        m.put("n_rejected_deadlock", Integer.valueOf(s.nRejectedDeadlock));
        m.put("n_rejected_too_long", Integer.valueOf(s.nRejectedTooLong));
        m.put("n_truncated_at_final", Integer.valueOf(s.nTruncatedAtFinal));
        m.put("runtime_ms", Long.valueOf(s.runtimeMs));
        m.put("seed", Long.valueOf(p.seed));
        m.put("max_trace_length_used", Integer.valueOf(p.maxTraceLength));
        m.put("max_attempts", Integer.valueOf(p.maxAttempts));
        return m;
    }

    static Map<String, Object> statsToManifest(Stats s, Params p) {
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        m.put("hybrid_sampling_n_valid", Integer.valueOf(s.nValid));
        m.put("hybrid_sampling_n_attempts", Integer.valueOf(s.nAttempts));
        m.put("hybrid_sampling_n_rejected_deadlock", Integer.valueOf(s.nRejectedDeadlock));
        m.put("hybrid_sampling_n_rejected_too_long", Integer.valueOf(s.nRejectedTooLong));
        m.put("hybrid_sampling_n_truncated_at_final", Integer.valueOf(s.nTruncatedAtFinal));
        m.put("hybrid_sampling_runtime_ms", Long.valueOf(s.runtimeMs));
        m.put("hybrid_sampling_seed", Long.valueOf(p.seed));
        m.put("hybrid_sampling_max_trace_length", Integer.valueOf(p.maxTraceLength));
        return m;
    }

    /**
     * FusionMINERful transition labels carry lifecycle markers ("a+" for start,
     * "a-" for complete). Normalise to the bare event-class name so k-grams
     * match what pm4py produces from the XES log.
     */
    private static String stripLifecycleMarker(String label) {
        if (label == null || label.isEmpty()) {
            return label;
        }
        String trimmed = label.trim();
        int newline = trimmed.indexOf('\n');
        if (newline > 0) {
            trimmed = trimmed.substring(0, newline).trim();
        }
        if (trimmed.endsWith("+") || trimmed.endsWith("-")) {
            return trimmed.substring(0, trimmed.length() - 1).trim();
        }
        return trimmed;
    }

    private static String csvEscape(String value) {
        if (value == null) {
            return "";
        }
        boolean needsQuoting = value.indexOf(',') >= 0
                || value.indexOf('"') >= 0
                || value.indexOf('\n') >= 0
                || value.indexOf('\r') >= 0;
        if (!needsQuoting) {
            return value;
        }
        return "\"" + value.replace("\"", "\"\"") + "\"";
    }
}
