package thesis.fusion;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;

import org.deckfour.xes.classification.XEventClass;
import org.deckfour.xes.classification.XEventClassifier;
import org.deckfour.xes.info.XLogInfo;
import org.deckfour.xes.info.XLogInfoFactory;
import org.deckfour.xes.info.impl.XLogInfoImpl;
import org.deckfour.xes.model.XLog;
import org.processmining.contexts.uitopia.UIPluginContext;
import org.processmining.fusionminerful.result.FusionMINERfulResult;
import org.processmining.mixedparadigm.algorithms.replayer.MPReplayResult;
import org.processmining.mixedparadigm.algorithms.replayer.PetrinetReplayerWithAutomata;
import org.processmining.mixedparadigm.models.mixedparadigm.DeclarativeArc;
import org.processmining.mixedparadigm.models.mixedparadigm.PetrinetWithAutomata;
import org.processmining.mixedparadigm.parameters.MPReplayParameters;
import org.processmining.models.graphbased.directed.petrinet.PetrinetEdge;
import org.processmining.models.graphbased.directed.petrinet.elements.Place;
import org.processmining.models.graphbased.directed.petrinet.elements.Transition;
import org.processmining.models.semantics.petrinet.Marking;
import org.processmining.plugins.connectionfactories.logpetrinet.TransEvClassMapping;
import org.processmining.plugins.petrinet.replayer.PNLogReplayer;
import org.processmining.plugins.petrinet.replayresult.PNRepResult;
import org.processmining.plugins.replayer.replayresult.SyncReplayResult;

final class MpccService {
    private static final String METHOD =
            "PetrinetReplayerWithAutomata via PNLogReplayer.replayLog(PluginContext, PetrinetGraph, XLog, TransEvClassMapping, IPNReplayAlgorithm, IPNReplayParameter)";
    private static final String METHOD_STRICT = METHOD + " [allow_violations=false]";
    private static final String METHOD_ALLOWING_VIOLATIONS = METHOD + " [allow_violations=true]";
    private static final int DEFAULT_CONSTRAINT_VIOLATION_COST = 2;

    static final class Result {
        final String status;
        final Double fitness;
        final long runtimeMs;
        final String error;
        final String method;
        final String classifier;
        final Integer replayResultSize;
        final Integer mappedTransitionCount;
        final Integer unmappedTransitionCount;
        final List<String> unmappedTransitions;
        final List<String> phantomTransitions;
        final Map<String, Object> replayInfo;
        // Exposed so the headless runner can feed downstream conformance plugins
        // (e.g. AlignmentPrecGen) without recomputing the alignment.
        final TransEvClassMapping mapping;
        final PNRepResult alignment;

        private Result(
                String status,
                Double fitness,
                long runtimeMs,
                String error,
                String method,
                String classifier,
                Integer replayResultSize,
                Integer mappedTransitionCount,
                Integer unmappedTransitionCount,
                List<String> unmappedTransitions,
                List<String> phantomTransitions,
                Map<String, Object> replayInfo,
                TransEvClassMapping mapping,
                PNRepResult alignment) {
            this.status = status;
            this.fitness = fitness;
            this.runtimeMs = runtimeMs;
            this.error = error;
            this.method = method;
            this.classifier = classifier;
            this.replayResultSize = replayResultSize;
            this.mappedTransitionCount = mappedTransitionCount;
            this.unmappedTransitionCount = unmappedTransitionCount;
            this.unmappedTransitions = unmappedTransitions;
            this.phantomTransitions = phantomTransitions;
            this.replayInfo = replayInfo;
            this.mapping = mapping;
            this.alignment = alignment;
        }

        static Result skipped(long runtimeMs, String reason) {
            return new Result("skipped", null, runtimeMs, reason, METHOD, null, null, null, null, new ArrayList<String>(), new ArrayList<String>(), new LinkedHashMap<String, Object>(), null, null);
        }

        static Result failed(long runtimeMs, String error) {
            return new Result("error", null, runtimeMs, error, METHOD, null, null, null, null, new ArrayList<String>(), new ArrayList<String>(), new LinkedHashMap<String, Object>(), null, null);
        }

        Map<String, Object> toJson() {
            Map<String, Object> data = new LinkedHashMap<String, Object>();
            data.put("mpcc_status", status);
            data.put("mpcc_fitness", fitness);
            data.put("mpcc_runtime_ms", Long.valueOf(runtimeMs));
            data.put("mpcc_error", error);
            data.put("mpcc_method", method);
            data.put("mpcc_classifier", classifier);
            data.put("mpcc_replay_result_size", replayResultSize);
            data.put("mpcc_mapped_transition_count", mappedTransitionCount);
            data.put("mpcc_unmapped_transition_count", unmappedTransitionCount);
            data.put("mpcc_unmapped_transitions", unmappedTransitions);
            data.put("mpcc_phantom_transition_count", phantomTransitions == null ? null : Integer.valueOf(phantomTransitions.size()));
            data.put("mpcc_phantom_transitions", phantomTransitions);
            data.put("mpcc_replay_info", replayInfo);
            return data;
        }
    }

    private static final class MappingResult {
        final TransEvClassMapping mapping;
        final int mappedTransitionCount;
        final List<String> unmappedTransitions;
        final List<String> phantomTransitions;
        final Set<Transition> phantomTransitionRefs;

        MappingResult(TransEvClassMapping mapping, int mappedTransitionCount, List<String> unmappedTransitions,
                List<String> phantomTransitions, Set<Transition> phantomTransitionRefs) {
            this.mapping = mapping;
            this.mappedTransitionCount = mappedTransitionCount;
            this.unmappedTransitions = unmappedTransitions;
            this.phantomTransitions = phantomTransitions;
            this.phantomTransitionRefs = phantomTransitionRefs;
        }
    }

    private static final class ReplayAttempt {
        final PNRepResult result;
        final String method;
        final String error;

        private ReplayAttempt(PNRepResult result, String method, String error) {
            this.result = result;
            this.method = method;
            this.error = error;
        }

        static ReplayAttempt success(PNRepResult result, String method) {
            return new ReplayAttempt(result, method, null);
        }

        static ReplayAttempt failed(String method, String error) {
            return new ReplayAttempt(null, method, error);
        }
    }

    Result compute(UIPluginContext context, FusionMINERfulResult fusionResult, XLog xlog) {
        long startedAt = System.currentTimeMillis();
        try {
            PetrinetWithAutomata pnwa = fusionResult.getPetriNetWithAutomata();
            if (pnwa == null) {
                pnwa = fusionResult.createPetriNetWithAutomata();
            }
            if (pnwa == null) {
                return Result.skipped(elapsed(startedAt), "FusionMINERful did not provide a PetrinetWithAutomata model.");
            }
            if (pnwa.getTransitions().isEmpty()) {
                return Result.skipped(elapsed(startedAt), "PetrinetWithAutomata has no transitions.");
            }
            loadLpSolveNativeLibraries();

            XEventClassifier classifier = XLogInfoImpl.NAME_CLASSIFIER;
            XLogInfo logInfo = XLogInfoFactory.createLogInfo(xlog, classifier);
            Collection<XEventClass> eventClasses = logInfo.getEventClasses().getClasses();
            XEventClass dummy = new XEventClass("DUMMY", -1);
            MappingResult mappingResult = buildTransitionMapping(pnwa, logInfo, classifier, dummy);
            int visibleTransitionCount = countVisibleTransitions(pnwa) - mappingResult.phantomTransitions.size();
            if (visibleTransitionCount > 0 && mappingResult.mappedTransitionCount == 0) {
                return new Result(
                        "error",
                        null,
                        elapsed(startedAt),
                        "MPCC aborted because no visible model transition could be mapped to a log event class.",
                        METHOD,
                        classifier.name(),
                        null,
                        Integer.valueOf(mappingResult.mappedTransitionCount),
                        Integer.valueOf(mappingResult.unmappedTransitions.size()),
                        mappingResult.unmappedTransitions,
                        mappingResult.phantomTransitions,
                        new LinkedHashMap<String, Object>(),
                        mappingResult.mapping,
                        null);
            }

            Marking initialMarking = fusionResult.getInitialMarking();
            Marking finalMarking = fusionResult.getFinalMarking();
            ReplayAttempt replayAttempt = attemptReplay(
                    context,
                    pnwa,
                    xlog,
                    mappingResult.mapping,
                    eventClasses,
                    dummy,
                    initialMarking,
                    finalMarking,
                    mappingResult.phantomTransitionRefs,
                    false);
            ReplayAttempt replayAttemptAllowingViolations = null;
            if (replayAttempt.result == null) {
                replayAttemptAllowingViolations = attemptReplay(
                        context,
                        pnwa,
                        xlog,
                        mappingResult.mapping,
                        eventClasses,
                        dummy,
                        initialMarking,
                        finalMarking,
                        mappingResult.phantomTransitionRefs,
                        true);
                if (replayAttemptAllowingViolations.result != null) {
                    replayAttempt = replayAttemptAllowingViolations;
                }
            }
            if (replayAttempt.result == null) {
                StringBuilder error = new StringBuilder("MixedParadigm replay returned no PNRepResult.");
                if (replayAttempt.error != null) {
                    error.append(" First attempt: ").append(replayAttempt.error);
                }
                if (replayAttemptAllowingViolations != null && replayAttemptAllowingViolations.error != null) {
                    error.append(" Fallback attempt: ").append(replayAttemptAllowingViolations.error);
                }
                return Result.failed(elapsed(startedAt), error.toString());
            }
            PNRepResult pnReplayResult = replayAttempt.result;

            MPReplayResult mpReplayResult = new MPReplayResult(pnReplayResult);
            Map<String, Object> replayInfo = serializableInfo(mpReplayResult.getInfo());
            Double rawFitness = extractFitness(pnReplayResult);
            Double fitness = rawFitness;
            String status = "success";
            String error = null;
            if (rawFitness == null) {
                status = "error";
                error = "MixedParadigm replay completed but did not report Trace Fitness.";
            } else if (!isFitnessInUnitInterval(rawFitness.doubleValue())) {
                status = "error";
                fitness = null;
                error = String.format(
                        "MixedParadigm replay returned out-of-range Trace Fitness %.12f (expected between 0 and 1).",
                        rawFitness.doubleValue());
            }
            return new Result(
                    status,
                    fitness,
                    elapsed(startedAt),
                    error,
                    replayAttempt.method,
                    classifier.name(),
                    Integer.valueOf(mpReplayResult.size()),
                    Integer.valueOf(mappingResult.mappedTransitionCount),
                    Integer.valueOf(mappingResult.unmappedTransitions.size()),
                    mappingResult.unmappedTransitions,
                    mappingResult.phantomTransitions,
                    replayInfo,
                    mappingResult.mapping,
                    pnReplayResult);
        } catch (Throwable throwable) {
            return Result.failed(elapsed(startedAt), throwable.getClass().getSimpleName() + ": " + throwable.getMessage());
        }
    }

    private static ReplayAttempt attemptReplay(
            UIPluginContext context,
            PetrinetWithAutomata pnwa,
            XLog xlog,
            TransEvClassMapping mapping,
            Collection<XEventClass> eventClasses,
            XEventClass dummy,
            Marking initialMarking,
            Marking finalMarking,
            Set<Transition> phantomTransitions,
            boolean allowViolatingConstraints) {
        String method = allowViolatingConstraints ? METHOD_ALLOWING_VIOLATIONS : METHOD_STRICT;
        try {
            MPReplayParameters parameters = new MPReplayParameters(eventClasses, dummy, pnwa.getTransitions());
            if (initialMarking != null) {
                parameters.setInitialMarking(initialMarking);
            }
            if (finalMarking != null) {
                parameters.setFinalMarkings(finalMarking);
            }
            // Phantom transitions (vendor-injected, no Place arcs) are not part
            // of the discovered model behaviour, so their model-only firings
            // should not count as deviations. Zero their move-model cost so
            // the alignment can satisfy any declarative automata that
            // reference these activities for free, without inflating the
            // fitness denominator beyond the genuine procedural skeleton.
            if (phantomTransitions != null && !phantomTransitions.isEmpty()) {
                Map<Transition, Integer> moveModelCosts = parameters.getMapTrans2Cost();
                if (moveModelCosts != null) {
                    for (Transition phantom : phantomTransitions) {
                        moveModelCosts.put(phantom, Integer.valueOf(0));
                    }
                }
            }
            parameters.setContraintCosts(buildConstraintCosts(pnwa.getConstraints()));
            parameters.setAllowViolatingConstraints(allowViolatingConstraints);
            parameters.setGUIMode(false);
            parameters.setCreateConn(false);
            parameters.setNumThreads(1);

            PetrinetReplayerWithAutomata algorithm = new PetrinetReplayerWithAutomata();
            PNRepResult replayResult = new PNLogReplayer().replayLog(
                    context,
                    pnwa,
                    xlog,
                    mapping,
                    algorithm,
                    parameters);
            if (replayResult == null) {
                return ReplayAttempt.failed(method, "MixedParadigm replay returned no PNRepResult.");
            }
            return ReplayAttempt.success(replayResult, method);
        } catch (Throwable throwable) {
            return ReplayAttempt.failed(method, throwable.getClass().getSimpleName() + ": " + throwable.getMessage());
        }
    }

    private static long elapsed(long startedAt) {
        return System.currentTimeMillis() - startedAt;
    }

    private static void loadLpSolveNativeLibraries() {
        String nativeDir = System.getProperty("thesis.fusion.lpsolve.native.dir", "");
        if (nativeDir == null || nativeDir.trim().isEmpty()) {
            return;
        }
        if (System.getProperty("os.name", "").toLowerCase().contains("mac")) {
            loadNativeIfPresent(nativeDir + "/liblpsolve55j.jnilib");
        }
    }

    private static void loadNativeIfPresent(String path) {
        java.io.File file = new java.io.File(path);
        if (file.exists()) {
            try {
                System.load(file.getAbsolutePath());
            } catch (UnsatisfiedLinkError error) {
                UnsatisfiedLinkError enriched = new UnsatisfiedLinkError(
                        "Unable to load native LpSolve library " + file.getAbsolutePath()
                                + " with JVM architecture " + System.getProperty("os.arch")
                                + ": " + error.getMessage());
                enriched.initCause(error);
                throw enriched;
            }
        }
    }

    private static MappingResult buildTransitionMapping(
            PetrinetWithAutomata pnwa,
            XLogInfo logInfo,
            XEventClassifier classifier,
            XEventClass dummy) {
        TransEvClassMapping mapping = new TransEvClassMapping(classifier, dummy);
        List<String> unmapped = new ArrayList<String>();
        List<String> phantoms = new ArrayList<String>();
        Set<Transition> phantomRefs = new HashSet<Transition>();
        int mapped = 0;
        for (Transition transition : pnwa.getTransitions()) {
            // FusionMINERful's createPetriNetWithAutomata() appends a transition
            // for every log-alphabet activity that is not already in the
            // procedural Petri net, without any input or output arcs. Those
            // "phantom" transitions are always enabled and — at the default
            // sync cost of 0 — would silently absorb any log event as a free
            // sync move, inflating Trace Fitness to 1.0 regardless of how
            // poorly the procedural skeleton actually fits the log. Map them
            // to the dummy event class so they cannot serve as free sync
            // proxies; the alignment will then correctly account for those
            // events as log moves (deviations).
            boolean disconnected = !transition.isInvisible() && !hasPlaceArc(pnwa, transition);
            XEventClass eventClass;
            if (transition.isInvisible() || disconnected) {
                eventClass = dummy;
                if (disconnected) {
                    phantoms.add(transition.getLabel());
                    phantomRefs.add(transition);
                }
            } else {
                eventClass = findEventClass(logInfo, transition.getLabel());
                if (eventClass == null) {
                    eventClass = dummy;
                    unmapped.add(transition.getLabel());
                } else {
                    mapped++;
                }
            }
            mapping.put(transition, eventClass);
        }
        return new MappingResult(mapping, mapped, unmapped, phantoms, phantomRefs);
    }

    private static XEventClass findEventClass(XLogInfo logInfo, String transitionLabel) {
        if (transitionLabel == null) {
            return null;
        }
        for (String candidate : labelCandidates(transitionLabel)) {
            XEventClass eventClass = logInfo.getEventClasses().getByIdentity(candidate);
            if (eventClass != null) {
                return eventClass;
            }
        }
        return null;
    }

    private static List<String> labelCandidates(String rawLabel) {
        Set<String> values = new LinkedHashSet<String>();
        values.add(rawLabel);

        String trimmed = rawLabel.trim();
        values.add(trimmed);

        int newline = trimmed.indexOf('\n');
        if (newline > 0) {
            values.add(trimmed.substring(0, newline).trim());
        }

        // Fusion/MP labels can carry lifecycle markers like "a+" or "a-".
        if (trimmed.endsWith("+") || trimmed.endsWith("-")) {
            values.add(trimmed.substring(0, trimmed.length() - 1).trim());
        }

        int plusIndex = trimmed.indexOf('+');
        if (plusIndex > 0) {
            values.add(trimmed.substring(0, plusIndex).trim());
        }

        int minusIndex = trimmed.indexOf('-');
        if (minusIndex > 0) {
            values.add(trimmed.substring(0, minusIndex).trim());
        }

        List<String> cleaned = new ArrayList<String>();
        for (String candidate : values) {
            if (candidate != null && !candidate.isEmpty()) {
                cleaned.add(candidate);
            }
        }
        return cleaned;
    }

    private static boolean hasPlaceArc(PetrinetWithAutomata pnwa, Transition transition) {
        // A transition that participates in the Petri-net flow has at least one
        // edge connecting it to a Place. DeclarativeArc instances connect two
        // Transitions and live in the same edge collection, so we filter on
        // the endpoint type. Phantom transitions (added by FusionMINERful for
        // alphabet activities absent from the procedural net) have no Place
        // arcs at all.
        for (Object edge : pnwa.getInEdges(transition)) {
            if (edge instanceof PetrinetEdge<?, ?>
                    && ((PetrinetEdge<?, ?>) edge).getSource() instanceof Place) {
                return true;
            }
        }
        for (Object edge : pnwa.getOutEdges(transition)) {
            if (edge instanceof PetrinetEdge<?, ?>
                    && ((PetrinetEdge<?, ?>) edge).getTarget() instanceof Place) {
                return true;
            }
        }
        return false;
    }

    private static Map<DeclarativeArc, Integer> buildConstraintCosts(Collection<DeclarativeArc> constraints) {
        Map<DeclarativeArc, Integer> costs = new LinkedHashMap<DeclarativeArc, Integer>();
        for (DeclarativeArc constraint : constraints) {
            costs.put(constraint, Integer.valueOf(DEFAULT_CONSTRAINT_VIOLATION_COST));
        }
        return costs;
    }

    private static int countVisibleTransitions(PetrinetWithAutomata pnwa) {
        int visible = 0;
        for (Transition transition : pnwa.getTransitions()) {
            if (!transition.isInvisible()) {
                visible++;
            }
        }
        return visible;
    }

    private static boolean isFitnessInUnitInterval(double value) {
        double epsilon = 1e-9;
        return value >= -epsilon && value <= 1.0 + epsilon;
    }

    private static Double extractFitness(PNRepResult replayResult) {
        Double fitness = asDouble(replayResult.getInfo().get(PNRepResult.TRACEFITNESS));
        if (fitness != null) {
            return fitness;
        }

        double weightedFitness = 0.0;
        int weight = 0;
        for (SyncReplayResult traceResult : replayResult) {
            Double traceFitness = asDouble(traceResult.getInfo().get(PNRepResult.TRACEFITNESS));
            if (traceFitness == null) {
                continue;
            }
            int traceWeight = Math.max(1, traceResult.getTraceIndex().size());
            weightedFitness += traceFitness.doubleValue() * traceWeight;
            weight += traceWeight;
        }
        if (weight == 0) {
            return null;
        }
        return Double.valueOf(weightedFitness / weight);
    }

    private static Double asDouble(Object value) {
        if (value instanceof Number) {
            return Double.valueOf(((Number) value).doubleValue());
        }
        if (value instanceof String) {
            try {
                return Double.valueOf(Double.parseDouble((String) value));
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static Map<String, Object> serializableInfo(Map<String, Object> info) {
        Map<String, Object> data = new LinkedHashMap<String, Object>();
        if (info == null) {
            return data;
        }
        for (Map.Entry<String, Object> entry : info.entrySet()) {
            Object value = entry.getValue();
            if (value == null || value instanceof Number || value instanceof Boolean || value instanceof String) {
                data.put(entry.getKey(), value);
            } else {
                data.put(entry.getKey(), value.toString());
            }
        }
        return data;
    }
}
