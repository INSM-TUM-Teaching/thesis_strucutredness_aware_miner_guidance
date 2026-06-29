package thesis.fusion;

import java.io.BufferedWriter;
import java.io.File;
import java.io.IOException;
import java.lang.reflect.Method;
import java.awt.Component;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.awt.geom.Point2D;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;

import org.deckfour.xes.in.XMxmlParser;
import org.deckfour.xes.in.XParser;
import org.deckfour.xes.in.XesXmlParser;
import org.deckfour.xes.model.XLog;
import org.processmining.contexts.uitopia.UIContext;
import org.processmining.contexts.uitopia.UIPluginContext;
import org.processmining.fusionminerful.log.EventLog;
import org.processmining.fusionminerful.miner.FusionMINERful;
import org.processmining.fusionminerful.parameters.FusionMinerSettings;
import org.processmining.fusionminerful.plugins.AlignmentPrecGen;
import org.processmining.fusionminerful.plugins.AlignmentPrecGenRes;
import org.processmining.fusionminerful.result.FusionMINERfulResult;
import org.processmining.fusionminerful.visualization.FusionMINERfulProMVisualization;
import org.processmining.fusionminerful.visualization.FusionMINERfulVisualization;
import org.processmining.framework.connections.Connection;
import org.processmining.framework.connections.ConnectionID;
import org.processmining.framework.connections.ConnectionManager;
import org.processmining.framework.plugin.PluginDescriptor;
import org.processmining.framework.plugin.PluginExecutionResult;
import org.processmining.framework.plugin.ProMFuture;
import org.processmining.framework.providedobjects.ProvidedObjectID;
import org.processmining.models.connections.GraphLayoutConnection;
import org.processmining.models.connections.petrinets.behavioral.FinalMarkingConnection;
import org.processmining.models.connections.petrinets.behavioral.InitialMarkingConnection;
import org.processmining.mixedparadigm.models.mixedparadigm.DeclarativeArc;
import org.processmining.mixedparadigm.models.mixedparadigm.PetrinetWithAutomata;
import org.processmining.mixedparadigm.plugins.MPVisualizer;
import org.processmining.mixedparadigm.plugins.PnmlExportMPModel;
import org.processmining.plugins.graphviz.dot.Dot2Image;
import org.processmining.models.flexiblemodel.Flex;
import org.processmining.models.flexiblemodel.FlexEdge;
import org.processmining.models.flexiblemodel.FlexNode;
import org.processmining.models.graphbased.AttributeMap;
import org.processmining.models.graphbased.AttributeMap.ArrowType;
import org.processmining.models.graphbased.NodeID;
import org.processmining.models.graphbased.ViewSpecificAttributeMap;
import org.processmining.models.graphbased.directed.DirectedGraph;
import org.processmining.models.graphbased.directed.DirectedGraphEdge;
import org.processmining.models.graphbased.directed.DirectedGraphNode;
import org.processmining.models.graphbased.directed.petrinet.Petrinet;
import org.processmining.models.graphbased.directed.petrinet.PetrinetEdge;
import org.processmining.models.graphbased.directed.petrinet.PetrinetNode;
import org.processmining.models.graphbased.directed.petrinet.elements.Place;
import org.processmining.models.graphbased.directed.petrinet.elements.Transition;
import org.processmining.models.jgraph.ProMJGraphVisualizer;
import org.processmining.models.jgraph.ProMJGraph;
import org.processmining.models.jgraph.visualization.ProMJGraphPanel;
import org.processmining.models.semantics.petrinet.Marking;
import org.processmining.plugins.causalnet.miner.settings.FlexibleHeuristicsMinerSettings;
import org.processmining.plugins.pnml.exporting.PnmlExportNetToPNML;
import org.freehep.graphicsbase.util.export.ExportFileType;

import javax.imageio.ImageIO;
import javax.swing.JComponent;
import javax.swing.SwingUtilities;

import minerful.concept.ProcessModel;
import minerful.concept.TaskChar;
import minerful.concept.TaskCharSet;
import minerful.concept.constraint.Constraint;
import minerful.concept.constraint.ConstraintFamily;
import minerful.concept.constraint.existence.AtMostOne;
import minerful.concept.constraint.existence.End;
import minerful.concept.constraint.existence.Init;
import minerful.concept.constraint.existence.Participation;

import org.processmining.models.shapes.Rectangle;

public class HeadlessFusionMinerFulRunner {
    private static final class LabelOnlyFuture extends ProMFuture<Object> {
        LabelOnlyFuture(String label) {
            super(Object.class, label);
        }

        @Override
        protected Object doInBackground() throws Exception {
            return null;
        }
    }

    private static final class HeadlessExecutionResult implements PluginExecutionResult {
        private final Object[] results;
        private final String[] names;
        private final ProvidedObjectID[] providedObjectIds;

        HeadlessExecutionResult(int slotCount) {
            this.results = new Object[slotCount];
            this.names = new String[slotCount];
            this.providedObjectIds = new ProvidedObjectID[slotCount];
            for (int i = 0; i < slotCount; i++) {
                this.names[i] = "headless-result-" + i;
                this.results[i] = new LabelOnlyFuture(this.names[i]);
            }
        }

        @Override
        public int getSize() {
            return results.length;
        }

        @Override
        public void synchronize() throws CancellationException, ExecutionException, InterruptedException {
            // Futures are placeholders for headless plugin internals, so there is nothing to await.
        }

        @Override
        public Object[] getResults() {
            return results;
        }

        @SuppressWarnings("unchecked")
        @Override
        public <T> T getResult(int index) throws ClassCastException {
            return (T) results[index];
        }

        @Override
        public String[] getResultNames() {
            return names;
        }

        @Override
        public String getResultName(int index) {
            return names[index];
        }

        @Override
        public void setProvidedObjectID(int index, ProvidedObjectID id) {
            providedObjectIds[index] = id;
        }

        @Override
        public ProvidedObjectID getProvidedObjectID(int index) {
            return providedObjectIds[index];
        }

        @Override
        public <T> Class<? super T> getType(int index) {
            return Object.class;
        }

        @Override
        public PluginDescriptor getPlugin() {
            return null;
        }
    }

    private static final class RenderResult {
        final boolean created;
        final String error;

        private RenderResult(boolean created, String error) {
            this.created = created;
            this.error = error;
        }

        static RenderResult ok() {
            return new RenderResult(true, null);
        }

        static RenderResult fail(String message) {
            return new RenderResult(false, message);
        }
    }

    private static final class Args {
        String logPath;
        String outputDir;
        double relativeToBestThreshold = 0.05;
        int positiveObservationThreshold = 1;
        double dependencyThreshold = 0.9;
        double l1lThreshold = 0.9;
        double l2lThreshold = 0.9;
        double longDistanceThreshold = 0.9;
        int dependencyDivisor = 1;
        boolean useAllConnectedHeuristics = true;
        boolean useLongDistanceDependency = false;
        boolean useUniqueStartEndTasks = false;
        double declareSupport = 1.0;
        double declareAlpha = 1.0;
        double activityEntropy = 0.4;
        double resilience = 0.1;
        double imFitness = 0.2;
        int sizeMultiplicator = 1;
        boolean cut = true;
        boolean prune = true;
        boolean negative = true;
        boolean checkModel = false;
        int precisionValidSamples = 5000;
        int precisionMaxAttempts = -1; // sentinel → 20 * nValidSamples
        int precisionMaxTraceLength = 200;
        long precisionSeed = 42L;
    }

    public static void main(String[] argv) throws Exception {
        // Prevent macOS Dock icon / menu bar from appearing for this batch rendering run.
        // Works even when java.awt.headless=false (which we need for ProMJGraphVisualizer
        // + Slickerbox's GraphicsUtilities to initialize).
        System.setProperty("apple.awt.UIElement", "true");
        long startedAt = System.currentTimeMillis();
        Args args = parseArgs(argv);
        Path outputDir = Paths.get(args.outputDir);
        Path rawDir = outputDir.resolve("assets").resolve("raw");
        Path normalizedDir = outputDir.resolve("assets").resolve("normalized");
        Path renderedDir = outputDir.resolve("assets").resolve("rendered");
        Files.createDirectories(rawDir);
        Files.createDirectories(normalizedDir);
        Files.createDirectories(renderedDir);

        Map<String, Object> manifest = new LinkedHashMap<String, Object>();
        manifest.put("started_at", Instant.ofEpochMilli(startedAt).toString());
        manifest.put("status", "error");
        manifest.put("log_path", args.logPath);
        manifest.put("output_dir", outputDir.toString());

        try {
            XLog xlog = parseLog(Paths.get(args.logPath));
            UIContext uiContext = new UIContext();
            UIPluginContext pluginContext = uiContext.getMainPluginContext();
            pluginContext.setFuture(new HeadlessExecutionResult(16));
            EventLog eventLog = new EventLog(xlog);

            FlexibleHeuristicsMinerSettings heuristics = buildHeuristics(args);
            FusionMinerSettings fusion = buildFusion(args);

            FusionMINERful miner = new FusionMINERful(pluginContext, eventLog, heuristics, fusion);
            FusionMINERfulResult result = miner.mineModel();

            Path fusionResultPath = rawDir.resolve("model.fusion_result.json");
            Path connectionsPath = rawDir.resolve("model.connections.json");
            Path hybridModelPath = normalizedDir.resolve("hybrid_model.json");
            Path pnwaModelPath = normalizedDir.resolve("pnwa_model.json");
            Path mpccResultPath = rawDir.resolve("mpcc_result.json");

            writeJson(fusionResultPath, buildFusionResultJson(result));
            writeJson(connectionsPath, buildConnectionsJson(pluginContext));
            writeJson(hybridModelPath, buildHybridModelJson(result));

            MpccService.Result mpcc = new MpccService().compute(pluginContext, result, xlog);
            writeJson(mpccResultPath, mpcc.toJson());
            manifest.putAll(mpcc.toJson());
            manifest.put("mpcc_result_path", mpccResultPath.toString());

            // PNwA alignment-based precision/generalization (AlignmentPrecGen, De Smedt 2015 §3.3).
            // Reuses the alignment + transition mapping computed during MPCC fitness above.
            long precisionStartedAt = System.currentTimeMillis();
            String precisionStatus = "skipped";
            String precisionError = null;
            Double precisionValue = null;
            Double generalizationValue = null;
            if (mpcc.alignment != null && mpcc.mapping != null && result.getPetriNetWithAutomata() != null) {
                try {
                    AlignmentPrecGenRes precRes = new AlignmentPrecGen().measureConformanceAssumingCorrectAlignment(
                            pluginContext,
                            mpcc.mapping,
                            mpcc.alignment,
                            result.getPetriNetWithAutomata(),
                            result.getInitialMarking(),
                            false);
                    if (precRes != null) {
                        precisionValue = Double.valueOf(precRes.getPrecision());
                        generalizationValue = Double.valueOf(precRes.getGeneralization());
                        precisionStatus = "ok";
                    } else {
                        precisionError = "AlignmentPrecGen returned null.";
                        precisionStatus = "error";
                    }
                } catch (Throwable t) {
                    precisionError = t.getClass().getSimpleName() + ": " + t.getMessage();
                    precisionStatus = "error";
                    t.printStackTrace(System.err);
                }
            } else {
                precisionError = "No alignment, mapping, or PNwA model available for precision computation.";
            }
            manifest.put("pnwa_precision", precisionValue);
            manifest.put("pnwa_generalization", generalizationValue);
            manifest.put("pnwa_precision_status", precisionStatus);
            manifest.put("pnwa_precision_error", precisionError);
            manifest.put("pnwa_precision_method", "alignment_based_etc_pnwa");
            manifest.put("pnwa_precision_runtime_ms",
                    Long.valueOf(System.currentTimeMillis() - precisionStartedAt));

            HybridTraceSampler.Params samplerParams = new HybridTraceSampler.Params();
            samplerParams.nValidSamples = args.precisionValidSamples;
            samplerParams.maxAttempts = args.precisionMaxAttempts > 0
                    ? args.precisionMaxAttempts
                    : 20 * args.precisionValidSamples;
            samplerParams.maxTraceLength = args.precisionMaxTraceLength;
            samplerParams.seed = args.precisionSeed;
            HybridTraceSampler.Stats samplerStats = new HybridTraceSampler.Stats();
            List<List<String>> hybridSamples = new HybridTraceSampler().sample(result, samplerParams, samplerStats);
            Path hybridSamplesPath = rawDir.resolve("model_sample_traces.csv");
            Path hybridSampleStatsPath = rawDir.resolve("model_sample_stats.json");
            HybridTraceSampler.writeCsv(hybridSamplesPath, hybridSamples);
            writeJson(hybridSampleStatsPath, HybridTraceSampler.statsToJson(samplerStats, samplerParams));
            manifest.putAll(HybridTraceSampler.statsToManifest(samplerStats, samplerParams));
            manifest.put("model_sample_traces_path", hybridSamplesPath.toString());
            manifest.put("model_sample_stats_path", hybridSampleStatsPath.toString());

            Path hybridPngPath = renderedDir.resolve("hybrid_model.png");
            Path hybridSvgPath = renderedDir.resolve("hybrid_model.svg");
            RenderResult hybridPngRender = renderFusionResultPng(pluginContext, result, hybridPngPath.toFile());
            // PNG-only mode for downstream UIs.
            boolean hybridSvgCreated = false;
            manifest.put("hybrid_png_path", hybridPngPath.toString());
            manifest.put("hybrid_png_created", Boolean.valueOf(hybridPngRender.created));
            manifest.put("hybrid_png_error", hybridPngRender.error);
            manifest.put("hybrid_svg_path", hybridSvgPath.toString());
            manifest.put("hybrid_svg_created", Boolean.valueOf(hybridSvgCreated));

            PetrinetWithAutomata pnwa = result.getPetriNetWithAutomata();
            boolean pnwaPresent = pnwa != null;
            manifest.put("pnwa_present", Boolean.valueOf(pnwaPresent));
            if (pnwaPresent) {
                writeJson(pnwaModelPath, buildPnwaModelJson(pnwa, result.getInitialMarking(), result.getFinalMarking()));
                Path dpnmlPath = rawDir.resolve("model.pnwa.dpnml");
                new PnmlExportMPModel().exportPetriNetToPNMLFile(pluginContext, pnwa, dpnmlPath.toFile());
                manifest.put("pnwa_dpnml_path", dpnmlPath.toString());
                Path pnwaPngPath = renderedDir.resolve("pnwa_model.png");
                Path pnwaSvgPath = renderedDir.resolve("pnwa_model.svg");
                RenderResult pnwaPngRender = renderPnwaPng(pluginContext, pnwa, result.getInitialMarking(), pnwaPngPath.toFile());
                // PNG-only mode for downstream UIs.
                boolean pnwaSvgCreated = false;
                manifest.put("pnwa_png_path", pnwaPngPath.toString());
                manifest.put("pnwa_png_created", Boolean.valueOf(pnwaPngRender.created));
                manifest.put("pnwa_png_error", pnwaPngRender.error);
                manifest.put("pnwa_svg_path", pnwaSvgPath.toString());
                manifest.put("pnwa_svg_created", Boolean.valueOf(pnwaSvgCreated));
            }

            Petrinet petriNet = result.getPetriNet();
            boolean petriNetPresent = petriNet != null;
            manifest.put("petri_net_present", Boolean.valueOf(petriNetPresent));
            if (petriNetPresent) {
                Path pnmlPath = rawDir.resolve("model.pnml");
                new PnmlExportNetToPNML().exportPetriNetToPNMLFile(pluginContext, petriNet, pnmlPath.toFile());
                manifest.put("pnml_path", pnmlPath.toString());
            }

            manifest.put("fusion_result_path", fusionResultPath.toString());
            manifest.put("connections_path", connectionsPath.toString());
            manifest.put("hybrid_model_path", hybridModelPath.toString());
            manifest.put("pnwa_model_path", pnwaPresent ? pnwaModelPath.toString() : null);
            manifest.put("status", "success");
            manifest.put("error_class", null);
            manifest.put("error_message", null);
        } catch (Throwable throwable) {
            manifest.put("status", "error");
            manifest.put("error_class", throwable.getClass().getSimpleName());
            manifest.put("error_message", throwable.getMessage());
            throwable.printStackTrace(System.err);
        } finally {
            long finishedAt = System.currentTimeMillis();
            manifest.put("finished_at", Instant.ofEpochMilli(finishedAt).toString());
            manifest.put("runtime_ms", Long.valueOf(finishedAt - startedAt));
            writeJson(rawDir.resolve("headless_manifest.json"), manifest);
        }
        // Force JVM exit even if the AWT Event Dispatch Thread is still running
        // (non-headless mode starts it and it holds the JVM alive indefinitely).
        System.exit(0);
    }

    private static Args parseArgs(String[] argv) {
        Args args = new Args();
        for (int i = 0; i < argv.length; i += 2) {
            String key = argv[i];
            String value = (i + 1) < argv.length ? argv[i + 1] : "";
            if ("--log".equals(key)) {
                args.logPath = value;
            } else if ("--output-dir".equals(key)) {
                args.outputDir = value;
            } else if ("--relative-to-best-threshold".equals(key)) {
                args.relativeToBestThreshold = Double.parseDouble(value);
            } else if ("--positive-observation-threshold".equals(key)) {
                args.positiveObservationThreshold = Integer.parseInt(value);
            } else if ("--dependency-threshold".equals(key)) {
                args.dependencyThreshold = Double.parseDouble(value);
            } else if ("--l1l-threshold".equals(key)) {
                args.l1lThreshold = Double.parseDouble(value);
            } else if ("--l2l-threshold".equals(key)) {
                args.l2lThreshold = Double.parseDouble(value);
            } else if ("--long-distance-threshold".equals(key)) {
                args.longDistanceThreshold = Double.parseDouble(value);
            } else if ("--dependency-divisor".equals(key)) {
                args.dependencyDivisor = Integer.parseInt(value);
            } else if ("--use-all-connected-heuristics".equals(key)) {
                args.useAllConnectedHeuristics = Boolean.parseBoolean(value);
            } else if ("--use-long-distance-dependency".equals(key)) {
                args.useLongDistanceDependency = Boolean.parseBoolean(value);
            } else if ("--use-unique-start-end-tasks".equals(key)) {
                args.useUniqueStartEndTasks = Boolean.parseBoolean(value);
            } else if ("--declare-support".equals(key)) {
                args.declareSupport = Double.parseDouble(value);
            } else if ("--declare-alpha".equals(key)) {
                args.declareAlpha = Double.parseDouble(value);
            } else if ("--activity-entropy".equals(key)) {
                args.activityEntropy = Double.parseDouble(value);
            } else if ("--resilience".equals(key)) {
                args.resilience = Double.parseDouble(value);
            } else if ("--im-fitness".equals(key)) {
                args.imFitness = Double.parseDouble(value);
            } else if ("--size-multiplicator".equals(key)) {
                args.sizeMultiplicator = Integer.parseInt(value);
            } else if ("--cut".equals(key)) {
                args.cut = Boolean.parseBoolean(value);
            } else if ("--prune".equals(key)) {
                args.prune = Boolean.parseBoolean(value);
            } else if ("--negative".equals(key)) {
                args.negative = Boolean.parseBoolean(value);
            } else if ("--check-model".equals(key)) {
                args.checkModel = Boolean.parseBoolean(value);
            } else if ("--precision-valid-samples".equals(key)) {
                args.precisionValidSamples = Integer.parseInt(value);
            } else if ("--precision-max-attempts".equals(key)) {
                args.precisionMaxAttempts = Integer.parseInt(value);
            } else if ("--precision-max-trace-length".equals(key)) {
                args.precisionMaxTraceLength = Integer.parseInt(value);
            } else if ("--precision-seed".equals(key)) {
                args.precisionSeed = Long.parseLong(value);
            }
        }
        if (args.logPath == null || args.outputDir == null) {
            throw new IllegalArgumentException("Both --log and --output-dir are required.");
        }
        return args;
    }

    private static FlexibleHeuristicsMinerSettings buildHeuristics(Args args) {
        FlexibleHeuristicsMinerSettings settings = new FlexibleHeuristicsMinerSettings();
        settings.setRelativeToBestThreshold(args.relativeToBestThreshold);
        settings.setPositiveObservationThreshold(args.positiveObservationThreshold);
        settings.setDependencyThreshold(args.dependencyThreshold);
        settings.setL1lThreshold(args.l1lThreshold);
        settings.setL2lThreshold(args.l2lThreshold);
        settings.setLongDistanceThreshold(args.longDistanceThreshold);
        settings.setDependencyDivisor(args.dependencyDivisor);
        settings.setUseAllConnectedHeuristics(args.useAllConnectedHeuristics);
        settings.setUseLongDistanceDependency(args.useLongDistanceDependency);
        settings.setUseUniqueStartEndTasks(args.useUniqueStartEndTasks);
        return settings;
    }

    private static FusionMinerSettings buildFusion(Args args) {
        FusionMinerSettings settings = new FusionMinerSettings();
        settings.setDeclareSupport(args.declareSupport);
        settings.setDeclareAlpha(args.declareAlpha);
        settings.setActivityEntropy(args.activityEntropy);
        settings.setResilience(args.resilience);
        settings.setIMFitness(args.imFitness);
        settings.setSizeMultiplicator(args.sizeMultiplicator);
        settings.setCut(args.cut);
        settings.setPrune(args.prune);
        settings.setNegative(args.negative);
        settings.setChecking(args.checkModel);
        return settings;
    }

    private static XLog parseLog(Path logPath) throws Exception {
        List<XParser> parsers = new ArrayList<XParser>();
        parsers.add(new XesXmlParser());
        parsers.add(new XMxmlParser());
        for (XParser parser : parsers) {
            if (!parser.canParse(logPath.toFile())) {
                continue;
            }
            List<XLog> logs = parser.parse(logPath.toFile());
            if (!logs.isEmpty()) {
                return logs.get(0);
            }
        }
        throw new IllegalArgumentException("Unable to parse log file: " + logPath);
    }

    private static Map<String, Object> buildFusionResultJson(FusionMINERfulResult result) {
        Map<String, Object> data = new LinkedHashMap<String, Object>();
        data.put("entropy_level", Double.valueOf(result.getEntropyLevel()));
        data.put("entropic_activities", characterCollectionToNames(result.getEntropicActivities(), result));
        data.put("activity_classification", classificationToJson(result));
        data.put("removed_constraints", constraintsToJson(result.getRemovedConstraints()));
        data.put("tau_transitions", characterCollectionToNames(result.getTauTransitions(), result));
        data.put("pnwa_present", Boolean.valueOf(result.getPetriNetWithAutomata() != null));
        data.put("petri_net_present", Boolean.valueOf(result.getPetriNet() != null));
        data.put("procedural_node_count", Integer.valueOf(result.getProceduralModel() == null ? 0 : result.getProceduralModel().getNodes().size()));
        data.put("declarative_constraint_count", Integer.valueOf(result.getProcessModel() == null ? 0 : result.getProcessModel().getAllConstraints().size()));
        return data;
    }

    private static Map<String, Object> buildHybridModelJson(FusionMINERfulResult result) {
        Map<String, Object> root = new LinkedHashMap<String, Object>();
        root.put("kind", "fusion_hybrid_model");
        root.put("entropy_level", Double.valueOf(result.getEntropyLevel()));
        root.put("entropic_activities", characterCollectionToNames(result.getEntropicActivities(), result));
        root.put("removed_constraints", constraintsToJson(result.getRemovedConstraints()));
        root.put("tau_transitions", characterCollectionToNames(result.getTauTransitions(), result));
        root.put("activity_classification", classificationToJson(result));

        Flex flex = result.getProceduralModel();
        Map<String, Object> procedural = new LinkedHashMap<String, Object>();
        List<Map<String, Object>> nodeData = new ArrayList<Map<String, Object>>();
        List<Map<String, Object>> edgeData = new ArrayList<Map<String, Object>>();
        if (flex != null) {
            for (FlexNode node : flex.getNodes()) {
                Map<String, Object> entry = new LinkedHashMap<String, Object>();
                entry.put("label", node.getLabel());
                nodeData.add(entry);
            }
            for (FlexEdge<? extends FlexNode, ? extends FlexNode> edge : flex.getEdges()) {
                Map<String, Object> entry = new LinkedHashMap<String, Object>();
                entry.put("source", edge.getSource().getLabel());
                entry.put("target", edge.getTarget().getLabel());
                edgeData.add(entry);
            }
        }
        procedural.put("nodes", nodeData);
        procedural.put("edges", edgeData);
        root.put("procedural", procedural);

        ProcessModel processModel = result.getProcessModel();
        Map<String, Object> declarative = new LinkedHashMap<String, Object>();
        declarative.put("constraints", constraintsToJson(processModel == null ? null : processModel.getAllConstraints()));
        root.put("declarative", declarative);
        return root;
    }

    private static Map<String, Object> buildPnwaModelJson(PetrinetWithAutomata pnwa, Marking initialMarking, Marking finalMarking) {
        Map<String, Object> root = new LinkedHashMap<String, Object>();
        List<Map<String, Object>> places = new ArrayList<Map<String, Object>>();
        List<Map<String, Object>> transitions = new ArrayList<Map<String, Object>>();
        List<Map<String, Object>> arcs = new ArrayList<Map<String, Object>>();
        List<Map<String, Object>> constraints = new ArrayList<Map<String, Object>>();

        for (Place place : pnwa.getPlaces()) {
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            entry.put("id", id(place.getId()));
            entry.put("label", place.getLabel());
            entry.put("in_initial_marking", Boolean.valueOf(initialMarking != null && initialMarking.contains(place)));
            entry.put("in_final_marking", Boolean.valueOf(finalMarking != null && finalMarking.contains(place)));
            places.add(entry);
        }

        for (Transition transition : pnwa.getTransitions()) {
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            entry.put("id", id(transition.getId()));
            entry.put("label", transition.getLabel());
            entry.put("invisible", Boolean.valueOf(transition.isInvisible()));
            transitions.add(entry);
        }

        for (PetrinetEdge<? extends PetrinetNode, ? extends PetrinetNode> arc : pnwa.getEdges()) {
            if (arc instanceof DeclarativeArc) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            entry.put("source_id", id(arc.getSource().getId()));
            entry.put("target_id", id(arc.getTarget().getId()));
            entry.put("source_label", labelForNode(arc.getSource()));
            entry.put("target_label", labelForNode(arc.getTarget()));
            arcs.add(entry);
        }

        for (DeclarativeArc arc : pnwa.getConstraints()) {
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            List<String> sourceIds = transitionIds(arc.getSources());
            List<String> targetIds = transitionIds(arc.getTargets());
            List<String> sourceLabels = transitionLabels(arc.getSources());
            List<String> targetLabels = transitionLabels(arc.getTargets());
            Object constraintType = arc.getType();
            String constraintClass = constraintType == null ? null : constraintType.getClass().getName();
            String arity = "unknown";
            if (constraintClass != null && constraintClass.contains(".unary.")) {
                arity = "unary";
            } else if (constraintClass != null && constraintClass.contains(".binary.")) {
                arity = "binary";
            } else if (sourceIds.isEmpty() || targetIds.isEmpty()) {
                arity = "unary";
            } else if (sourceIds.equals(targetIds)) {
                arity = "unary";
            } else {
                arity = "binary";
            }
            entry.put("type", constraintType == null ? "unknown" : constraintType.getClass().getSimpleName());
            entry.put("type_class", constraintClass);
            entry.put("type_raw", constraintType == null ? null : constraintType.toString());
            entry.put("arity", arity);
            entry.put("sources", sourceIds);
            entry.put("targets", targetIds);
            entry.put("source_labels", sourceLabels);
            entry.put("target_labels", targetLabels);
            constraints.add(entry);
        }

        root.put("places", places);
        root.put("transitions", transitions);
        root.put("arcs", arcs);
        root.put("constraints", constraints);
        return root;
    }

    private static RenderResult renderFusionResultPng(UIPluginContext context, FusionMINERfulResult result, File outputFile) {
        StringBuilder errors = new StringBuilder();

        try {
            JComponent component = FusionMINERfulProMVisualization.visualize(context, result);
            RenderResult rendered = renderComponentToPng(component, outputFile, 1900, 1200);
            if (rendered.created) {
                return rendered;
            }
            errors.append("FusionMINERfulProMVisualization: ").append(rendered.error);
        } catch (Throwable throwable) {
            errors.append("FusionMINERfulProMVisualization: ").append(throwable.toString());
        }
        try {
            JComponent component = FusionMINERfulVisualization.visualize(context, result);
            RenderResult rendered = renderComponentToPng(component, outputFile, 1900, 1200);
            if (rendered.created) {
                return rendered;
            }
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("FusionMINERfulVisualization: ").append(rendered.error);
        } catch (Throwable throwable) {
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("FusionMINERfulVisualization: ").append(throwable.toString());
        }

        try {
            ProMJGraphPanel panel = visualizeFusionResultWithLayout(context, result);
            RenderResult rendered = renderComponentToPng(panel, outputFile, 1900, 1200);
            if (rendered.created) {
                return rendered;
            }
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("ProMJGraphVisualizer: ").append(rendered.error);
        } catch (Throwable throwable) {
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("ProMJGraphVisualizer: ").append(throwable.toString());
        }
        return RenderResult.fail(errors.length() == 0 ? "unknown render failure" : errors.toString());
    }

    /**
     * Headless-capable port of {@code FusionMINERfulVisualization#visualize}. Instead of
     * returning the {@code JComponent} wrapper (ScalableViewPanel) whose inner JGraph
     * is only laid out upon a display-hierarchy event, this method calls
     * {@link ProMJGraphVisualizer#visualizeGraph} directly and returns the resulting
     * {@link ProMJGraphPanel}, which is proven to paint correctly via offscreen
     * {@code printAll(Graphics2D)} (see {@link #visualizePnwaWithLayout}).
     *
     * <p>The mutation logic (removing entropy self-loops, pruning START/END nodes when
     * Init/End constraints are present, injecting declarative constraints as Flex edges,
     * classifying Participation/AtMostOne activities) is a faithful port of the original
     * source extracted from {@code FusionMinerFul.jar}.
     */
    private static ProMJGraphPanel visualizeFusionResultWithLayout(UIPluginContext context,
                                                                    FusionMINERfulResult result) {
        Flex graph = result.getProceduralModel();
        ProcessModel declareOutput = result.getProcessModel();
        Collection<Constraint> removedConstraints = result.getRemovedConstraints();
        if (removedConstraints == null) {
            removedConstraints = new ArrayList<Constraint>();
        }
        Set<FlexEdge<?, ?>> redColoredConstraints = new HashSet<FlexEdge<?, ?>>();

        char init = ' ';
        char last = ' ';

        List<Collection<Character>> classification = result.getActivityClassification();
        Collection<Character> DD = classification.get(0);
        Collection<Character> DLd = classification.get(1);
        Collection<Character> LDd = classification.get(3);

        EventLog eventLog = result.getEventLog();
        Collection<Character> entropyAct = result.getEntropicActivities();
        if (entropyAct == null) {
            entropyAct = new ArrayList<Character>();
        }

        // Make procedural diagram: remove entropy self-loops on non-START/END nodes,
        // clear edge labels for surviving procedural edges.
        if (graph != null && result.getEntropyLevel() != 1) {
            List<FlexEdge<?, ?>> toRemove = new ArrayList<FlexEdge<?, ?>>();
            for (FlexEdge<?, ?> flex : graph.getEdges()) {
                String sourceLabel = flex.getSource().getLabel();
                String targetLabel = flex.getTarget().getLabel();
                if (sourceLabel == null || targetLabel == null
                        || sourceLabel.isEmpty() || targetLabel.isEmpty()) {
                    flex.getAttributeMap().put(AttributeMap.LABEL, "");
                    continue;
                }
                char so = sourceLabel.charAt(0);
                char ta = targetLabel.charAt(0);
                boolean remove = (so == ta) && entropyAct.contains(so);
                if (remove && !"START".equals(sourceLabel) && !"END".equals(targetLabel)) {
                    toRemove.add(flex);
                } else {
                    flex.getAttributeMap().put(AttributeMap.LABEL, "");
                }
            }
            for (FlexEdge<?, ?> edge : toRemove) {
                graph.removeEdge(edge);
            }
        }

        // Add Declare constraints.
        Set<Character> exactly1 = new HashSet<Character>();
        Set<Character> existence = new HashSet<Character>();
        Set<Character> absence2 = new HashSet<Character>();

        if (graph != null && declareOutput != null && declareOutput.bag != null) {
            for (Constraint c : declareOutput.bag.getAllConstraints()) {
                if (c.getFamily() != null && c.getFamily().equals(ConstraintFamily.EXISTENCE)) {
                    if (c.getParameters() == null || c.getParameters().isEmpty()) {
                        continue;
                    }
                    TaskChar firstTask = c.getParameters().get(0).getFirstTaskChar();
                    if (firstTask == null) {
                        continue;
                    }
                    char act = firstTask.identifier;
                    boolean go = DD.contains(act) || DLd.contains(act) || LDd.contains(act);
                    if (go) {
                        if (c instanceof Init) {
                            FlexNode toRemove = null;
                            for (FlexNode fn : graph.getNodes()) {
                                if ("START".equals(fn.getLabel())) {
                                    toRemove = fn;
                                    break;
                                }
                            }
                            if (toRemove != null) {
                                graph.removeNode(toRemove);
                            }
                            init = act;
                        }
                        if (c instanceof End) {
                            FlexNode toRemove = null;
                            for (FlexNode fn : graph.getNodes()) {
                                if ("END".equals(fn.getLabel())) {
                                    toRemove = fn;
                                    break;
                                }
                            }
                            if (toRemove != null) {
                                graph.removeNode(toRemove);
                            }
                            last = act;
                        }
                    }
                    if (c instanceof Participation) {
                        existence.add(act);
                    }
                    if (c instanceof AtMostOne) {
                        absence2.add(act);
                    }
                } else {
                    if (c.getParameters() == null || c.getParameters().size() < 2) {
                        continue;
                    }
                    TaskChar sourceTask = c.getParameters().get(0).getFirstTaskChar();
                    TaskChar targetTask = c.getParameters().get(1).getFirstTaskChar();
                    if (sourceTask == null || targetTask == null) {
                        continue;
                    }
                    char so = sourceTask.identifier;
                    char ta = targetTask.identifier;

                    FlexNode sourceN = null;
                    FlexNode targetN = null;
                    for (FlexNode n : graph.getNodes()) {
                        String label = n.getLabel();
                        if (label == null || label.isEmpty()) {
                            continue;
                        }
                        if (so == label.charAt(0)) {
                            sourceN = n;
                        }
                        if (ta == label.charAt(0)) {
                            targetN = n;
                        }
                    }
                    if (sourceN == null || targetN == null) {
                        continue;
                    }
                    FlexEdge<FlexNode, FlexNode> edge = graph.addArc(sourceN, targetN);
                    edge.getAttributeMap().put(AttributeMap.LABEL, c.type);

                    if (removedConstraints.contains(c)) {
                        FlexEdge<FlexNode, FlexNode> redEdge = graph.addArc(sourceN, targetN);
                        redColoredConstraints.add(redEdge);
                    }
                }
            }
        }

        for (Character i : existence) {
            if (absence2.contains(i)) {
                exactly1.add(i);
            }
        }

        ViewSpecificAttributeMap viewSpecificMap = new ViewSpecificAttributeMap();
        if (graph != null) {
            for (DirectedGraphNode node : graph.getNodes()) {
                String label = node.getLabel();
                if (label == null || label.isEmpty()) {
                    continue;
                }
                char firstChar = label.charAt(0);

                viewSpecificMap.putViewSpecific(node, AttributeMap.SIZE, new Dimension(100, 30));
                viewSpecificMap.putViewSpecific(node, AttributeMap.FILLCOLOR, Color.WHITE);

                if (entropyAct.contains(firstChar)) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.BORDERWIDTH, Integer.valueOf(1));
                    viewSpecificMap.putViewSpecific(node, AttributeMap.DASHPATTERN,
                            new float[] { (float) 4.0, (float) 2.0 });
                }
                if (existence.contains(firstChar)) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.FILLCOLOR, Color.LIGHT_GRAY);
                    viewSpecificMap.putViewSpecific(node, AttributeMap.BORDERWIDTH, Integer.valueOf(1));
                }
                if (exactly1.contains(firstChar)) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.FILLCOLOR, Color.RED);
                    viewSpecificMap.putViewSpecific(node, AttributeMap.BORDERWIDTH, Integer.valueOf(1));
                }
                if (init == firstChar) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.SHAPE, new Rectangle());
                }
                if (last == firstChar) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.SHAPE, new Rectangle());
                }
                if (eventLog != null && eventLog.getLabel(firstChar) != null) {
                    viewSpecificMap.putViewSpecific(node, AttributeMap.LABEL, eventLog.getLabel(firstChar));
                }
            }

            for (DirectedGraphEdge<?, ?> e : graph.getEdges()) {
                String edgeLabel = e.getLabel();
                if (edgeLabel == null) {
                    edgeLabel = "";
                }
                if (!edgeLabel.isEmpty()) {
                    e.getAttributeMap().put(AttributeMap.DASHPATTERN,
                            new float[] { (float) 3.0, (float) 3.0 });
                    e.getAttributeMap().put(AttributeMap.LABEL, edgeLabel);
                    e.getAttributeMap().put(AttributeMap.SHOWLABEL, Boolean.TRUE);
                }
                if ("RespondedExistence".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEEND, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                } else if ("CoExistence".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEEND, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if ("Response".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEEND, ArrowType.ARROWTYPE_TECHNICAL);
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if ("Precedence".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                } else if ("Succession".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if ("AlternatePrecedence".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGEMIDDLEFILLED, Boolean.TRUE);
                } else if ("AlternateResponse".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEEND, ArrowType.ARROWTYPE_DIAMOND);
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if ("AlternateSuccession".equals(edgeLabel)) {
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_DIAMOND);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if (edgeLabel.contains("Not")) {
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.TRUE);
                    e.getAttributeMap().put(AttributeMap.EDGECOLOR, Color.ORANGE);
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_DIAMOND);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.TRUE);
                } else if (!edgeLabel.isEmpty()) {
                    e.getAttributeMap().put(AttributeMap.EDGESTART, ArrowType.ARROWTYPE_CIRCLE);
                    e.getAttributeMap().put(AttributeMap.EDGESTARTFILLED, Boolean.FALSE);
                    e.getAttributeMap().put(AttributeMap.EDGEEND, ArrowType.ARROWTYPE_SIMPLE);
                    e.getAttributeMap().put(AttributeMap.EDGEENDFILLED, Boolean.FALSE);
                } else {
                    e.getAttributeMap().put(AttributeMap.EDGECOLOR, Color.BLUE);
                    e.getAttributeMap().put(AttributeMap.SHOWLABEL, Boolean.FALSE);
                }
                for (FlexEdge<?, ?> f : redColoredConstraints) {
                    if (e.getSource().equals(f.getSource())
                            && e.getTarget().equals(f.getTarget())
                            && edgeLabel.equals(f.getLabel())) {
                        e.getAttributeMap().put(AttributeMap.EDGECOLOR, Color.RED);
                        e.getAttributeMap().put(AttributeMap.LABELCOLOR, Color.RED);
                    }
                }
            }
        }

        ProMJGraphPanel panel = ProMJGraphVisualizer.instance().visualizeGraph(context, graph, viewSpecificMap);
        panel.scaleToFit();
        return panel;
    }

    private static RenderResult renderPnwaPng(UIPluginContext context, PetrinetWithAutomata pnwa, Marking initialMarking, File outputFile) {
        StringBuilder errors = new StringBuilder();

        // MPVisualizer triggers Swing dialog chains — only attempt when a display is present.
        if (!isHeadlessMode()) {
            try {
                JComponent component = new MPVisualizer().visualize(context, pnwa, initialMarking);
                RenderResult rendered = renderComponentToPng(component, outputFile, 1900, 1200);
                if (rendered.created) {
                    return rendered;
                }
                errors.append("MPVisualizer: ").append(rendered.error);
            } catch (Throwable throwable) {
                errors.append("MPVisualizer: ").append(throwable.toString());
            }
        }

        // ProMJGraphVisualizer path works headlessly (ProMJGraphPanel paints correctly
        // via offscreen printAll). This used to be unreachable due to the blanket
        // isHeadlessMode() early return at the top of this method.
        try {
            ProMJGraphPanel panel = visualizePnwaWithLayout(context, pnwa, initialMarking);
            RenderResult rendered = renderComponentToPng(panel, outputFile, 1900, 1200);
            if (rendered.created) {
                return rendered;
            }
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("ProMJGraphVisualizer: ").append(rendered.error);
        } catch (Throwable throwable) {
            if (errors.length() > 0) {
                errors.append(" | ");
            }
            errors.append("ProMJGraphVisualizer: ").append(throwable.toString());
        }

        return RenderResult.fail(errors.length() == 0 ? "unknown render failure" : errors.toString());
    }

    private static ProMJGraphPanel visualizePnwaWithLayout(UIPluginContext context, PetrinetWithAutomata pnwa, Marking initialMarking) {
        ViewSpecificAttributeMap map = new ViewSpecificAttributeMap();
        if (initialMarking != null) {
            for (Place place : initialMarking) {
                String markingLabel = String.valueOf(initialMarking.occurrences(place));
                map.putViewSpecific(place, "ProM_Vis_attr_label", markingLabel);
                map.putViewSpecific(place, "ProM_Vis_attr_tooltip", place.getLabel());
                map.putViewSpecific(place, "ProM_Vis_attr_showLabel", Boolean.valueOf(!"".equals(markingLabel)));
            }
        }
        ProMJGraphPanel panel = ProMJGraphVisualizer.instance().visualizeGraph(context, pnwa, map);
        panel.scaleToFit();
        return panel;
    }

    private static RenderResult renderComponentToPng(final JComponent component, final File outputFile, final int defaultWidth, final int defaultHeight) {
        if (component == null) {
            return RenderResult.fail("visualizer returned null component");
        }

        // For ProMJGraphPanel, the lazy JGraph canvas only paints after the component
        // tree has been realized (addNotify) inside a window. Doing this up-front gives
        // the FreeHEP + direct-printAll paths a fully-laid-out component to work with.
        RenderResult realized = renderProMJGraphPanelInFrame(component, outputFile, defaultWidth, defaultHeight);
        if (realized.created) {
            return realized;
        }

        RenderResult exported = tryFreeHepPngExport(component, outputFile, defaultWidth, defaultHeight);
        if (exported.created) {
            return exported;
        }
        RenderResult direct = renderSingleComponentToPng(component, outputFile, defaultWidth, defaultHeight);
        if (direct.created) {
            return direct;
        }
        JComponent inner = extractInnerRenderableComponent(component);
        if (inner != null && inner != component) {
            RenderResult second = renderSingleComponentToPng(inner, outputFile, defaultWidth, defaultHeight);
            if (second.created) {
                return second;
            }
            return RenderResult.fail(
                "freehep: " + nonEmpty(exported.error, "render failed")
                + " | direct: " + nonEmpty(direct.error, "render failed")
                + " | inner-component: " + nonEmpty(second.error, "render failed"));
        }
        return RenderResult.fail(
            "freehep: " + nonEmpty(exported.error, "render failed")
            + " | direct: " + nonEmpty(direct.error, "render failed"));
    }

    /**
     * Realise the component tree in an off-screen (never made visible) JFrame so the
     * lazy JGraph canvas actually paints, then render the inner {@code ProMJGraph}
     * directly to a BufferedImage. Without this, offscreen {@code printAll()} on a
     * {@code ProMJGraphPanel} yields only the surrounding ScalableViewPanel toolbar.
     * Requires {@code -Djava.awt.headless=false}; returns {@code fail} in headless mode.
     */
    private static RenderResult renderProMJGraphPanelInFrame(final JComponent component,
                                                             final File outputFile,
                                                             final int defaultWidth,
                                                             final int defaultHeight) {
        if (!(component instanceof ProMJGraphPanel)) {
            return RenderResult.fail("not a ProMJGraphPanel");
        }
        if (isHeadlessMode()) {
            return RenderResult.fail("headless mode — cannot realize JFrame");
        }
        final ProMJGraphPanel panel = (ProMJGraphPanel) component;
        final boolean[] ok = new boolean[] { false };
        final Throwable[] failure = new Throwable[] { null };

        Runnable painter = new Runnable() {
            @Override
            public void run() {
                javax.swing.JFrame frame = null;
                try {
                    frame = new javax.swing.JFrame();
                    frame.setUndecorated(true);
                    frame.setDefaultCloseOperation(javax.swing.JFrame.DISPOSE_ON_CLOSE);
                    frame.getContentPane().add(panel);
                    frame.setSize(defaultWidth, defaultHeight);
                    // Realise without actually becoming visible on screen.
                    frame.addNotify();
                    frame.validate();
                    frame.doLayout();
                    panel.validate();
                    panel.doLayout();

                    ProMJGraph jgraph = panel.getGraph();
                    if (jgraph == null) {
                        failure[0] = new IllegalStateException("ProMJGraphPanel.getGraph() returned null");
                        return;
                    }
                    jgraph.repositionToOrigin();
                    jgraph.revalidate();
                    jgraph.doLayout();
                    // Let pending Swing layout events flush.
                    try {
                        java.awt.Toolkit.getDefaultToolkit().sync();
                    } catch (Throwable ignored) {
                    }

                    // Size the BufferedImage to the laid-out JGraph.
                    java.awt.geom.Rectangle2D graphBounds = jgraph.getCellBounds(jgraph.getRoots());
                    int gw;
                    int gh;
                    if (graphBounds != null && graphBounds.getWidth() > 0 && graphBounds.getHeight() > 0) {
                        gw = (int) Math.ceil(graphBounds.getMaxX()) + 40;
                        gh = (int) Math.ceil(graphBounds.getMaxY()) + 40;
                    } else {
                        Dimension pref = jgraph.getPreferredSize();
                        gw = (pref != null && pref.width > 0) ? pref.width : defaultWidth;
                        gh = (pref != null && pref.height > 0) ? pref.height : defaultHeight;
                    }
                    gw = Math.max(gw, 600);
                    gh = Math.max(gh, 400);
                    jgraph.setSize(gw, gh);
                    jgraph.setPreferredSize(new Dimension(gw, gh));
                    jgraph.doLayout();

                    BufferedImage image = new BufferedImage(gw, gh, BufferedImage.TYPE_INT_ARGB);
                    Graphics2D graphics = image.createGraphics();
                    graphics.setColor(Color.WHITE);
                    graphics.fillRect(0, 0, gw, gh);
                    graphics.setRenderingHint(java.awt.RenderingHints.KEY_ANTIALIASING,
                                              java.awt.RenderingHints.VALUE_ANTIALIAS_ON);
                    graphics.setRenderingHint(java.awt.RenderingHints.KEY_TEXT_ANTIALIASING,
                                              java.awt.RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
                    jgraph.printAll(graphics);
                    graphics.dispose();

                    BufferedImage cropped = cropToInkBounds(image, 28);
                    if (looksVisuallyEmpty(cropped)) {
                        failure[0] = new IllegalStateException(
                            "JGraph printAll produced no sufficient ink inside a realized JFrame");
                        return;
                    }
                    if (outputFile.getParentFile() != null) {
                        outputFile.getParentFile().mkdirs();
                    }
                    boolean wrote = ImageIO.write(cropped, "png", outputFile);
                    if (!wrote) {
                        failure[0] = new IllegalStateException("ImageIO could not encode PNG");
                        return;
                    }
                    String validationError = validateRenderedOutput(outputFile, Dot2Image.Type.png);
                    if (validationError != null) {
                        failure[0] = new IllegalStateException(validationError);
                        return;
                    }
                    ok[0] = true;
                } catch (Throwable throwable) {
                    failure[0] = throwable;
                } finally {
                    if (frame != null) {
                        try {
                            frame.getContentPane().removeAll();
                        } catch (Throwable ignored) {
                        }
                        try {
                            frame.dispose();
                        } catch (Throwable ignored) {
                        }
                    }
                }
            }
        };
        try {
            if (SwingUtilities.isEventDispatchThread()) {
                painter.run();
            } else {
                final Object done = new Object();
                final boolean[] completed = new boolean[] { false };
                SwingUtilities.invokeLater(new Runnable() {
                    @Override
                    public void run() {
                        try { painter.run(); }
                        finally {
                            synchronized (done) {
                                completed[0] = true;
                                done.notifyAll();
                            }
                        }
                    }
                });
                long deadline = System.currentTimeMillis() + 20000L;
                synchronized (done) {
                    while (!completed[0]) {
                        long remaining = deadline - System.currentTimeMillis();
                        if (remaining <= 0) break;
                        try { done.wait(remaining); }
                        catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
                    }
                    if (!completed[0]) {
                        return RenderResult.fail("realized-frame render timed out after 20s");
                    }
                }
            }
        } catch (Throwable throwable) {
            return RenderResult.fail(throwable.toString());
        }
        if (ok[0]) {
            return RenderResult.ok();
        }
        if (failure[0] != null) {
            return RenderResult.fail(failure[0].toString());
        }
        return RenderResult.fail("unknown realized-frame render failure");
    }

    private static RenderResult tryFreeHepPngExport(final JComponent component, final File outputFile, final int defaultWidth, final int defaultHeight) {
        try {
            List<ExportFileType> pngTypes = ExportFileType.getExportFileTypes("png");
            if (pngTypes == null || pngTypes.isEmpty()) {
                return RenderResult.fail("FreeHEP PNG export type not available");
            }
            int prefWidth = component.getPreferredSize() == null ? 0 : component.getPreferredSize().width;
            int prefHeight = component.getPreferredSize() == null ? 0 : component.getPreferredSize().height;
            int width = Math.max(defaultWidth, prefWidth);
            int height = Math.max(defaultHeight, prefHeight);
            component.setSize(width, height);
            component.setPreferredSize(new Dimension(width, height));
            component.doLayout();
            component.revalidate();

            if (outputFile.getParentFile() != null) {
                outputFile.getParentFile().mkdirs();
            }
            Properties props = new Properties();
            props.setProperty("SAVE_AS_FILE", "true");
            props.setProperty("TRANSPARENT", "false");
            ExportFileType pngType = pngTypes.get(0);
            pngType.exportToFile(outputFile, component, component, props, "View");

            BufferedImage image = ImageIO.read(outputFile);
            if (image == null) {
                return RenderResult.fail("FreeHEP exported PNG could not be read");
            }
            BufferedImage cropped = cropToInkBounds(image, 28);
            if (looksVisuallyEmpty(cropped)) {
                return RenderResult.fail("FreeHEP exported image appears empty");
            }
            boolean wrote = ImageIO.write(cropped, "png", outputFile);
            if (!wrote) {
                return RenderResult.fail("ImageIO could not encode PNG");
            }
            String validationError = validateRenderedOutput(outputFile, Dot2Image.Type.png);
            if (validationError != null) {
                return RenderResult.fail(validationError);
            }
            return RenderResult.ok();
        } catch (Throwable throwable) {
            return RenderResult.fail(throwable.toString());
        }
    }

    private static RenderResult renderSingleComponentToPng(final JComponent component, final File outputFile, final int defaultWidth, final int defaultHeight) {
        final boolean[] ok = new boolean[] { false };
        final Throwable[] failure = new Throwable[] { null };
        Runnable painter = new Runnable() {
            @Override
            public void run() {
                try {
                    if (component instanceof ProMJGraphPanel) {
                        ProMJGraphPanel panel = (ProMJGraphPanel) component;
                        ProMJGraph graph = panel.getGraph();
                        if (graph != null) {
                            graph.repositionToOrigin();
                            graph.revalidate();
                            graph.repaint();
                        }
                        panel.revalidate();
                        panel.repaint();
                    }
                    int prefWidth = component.getPreferredSize() == null ? 0 : component.getPreferredSize().width;
                    int prefHeight = component.getPreferredSize() == null ? 0 : component.getPreferredSize().height;
                    int width = Math.max(defaultWidth, prefWidth);
                    int height = Math.max(defaultHeight, prefHeight);
                    component.setSize(width, height);
                    component.setPreferredSize(new Dimension(width, height));
                    component.doLayout();
                    component.revalidate();
                    BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
                    Graphics2D graphics = image.createGraphics();
                    graphics.setColor(Color.WHITE);
                    graphics.fillRect(0, 0, width, height);
                    component.printAll(graphics);
                    graphics.dispose();
                    BufferedImage cropped = cropToInkBounds(image, 28);
                    if (looksVisuallyEmpty(cropped)) {
                        failure[0] = new IllegalStateException(
                            "rendered image appears empty (no sufficient graph ink); falling back to SVG");
                        ok[0] = false;
                        return;
                    }
                    if (outputFile.getParentFile() != null) {
                        outputFile.getParentFile().mkdirs();
                    }
                    boolean wrote = ImageIO.write(cropped, "png", outputFile);
                    if (!wrote) {
                        failure[0] = new IllegalStateException("ImageIO could not encode PNG");
                        ok[0] = false;
                        return;
                    }
                    String validationError = validateRenderedOutput(outputFile, Dot2Image.Type.png);
                    if (validationError != null) {
                        failure[0] = new IllegalStateException(validationError);
                        ok[0] = false;
                        return;
                    }
                    ok[0] = true;
                } catch (Throwable throwable) {
                    failure[0] = throwable;
                    ok[0] = false;
                }
            }
        };
        try {
            if (SwingUtilities.isEventDispatchThread()) {
                painter.run();
            } else {
                SwingUtilities.invokeAndWait(painter);
            }
        } catch (Throwable throwable) {
            return RenderResult.fail(throwable.toString());
        }
        if (ok[0]) {
            return RenderResult.ok();
        }
        if (failure[0] != null) {
            return RenderResult.fail(failure[0].toString());
        }
        return RenderResult.fail("unknown render failure");
    }

    private static JComponent extractInnerRenderableComponent(JComponent component) {
        try {
            Method noArgGetComponent = component.getClass().getMethod("getComponent");
            Object candidate = noArgGetComponent.invoke(component);
            if (candidate instanceof JComponent) {
                return (JComponent) candidate;
            }
            if (candidate instanceof Component) {
                Component awtComponent = (Component) candidate;
                if (awtComponent instanceof JComponent) {
                    return (JComponent) awtComponent;
                }
            }
        } catch (Throwable ignored) {
            return null;
        }
        return null;
    }

    private static boolean isHeadlessMode() {
        return "true".equalsIgnoreCase(System.getProperty("java.awt.headless", "false"));
    }

    private static BufferedImage cropToInkBounds(BufferedImage image, int padding) {
        int width = image.getWidth();
        int height = image.getHeight();
        int minX = width;
        int minY = height;
        int maxX = -1;
        int maxY = -1;
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                if (!isInkPixel(image.getRGB(x, y))) {
                    continue;
                }
                if (x < minX) {
                    minX = x;
                }
                if (x > maxX) {
                    maxX = x;
                }
                if (y < minY) {
                    minY = y;
                }
                if (y > maxY) {
                    maxY = y;
                }
            }
        }
        if (maxX < minX || maxY < minY) {
            return image;
        }
        minX = Math.max(0, minX - padding);
        minY = Math.max(0, minY - padding);
        maxX = Math.min(width - 1, maxX + padding);
        maxY = Math.min(height - 1, maxY + padding);
        int cropWidth = maxX - minX + 1;
        int cropHeight = maxY - minY + 1;
        if (cropWidth <= 0 || cropHeight <= 0 || (cropWidth == width && cropHeight == height)) {
            return image;
        }
        BufferedImage out = new BufferedImage(cropWidth, cropHeight, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = out.createGraphics();
        g.setColor(Color.WHITE);
        g.fillRect(0, 0, cropWidth, cropHeight);
        g.drawImage(image, 0, 0, cropWidth, cropHeight, minX, minY, maxX + 1, maxY + 1, null);
        g.dispose();
        return out;
    }

    private static boolean isInkPixel(int rgba) {
        int alpha = (rgba >>> 24) & 0xFF;
        if (alpha < 20) {
            return false;
        }
        int red = (rgba >>> 16) & 0xFF;
        int green = (rgba >>> 8) & 0xFF;
        int blue = rgba & 0xFF;
        return red < 210 || green < 210 || blue < 210;
    }

    private static boolean looksVisuallyEmpty(BufferedImage image) {
        int width = image.getWidth();
        int height = image.getHeight();
        if (width <= 0 || height <= 0) {
            return true;
        }

        // Ignore the ProM ScalableViewPanel toolbar chrome (PIP badge + vertical "Zoom" strip)
        // when assessing emptiness. Without this, a toolbar-only render slips through the
        // ratio check because the toolbar itself contributes enough dark pixels.
        int xStart = Math.min(40, Math.max(1, width / 10));
        int yStart = Math.min(80, Math.max(1, height / 10));

        long darkInterior = 0L;
        int minInkX = width;
        int minInkY = height;
        int maxInkX = -1;
        int maxInkY = -1;

        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                if (!isInkPixel(image.getRGB(x, y))) {
                    continue;
                }
                if (x < minInkX) minInkX = x;
                if (x > maxInkX) maxInkX = x;
                if (y < minInkY) minInkY = y;
                if (y > maxInkY) maxInkY = y;
                if (x >= xStart && y >= yStart) {
                    darkInterior++;
                }
            }
        }

        // No ink anywhere.
        if (maxInkX < 0 || maxInkY < 0) {
            return true;
        }

        // Ink-bounding-box lies entirely inside the toolbar corner — pure chrome, no graph.
        if (maxInkX < 200 && maxInkY < 100) {
            return true;
        }

        long interiorPixels = (long) Math.max(1, width - xStart) * (long) Math.max(1, height - yStart);
        double inkRatio = (double) darkInterior / (double) interiorPixels;
        return inkRatio < 0.005d;
    }

    private static String validateRenderedOutput(File outputFile, Dot2Image.Type outputType) {
        if (outputFile == null) {
            return "renderer produced no output file target";
        }
        if (!outputFile.exists() || !outputFile.isFile()) {
            return "renderer did not create output file";
        }
        if (outputFile.length() <= 0L) {
            return "renderer created empty output file";
        }
        if (Dot2Image.Type.png.equals(outputType)) {
            try {
                BufferedImage image = ImageIO.read(outputFile);
                if (image == null) {
                    return "renderer created unreadable PNG";
                }
                if (image.getWidth() <= 0 || image.getHeight() <= 0) {
                    return "renderer created PNG with invalid dimensions";
                }
            } catch (Throwable throwable) {
                return throwable.toString();
            }
        }
        return null;
    }

    private static String labelForNode(PetrinetNode node) {
        if (node instanceof Place) {
            return ((Place) node).getLabel();
        }
        if (node instanceof Transition) {
            return ((Transition) node).getLabel();
        }
        return node.toString();
    }

    private static List<String> transitionIds(Collection<Transition> transitions) {
        List<String> ids = new ArrayList<String>();
        if (transitions == null) {
            return ids;
        }
        for (Transition transition : transitions) {
            ids.add(id(transition.getId()));
        }
        return ids;
    }

    private static List<String> transitionLabels(Collection<Transition> transitions) {
        List<String> labels = new ArrayList<String>();
        if (transitions == null) {
            return labels;
        }
        for (Transition transition : transitions) {
            labels.add(transition.getLabel());
        }
        return labels;
    }

    private static String nonEmpty(String value, String fallbackPrefix) {
        if (value != null && value.trim().length() > 0) {
            return value;
        }
        return fallbackPrefix;
    }

    private static Map<String, Object> buildConnectionsJson(UIPluginContext context) {
        Map<String, Object> root = new LinkedHashMap<String, Object>();
        List<Object> layoutConnections = new ArrayList<Object>();
        List<Object> markingConnections = new ArrayList<Object>();
        List<Object> errors = new ArrayList<Object>();
        int totalConnections = 0;

        try {
            ConnectionManager manager = context.getConnectionManager();
            for (ConnectionID connectionID : manager.getConnectionIDs()) {
                totalConnections++;
                try {
                    Connection connection = manager.getConnection(connectionID);
                    if (connection == null) {
                        continue;
                    }
                    if (connection instanceof GraphLayoutConnection) {
                        layoutConnections.add(graphLayoutConnectionToJson((GraphLayoutConnection) connection));
                    } else if (connection instanceof InitialMarkingConnection) {
                        markingConnections.add(markingConnectionToJson(connection, "InitialMarkingConnection"));
                    } else if (connection instanceof FinalMarkingConnection) {
                        markingConnections.add(markingConnectionToJson(connection, "FinalMarkingConnection"));
                    }
                } catch (Throwable throwable) {
                    Map<String, Object> entry = new LinkedHashMap<String, Object>();
                    entry.put("connection_id", connectionID == null ? null : connectionID.toString());
                    entry.put("error", throwable.toString());
                    errors.add(entry);
                }
            }
        } catch (Throwable throwable) {
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            entry.put("connection_manager_error", throwable.toString());
            errors.add(entry);
        }

        root.put("total_connection_count", Integer.valueOf(totalConnections));
        root.put("layout_connection_count", Integer.valueOf(layoutConnections.size()));
        root.put("marking_connection_count", Integer.valueOf(markingConnections.size()));
        root.put("layout_connections", layoutConnections);
        root.put("marking_connections", markingConnections);
        root.put("errors", errors);
        return root;
    }

    private static Map<String, Object> graphLayoutConnectionToJson(GraphLayoutConnection connection) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("connection_class", connection.getClass().getSimpleName());
        out.put("connection_label", connection.getLabel());
        out.put("is_layed_out", Boolean.valueOf(connection.isLayedOut()));

        DirectedGraph<?, ?> graph = connection.getGraph();
        out.put("graph_class", graph == null ? null : graph.getClass().getName());
        out.put("graph_label", graph == null ? null : graph.getLabel());

        List<Object> nodes = new ArrayList<Object>();
        List<Object> edges = new ArrayList<Object>();
        if (graph != null) {
            for (DirectedGraphNode node : graph.getNodes()) {
                Map<String, Object> entry = new LinkedHashMap<String, Object>();
                entry.put("id", id(node.getId()));
                entry.put("label", node.getLabel());
                entry.put("class", node.getClass().getSimpleName());
                Point2D position = connection.getPosition(node);
                entry.put("x", position == null ? null : Double.valueOf(position.getX()));
                entry.put("y", position == null ? null : Double.valueOf(position.getY()));
                Dimension size = connection.getSize(node);
                entry.put("width", size == null ? null : Integer.valueOf(size.width));
                entry.put("height", size == null ? null : Integer.valueOf(size.height));
                Point2D portOffset = connection.getPortOffset(node);
                entry.put("port_offset_x", portOffset == null ? null : Double.valueOf(portOffset.getX()));
                entry.put("port_offset_y", portOffset == null ? null : Double.valueOf(portOffset.getY()));
                entry.put("collapsed", Boolean.valueOf(connection.isCollapsed(node)));
                nodes.add(entry);
            }
            for (DirectedGraphEdge<?, ?> edge : graph.getEdges()) {
                Map<String, Object> entry = new LinkedHashMap<String, Object>();
                entry.put("class", edge.getClass().getSimpleName());
                entry.put("label", edge.getLabel());
                entry.put("source_id", id(edge.getSource().getId()));
                entry.put("target_id", id(edge.getTarget().getId()));
                List<Object> points = new ArrayList<Object>();
                List<Point2D> edgePoints = connection.getEdgePoints(edge);
                if (edgePoints != null) {
                    for (Point2D point : edgePoints) {
                        Map<String, Object> p = new LinkedHashMap<String, Object>();
                        p.put("x", Double.valueOf(point.getX()));
                        p.put("y", Double.valueOf(point.getY()));
                        points.add(p);
                    }
                }
                entry.put("bend_points", points);
                edges.add(entry);
            }
        }
        out.put("node_count", Integer.valueOf(nodes.size()));
        out.put("edge_count", Integer.valueOf(edges.size()));
        out.put("nodes", nodes);
        out.put("edges", edges);
        return out;
    }

    private static Map<String, Object> markingConnectionToJson(Connection connection, String declaredType) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("connection_class", connection.getClass().getSimpleName());
        out.put("declared_type", declaredType);
        out.put("connection_label", connection.getLabel());

        Object netObj = roleObject(connection, "Net", "NET", "net");
        out.put("net_class", netObj == null ? null : netObj.getClass().getName());
        out.put("net_label", netObj instanceof DirectedGraph ? ((DirectedGraph<?, ?>) netObj).getLabel() : null);

        Object markingObj = roleObject(connection, "Marking", "MARKING", "marking");
        if (markingObj instanceof Marking) {
            Marking marking = (Marking) markingObj;
            List<Object> places = new ArrayList<Object>();
            for (Place place : marking) {
                Map<String, Object> placeEntry = new LinkedHashMap<String, Object>();
                placeEntry.put("place_id", id(place.getId()));
                placeEntry.put("place_label", place.getLabel());
                placeEntry.put("tokens", Integer.valueOf(marking.occurrences(place)));
                places.add(placeEntry);
            }
            out.put("marking_places", places);
            out.put("marking_place_count", Integer.valueOf(places.size()));
        } else {
            out.put("marking_places", new ArrayList<Object>());
            out.put("marking_place_count", Integer.valueOf(0));
        }
        return out;
    }

    private static Object roleObject(Connection connection, String... roles) {
        if (connection == null || roles == null) {
            return null;
        }
        for (String role : roles) {
            try {
                Object value = connection.getObjectWithRole(role);
                if (value != null) {
                    return value;
                }
            } catch (Throwable ignored) {
                // Try next role spelling.
            }
        }
        return null;
    }

    private static List<Object> classificationToJson(FusionMINERfulResult result) {
        List<Object> output = new ArrayList<Object>();
        if (result.getActivityClassification() == null) {
            return output;
        }
        for (Collection<Character> item : result.getActivityClassification()) {
            output.add(characterCollectionToNames(item, result));
        }
        return output;
    }

    private static List<Object> characterCollectionToNames(Collection<Character> chars, FusionMINERfulResult result) {
        List<Object> names = new ArrayList<Object>();
        if (chars == null) {
            return names;
        }
        for (Character ch : chars) {
            String label = result.getEventLog().getLabel(ch);
            names.add(label != null ? label : ch.toString());
        }
        return names;
    }

    private static List<Object> constraintsToJson(Collection<Constraint> constraints) {
        List<Object> output = new ArrayList<Object>();
        if (constraints == null) {
            return output;
        }
        for (Constraint constraint : constraints) {
            Map<String, Object> entry = new LinkedHashMap<String, Object>();
            entry.put("template", constraint.getTemplateName());
            entry.put("type", constraint.type);
            entry.put("support", Double.valueOf(constraint.getSupport()));
            entry.put("confidence", Double.valueOf(constraint.getConfidence()));
            entry.put("interest_factor", Double.valueOf(constraint.getInterestFactor()));
            List<Object> activities = new ArrayList<Object>();
            for (TaskCharSet parameter : constraint.getParameters()) {
                List<Object> grouped = new ArrayList<Object>();
                for (TaskChar taskChar : parameter.getTaskCharsList()) {
                    grouped.add(taskChar.getName());
                }
                if (grouped.size() == 1) {
                    activities.add(grouped.get(0));
                } else {
                    activities.add(grouped);
                }
            }
            entry.put("activities", activities);
            output.add(entry);
        }
        return output;
    }

    private static String id(NodeID id) {
        return id == null ? "unknown" : id.toString();
    }

    private static void writeJson(Path path, Object value) throws IOException {
        Files.createDirectories(path.getParent());
        try (BufferedWriter writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
            writer.write(toJson(value));
        }
    }

    private static String toJson(Object value) {
        if (value == null) {
            return "null";
        }
        if (value instanceof String) {
            return "\"" + escape((String) value) + "\"";
        }
        if (value instanceof Number || value instanceof Boolean) {
            return value.toString();
        }
        if (value instanceof Map<?, ?>) {
            StringBuilder builder = new StringBuilder();
            builder.append("{");
            boolean first = true;
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!first) {
                    builder.append(",");
                }
                first = false;
                builder.append(toJson(String.valueOf(entry.getKey())));
                builder.append(":");
                builder.append(toJson(entry.getValue()));
            }
            builder.append("}");
            return builder.toString();
        }
        if (value instanceof Collection<?>) {
            StringBuilder builder = new StringBuilder();
            builder.append("[");
            boolean first = true;
            for (Object item : (Collection<?>) value) {
                if (!first) {
                    builder.append(",");
                }
                first = false;
                builder.append(toJson(item));
            }
            builder.append("]");
            return builder.toString();
        }
        return toJson(String.valueOf(value));
    }

    private static String escape(String text) {
        return text
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
