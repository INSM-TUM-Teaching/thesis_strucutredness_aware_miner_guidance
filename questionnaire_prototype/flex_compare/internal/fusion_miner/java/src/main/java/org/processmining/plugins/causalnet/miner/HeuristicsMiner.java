package org.processmining.plugins.causalnet.miner;

import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map.Entry;
import java.util.TreeSet;

import org.processmining.framework.util.Pair;
import org.processmining.models.causalnet.CausalNetAnnotations;
import org.processmining.models.flexiblemodel.EndTaskNodesSet;
import org.processmining.models.flexiblemodel.Flex;
import org.processmining.models.flexiblemodel.FlexEdge;
import org.processmining.models.flexiblemodel.FlexFactory;
import org.processmining.models.flexiblemodel.FlexNode;
import org.processmining.models.flexiblemodel.SetFlex;
import org.processmining.models.flexiblemodel.StartTaskNodesSet;
import org.processmining.models.graphbased.AttributeMap;
import org.processmining.plugins.causalnet.miner.settings.FlexibleHeuristicsMinerSettings;
import org.processmining.plugins.causalnet.temp.Counter;
import org.processmining.plugins.causalnet.temp.cube.lattice.LatticeIterator;
import org.processmining.plugins.causalnet.temp.cube.lattice.LatticeValues;
import org.processmining.plugins.causalnet.temp.elements.Dimension;
import org.processmining.plugins.causalnet.temp.measures.EventDirectDependencyMeasure;
import org.processmining.plugins.causalnet.temp.measures.EventEnd;
import org.processmining.plugins.causalnet.temp.measures.EventEntry;
import org.processmining.plugins.causalnet.temp.measures.EventLenghtTwoDependencyMeasure;
import org.processmining.plugins.causalnet.temp.measures.EventLongDistanceDependencyMeasure;
import org.processmining.plugins.causalnet.temp.measures.EventStart;



public class HeuristicsMiner {

	public static Object[] buildACNet(String logID, LatticeValues values, FlexibleHeuristicsMinerSettings settings){
		
		final Flex flexDiagram = FlexFactory.newFlex("aC-Net of "+logID);
		
		HashMap<String, EntryDG> dg = 
			buildDependencyGraph(values, settings);
		
		HashMap<String, EntrySJ<Integer[]>> patterns =
			computeSplitsJoins(dg, values);
		
		HashMap<String, EntrySJ<Counter>> frequencies =
			computeSplitsJoinsFrequencies(dg, patterns);	
		
		HashMap<String, EntryDG> longDistanceDependencies = null;
		if(settings.isUseLongDistanceDependency())
			longDistanceDependencies = computeLongDistanceDependencies(dg, frequencies, values, settings);
				
		// CREATE C-NET OBJECTS
		
		CausalNetAnnotations annotations = new CausalNetAnnotations();
		
		annotations.addExecutionInfo(CausalNetAnnotations.parameters, settings);
		
		HashMap<String, FlexNode> map = new HashMap<String, FlexNode>();
		for(java.util.Map.Entry<String, EntryDG> entry : dg.entrySet()){
			
			FlexNode node = flexDiagram.addNode(entry.getKey());
			map.put(entry.getKey(), node);
			
			annotations.addNodeInfo(node, CausalNetAnnotations.id, entry.getValue().getID());
			annotations.addNodeInfo(node, CausalNetAnnotations.counterTask, new Integer(entry.getValue().getFrequency()));
			annotations.addNodeInfo(node, CausalNetAnnotations.relations, entry.getValue());
		}
		
		for(java.util.Map.Entry<String, EntrySJ<Counter>> entry : frequencies.entrySet()){

			EntryDG eventEntry = dg.get(entry.getKey());
			EntryDG entryLDD = null;
			
			FlexNode node = map.get(entry.getKey());
			
			annotations.addNodeInfo(node, CausalNetAnnotations.splitJoinPatterns, entry.getValue());
			
			if(settings.isUseLongDistanceDependency()){
				
				entryLDD = longDistanceDependencies.get(entry.getKey());
				annotations.addNodeInfo(node, CausalNetAnnotations.longDistanceRelations, entryLDD);
				
				for(String dependency : entryLDD.getOutputs())
					flexDiagram.addArc(node, map.get(dependency));
			}
			
			ArrayList<Pair<String, FlexNode>> inputNodes = new ArrayList<Pair<String, FlexNode>>(eventEntry.inputsSize()); 
			for(String input : eventEntry.getInputs()){
				
				inputNodes.add(new Pair<String, FlexNode>(input, map.get(input)));
			}
			
			ArrayList<Pair<String, FlexNode>> outputNodes = new ArrayList<Pair<String, FlexNode>>(eventEntry.outputsSize()); 
			for(String output : eventEntry.getOutputs()){
				
				flexDiagram.addArc(node, map.get(output));
				outputNodes.add(new Pair<String, FlexNode>(output, map.get(output)));
			}
			
				
			if(eventEntry.inputsSize() > 0){
				
				for(String code : entry.getValue().getJoins().keySet()){
					
					SetFlex temp = new SetFlex();
					for(int i = 0; i < code.length(); i++){
						
						if(code.charAt(i) == '1'){
							
							Pair<String, FlexNode> input = inputNodes.get(i);
							temp.add(input.getSecond());
							
							if(entryLDD == null) continue;
							
							for(String dependency : entryLDD.getInputs()) temp.add(map.get(dependency));
						}
					}
					node.addInputNodes(temp);
				}
			}
			else node.addInputNodes(new SetFlex());

			if(eventEntry.outputsSize() > 0){
				
				for(String code : entry.getValue().getSplits().keySet()){
					
					SetFlex temp = new SetFlex();
					for(int i = 0; i < code.length(); i++){
						
						if(code.charAt(i) == '1'){
							
							Pair<String, FlexNode> output = outputNodes.get(i);
							temp.add(output.getSecond());
							
							if(entryLDD == null) continue;
							
							for(String dependency : entryLDD.getOutputs()) temp.add(map.get(dependency));
						}
					}
					node.addOutputNodes(temp);
				}
			}
			else node.addOutputNodes(new SetFlex());
		}
		
		// ANNOTATE EDGES
		
		for(FlexEdge<? extends FlexNode, ? extends FlexNode> edge : flexDiagram.getEdges()){
			
			FlexNode source = edge.getSource();
			FlexNode target = edge.getTarget();
			
			EntryDG entryDG = dg.get(source.getLabel());
			
			if(entryDG.containsOutput(target.getLabel())){
				
				annotations.addEdgeInfo(edge, CausalNetAnnotations.directDependency, entryDG.getOutputInfo(target.getLabel()));
				edge.getAttributeMap().put(AttributeMap.SHOWLABEL, true);
				edge.getAttributeMap().put(AttributeMap.LABEL, String.valueOf(entryDG.getOutputInfo(target.getLabel())));
			}
			else{
				
				if(!settings.isUseLongDistanceDependency()) continue;
				
				EntryDG entryLDD = longDistanceDependencies.get(source.getLabel());
				
				if(entryLDD.containsOutput(target.getLabel()))
					annotations.addEdgeInfo(edge, CausalNetAnnotations.longDistanceDependency, entryLDD.getOutputInfo(target.getLabel()));
					edge.getAttributeMap().put(AttributeMap.SHOWLABEL, true);
					edge.getAttributeMap().put(AttributeMap.LABEL, String.valueOf(entryLDD.getOutputInfo(target.getLabel())));
			}
		}
		
		// SET START AND END TASKS
		
		StartTaskNodesSet startTaskNodes = new StartTaskNodesSet();
		EndTaskNodesSet endTaskNodes = new EndTaskNodesSet();
		
		HashMap<FlexNode, Integer> stackStartTasks = new HashMap<FlexNode, Integer>();
		HashMap<FlexNode, Integer> stackEndTasks = new HashMap<FlexNode, Integer>();
		
		LatticeIterator it = new LatticeIterator(values);
		while(it.hasNext()){
			
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();
			
			@SuppressWarnings("unchecked")
			Collection<Pair<Integer, Integer>> startTids = (Collection<Pair<Integer, Integer>>) pair.getSecond().get(EventStart.DESIGNATION);
		
			@SuppressWarnings("unchecked")
			Collection<Pair<Integer, Integer>> endTids = (Collection<Pair<Integer, Integer>>) pair.getSecond().get(EventEnd.DESIGNATION);
		
			if((startTids == null) && (endTids == null)) continue;
			
			StringBuffer eventID = new StringBuffer();
			boolean flag = true;
			for(Pair<String,String> id : pair.getFirst()){
				
				if(flag){
					eventID.append(id.getSecond());
					flag = false;
				}
				else eventID.append(":"+id.getSecond());
			}
			
			FlexNode node = map.get(eventID.toString());
			
			if(startTids != null){
				
				annotations.addNodeInfo(node, CausalNetAnnotations.counterStartTask, new Integer(startTids.size()));
				
				if(!startTids.isEmpty()) stackStartTasks.put(node, new Integer(startTids.size()));
			}
			if(endTids != null){
				
				annotations.addNodeInfo(node, CausalNetAnnotations.counterEndTask, new Integer(endTids.size()));
				
				if(!endTids.isEmpty()) stackEndTasks.put(node, new Integer(endTids.size()));
			}
		}
		
		
		if(settings.isUseUniqueStartEndTasks()){
						
			FlexNode artificialStartTask = flexDiagram.addNode("START");

			ArrayList<Pair<String,String>> id = new ArrayList<Pair<String,String>>(1);
			id.add(new Pair<String,String>(null, "START"));
			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.id, id);

			EntryDG artificialRelations = new EntryDG(id);
			EntrySJ<Integer> artificialPatterns = new EntrySJ<Integer>(id);
			
			int support = 0;
			int index = 0;
			for(java.util.Map.Entry<FlexNode, Integer> entry : stackStartTasks.entrySet()){

				String outputTask = entry.getKey().getLabel();

				SetFlex tempOUT = new SetFlex();
				tempOUT.add(entry.getKey());
				artificialStartTask.addInputNodes(new SetFlex());
				artificialStartTask.addOutputNodes(tempOUT);

				SetFlex tempIN = new SetFlex();
				entry.getKey().removeInputNodes(tempIN);
				tempIN.add(artificialStartTask);
				entry.getKey().addInputNodes(tempIN);

				flexDiagram.addArc(artificialStartTask, entry.getKey());

				artificialRelations.addOutput(outputTask, null);
				
				StringBuffer patternCode = new StringBuffer();
				for(int i = 0; i < stackStartTasks.size(); i++){
					
					if(i == index) patternCode.append("1");
					else patternCode.append("0");
				}
				artificialPatterns.addSplit(patternCode.toString(), entry.getValue());
				
				((EntryDG) annotations.getNodeInfo(entry.getKey(), CausalNetAnnotations.relations)).addInput("START", null);
				@SuppressWarnings("unchecked")
				EntrySJ<Integer> patternsOutput = (EntrySJ<Integer>) annotations.getNodeInfo(entry.getKey(), CausalNetAnnotations.splitJoinPatterns);
				patternsOutput.removeJoin("");
				patternsOutput.addJoin("1", entry.getValue());
				
				
				annotations.addNodeInfo(entry.getKey(), CausalNetAnnotations.counterStartTask, new Integer(0));
				support += entry.getValue();
			}

			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.relations, artificialRelations);
			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.splitJoinPatterns, artificialPatterns);
			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.counterTask, new Integer(support));
			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.counterStartTask, new Integer(support));
			annotations.addNodeInfo(artificialStartTask, CausalNetAnnotations.counterEndTask, new Integer(0));
			artificialStartTask.commitUpdates();
			
			SetFlex temp = new SetFlex();
			temp.add(artificialStartTask);
			startTaskNodes.add(temp);

			// ------------

			FlexNode artificialEndTask = flexDiagram.addNode("END");

			id = new ArrayList<Pair<String,String>>(1);
			id.add(new Pair<String,String>(null, "END"));
			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.id, id);

			artificialRelations = new EntryDG(id);
			artificialPatterns = new EntrySJ<Integer>(id);

			support = 0;
			index = 0;
			for(java.util.Map.Entry<FlexNode, Integer> entry : stackEndTasks.entrySet()){

				String inputTask = entry.getKey().getLabel();

				SetFlex tempIN = new SetFlex();
				tempIN.add(entry.getKey());
				artificialEndTask.addInputNodes(tempIN);
				artificialEndTask.addOutputNodes(new SetFlex());

				SetFlex tempOUT = new SetFlex();
				entry.getKey().removeOutputNodes(tempOUT);
				tempOUT.add(artificialEndTask);
				entry.getKey().addOutputNodes(tempOUT);

				flexDiagram.addArc(entry.getKey(), artificialEndTask);

				artificialRelations.addInput(inputTask, null);
				
				StringBuffer patternCode = new StringBuffer();
				for(int i = 0; i < stackEndTasks.size(); i++){
					
					if(i == index) patternCode.append("1");
					else patternCode.append("0");
				}
				artificialPatterns.addJoin(patternCode.toString(), entry.getValue());
				
				((EntryDG) annotations.getNodeInfo(entry.getKey(), CausalNetAnnotations.relations)).addOutput("END", null);
				@SuppressWarnings("unchecked")
				EntrySJ<Integer> patternsInput = (EntrySJ<Integer>) annotations.getNodeInfo(entry.getKey(), CausalNetAnnotations.splitJoinPatterns);
				patternsInput.removeSplit("");
				patternsInput.addSplit("1", entry.getValue());
				
				annotations.addNodeInfo(entry.getKey(), CausalNetAnnotations.counterEndTask, new Integer(0));
				support += entry.getValue();
			}

			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.relations, artificialRelations);
			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.splitJoinPatterns, artificialPatterns);
			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.counterTask, new Integer(support));
			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.counterStartTask, new Integer(0));
			annotations.addNodeInfo(artificialEndTask, CausalNetAnnotations.counterEndTask, new Integer(support));
			artificialEndTask.commitUpdates();
			
			temp = new SetFlex();
			temp.add(artificialEndTask);
			endTaskNodes.add(temp);
		}
		else{
			
			for(java.util.Map.Entry<FlexNode, Integer> entry : stackStartTasks.entrySet()){
				
				SetFlex temp = new SetFlex();
				temp.add(entry.getKey());
				startTaskNodes.add(temp);
			}
			
			for(java.util.Map.Entry<FlexNode, Integer> entry : stackEndTasks.entrySet()){
				
				SetFlex temp = new SetFlex();
				temp.add(entry.getKey());
				endTaskNodes.add(temp);
			}
		}
		
		for(FlexNode node : map.values()) node.commitUpdates();
		
		return new Object[]{ flexDiagram, startTaskNodes, endTaskNodes, annotations };
	}
	
	protected static HashMap<String, EntryDG> buildDependencyGraph(LatticeValues values, FlexibleHeuristicsMinerSettings settings){
		
		HashMap<String, EntryDG> relations = new HashMap<String, EntryDG>();
		
		// STEP 1 AND 2
		HashMap<ArrayList<Pair<String, String>>, String> occurrences = new HashMap<ArrayList<Pair<String, String>>, String>();
		
		LatticeIterator it = new LatticeIterator(values);
		while(it.hasNext()){
		
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();
			
			@SuppressWarnings("unchecked")
			Collection<Pair<Integer, Integer>> tids = 
				(Collection<Pair<Integer, Integer>>) pair.getSecond().get(EventEntry.DESIGNATION);
			
			EntryDG entry = new EntryDG(pair.getFirst(), tids.size());
			
			if(tids.isEmpty()) continue;
						
			String event = entry.getKey();
			
			occurrences.put(pair.getFirst(), entry.getKey());
			
			@SuppressWarnings("unchecked")
			AbstractMap<String, Float> dependencies = 
				(AbstractMap<String, Float>) pair.getSecond().get(EventDirectDependencyMeasure.DESIGNATION);
			
			relations.put(event, entry);
			
			if(dependencies.containsKey(event))
				entry.addL1Ldependency(dependencies.get(event), settings.getL1lThreshold());
		}
		
		// STEP 3
		it = new LatticeIterator(values);
		while(it.hasNext()){
			
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();

			if(!occurrences.containsKey(pair.getFirst())) continue;
			
			String event = occurrences.get(pair.getFirst());
			EntryDG eventEntry = relations.get(event);
			
			@SuppressWarnings("unchecked")
			AbstractMap<String, Float> dependencies = 
				(AbstractMap<String, Float>) pair.getSecond().get(EventLenghtTwoDependencyMeasure.DESIGNATION);
	
			eventEntry.addL2Ldependencies(dependencies, settings.getL2lThreshold(), relations);
		}
		
		//STEP 4
		it = new LatticeIterator(values);
		while(it.hasNext()){
			
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();
			
			if(!occurrences.containsKey(pair.getFirst())) continue;
			
			String event = occurrences.get(pair.getFirst());			
			EntryDG eventEntry = relations.get(event);
			
			@SuppressWarnings("unchecked")
			AbstractMap<String, Float> measures = 
				(AbstractMap<String, Float>) pair.getSecond().get(EventDirectDependencyMeasure.DESIGNATION);
			
			eventEntry.addDirectDependencies(measures);
			
		}
		
		// STEPS 5-9
		
		if(settings.isUseAllConnectedHeuristics()){
			
			for(EntryDG relation : relations.values())
				relation.computeStrongestDependencies(relations);
			
			for(EntryDG relation : relations.values())
				relation.removeWeakDependencies(relations, settings.getL2lThreshold(), settings.getDependencyThreshold(), settings.getRelativeToBestThreshold());
		}
		
		// STEPS 10-11
		for(EntryDG relation : relations.values()){
			relation.computeDependencies(relations, settings.getDependencyThreshold(), settings.getRelativeToBestThreshold());
			
			if(settings.isUseAllConnectedHeuristics())
				relation.checkUnconnectedTasks(relations);
		}
		
		// STEP 12 is implicit in the previous steps
			
		return relations;
	}
	

	protected static HashMap<String, EntrySJ<Integer[]>> computeSplitsJoins(HashMap<String, EntryDG> dependencyGraph, LatticeValues values){
		
		HashMap<String, HashMap<String, TreeSet<Integer>>> map = new HashMap<String, HashMap<String, TreeSet<Integer>>>();
		HashMap<String, EntrySJ<Integer[]>> patterns = new HashMap<String, EntrySJ<Integer[]>>();
		
		LatticeIterator it = new LatticeIterator(values);
		while(it.hasNext()){
			
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();
			
			@SuppressWarnings("unchecked")
			Collection<Pair<Integer, Integer>> tids = (Collection<Pair<Integer, Integer>>) pair.getSecond().get(EventEntry.DESIGNATION);
			
			if(tids.isEmpty()) continue;
			
			EntrySJ<Integer[]> eventEntry = new EntrySJ<Integer[]>(pair.getFirst());
			String event = eventEntry.getKey();
			
			if(!dependencyGraph.containsKey(event)) continue; // FOR THE FILTERED CASES
			
			HashMap<String, TreeSet<Integer>> stackMap = new HashMap<String, TreeSet<Integer>>(); // WHERE EVENTS APPEAR (TRACE ID,[EVENT ID])
			for(Pair<Integer, Integer> tid : tids){
				
				String traceID = tid.getFirst().toString();
//				String tidID = traceID + ":" + tid.getSecond().toString();
				
				if(stackMap.containsKey(traceID)){
					
					TreeSet<Integer> temp = stackMap.get(traceID);
					temp.add(tid.getSecond());
				}
				else{
					
					TreeSet<Integer> temp = new TreeSet<Integer>();
					temp.add(tid.getSecond());
					stackMap.put(traceID, temp);
				}
			}
			map.put(event, stackMap);
			patterns.put(event, eventEntry);
//			System.out.println(event+"\t"+stackMap.toString());
		}
		
		for(Entry<String, HashMap<String, TreeSet<Integer>>> entry : map.entrySet()){
			
			String event = entry.getKey(); 

			EntrySJ<Integer[]> eventPEntry = patterns.get(event);
			EntryDG eventEntry = dependencyGraph.get(event);
			
			HashMap<String, TreeSet<Integer>> tids = map.get(event);
			ArrayList<HashMap<String, TreeSet<Integer>>> inputsTids = new ArrayList<HashMap<String, TreeSet<Integer>>>(eventEntry.inputsSize());
			ArrayList<ArrayList<HashMap<String, TreeSet<Integer>>>> inputsOutputsTids = new ArrayList<ArrayList<HashMap<String, TreeSet<Integer>>>>(eventEntry.inputsSize());
			ArrayList<HashMap<String, TreeSet<Integer>>> outputsTids = new ArrayList<HashMap<String, TreeSet<Integer>>>(eventEntry.outputsSize());
			ArrayList<ArrayList<HashMap<String, TreeSet<Integer>>>> outputsInputsTids = new ArrayList<ArrayList<HashMap<String, TreeSet<Integer>>>>(eventEntry.outputsSize());
			
			for(String input : eventEntry.getInputs()){
				
				inputsTids.add(map.get(input));
				
				EntryDG inputEntry = dependencyGraph.get(input);
				
				ArrayList<HashMap<String, TreeSet<Integer>>> temp = new ArrayList<HashMap<String, TreeSet<Integer>>>(inputEntry.outputsSize());
				for(String inputOutput : inputEntry.getOutputs()){
					
					temp.add(map.get(inputOutput));
				}
				inputsOutputsTids.add(temp);
			}
			for(String output : eventEntry.getOutputs()){
				
				outputsTids.add(map.get(output));
				
				EntryDG outputEntry = dependencyGraph.get(output);
				
				ArrayList<HashMap<String, TreeSet<Integer>>> temp = new ArrayList<HashMap<String, TreeSet<Integer>>>(outputEntry.inputsSize());
				for(String outputInput : outputEntry.getInputs()){
					
					temp.add(map.get(outputInput));
				}
				outputsInputsTids.add(temp);
			}
			
//			if(event.equals("H")){
//				System.out.println(event);
//				System.out.println();
//				System.out.println(inputsTids);
//				System.out.println(inputsOutputsTids);
//				System.out.println();
//				System.out.println(outputsTids);
//				System.out.println(outputsInputsTids);
//			}
			
			for(java.util.Map.Entry<String, TreeSet<Integer>> tid : tids.entrySet()){
				
				String traceID = tid.getKey();
				
				for(Integer eventTid : tid.getValue()){
					
					String relationKey = traceID + ":" + eventTid;
					
					Integer[] joinIndices = new Integer[eventEntry.inputsSize()];
					Integer[] splitIndices = new Integer[eventEntry.outputsSize()];
					
					int index = 0;
					int nonNullInputIndices = 0;
					for(HashMap<String, TreeSet<Integer>> inputTids : inputsTids){
						
						if(inputTids.containsKey(traceID)){
						
							joinIndices[index] =  inputTids.get(traceID).floor(eventTid - 1);
							if(joinIndices[index] != null) nonNullInputIndices++;
						}
						index ++;
					}
					index = 0;
					int nonNullOutputIndices = 0;
					for(HashMap<String, TreeSet<Integer>> outputTids : outputsTids){
						
						if(outputTids.containsKey(traceID)){
							
							splitIndices[index] = outputTids.get(traceID).ceiling(eventTid + 1);
							if(splitIndices[index] != null) nonNullOutputIndices++;
						}
						index ++;
					}
					
//					if((event.equals("H")) && relationKey.startsWith("339:")){
//						
//						for(int i =  0; i < outputIndex; i++) System.out.print(splitIndices[i]+"\t");
//						System.out.println();
//					}
					
					if(nonNullInputIndices > 1){
						
						for(int i = 0; i < joinIndices.length; i++){
													
							if(joinIndices[i] == null) continue;
							if((eventTid - joinIndices[i]) == 1) continue;
						
							for(HashMap<String, TreeSet<Integer>> tempTids : inputsOutputsTids.get(i)){

								if(!tempTids.containsKey(traceID)) continue;

								Integer tempIndex = tempTids.get(traceID).ceiling(joinIndices[i] + 1);

								if(tempIndex == null) continue;

								if(tempIndex.intValue() < eventTid.intValue()){

									joinIndices[i] = null;
									break;
								}
							}
						}
					}
					
					if(nonNullOutputIndices > 1){
						
						for(int i = 0; i < splitIndices.length; i++){
							
							if(splitIndices[i] == null) continue;
							if((splitIndices[i] - eventTid) == 1) continue;
							
							for(HashMap<String, TreeSet<Integer>> tempTids : outputsInputsTids.get(i)){

								if(!tempTids.containsKey(traceID)) continue;

								Integer tempIndex = tempTids.get(traceID).floor(splitIndices[i] - 1);

								if(tempIndex == null) continue;
								
								if(tempIndex.intValue() > eventTid.intValue()){

									splitIndices[i] = null;
									break;
								}
							}
						}
					}
					
					eventPEntry.addJoin(relationKey, joinIndices);
					eventPEntry.addSplit(relationKey, splitIndices);
					
//					if((event.equals("D")) && relationKey.startsWith("18:")){
//						for(int i = 0; i < joinIndices.length; i++) System.out.print(joinIndices[i]+"\t");
//						System.out.print(" > "+relationKey+" > ");
//						for(int i = 0; i < splitIndices.length; i++) System.out.print(splitIndices[i]+"\t");
//						System.out.println();
//					}
				}
			}
		}
		
		// ASSURING RESULTS CONSISTENCY
		
		HashMap<String,Pair<HashMap<String,Integer>, HashMap<String,Integer>>> index =
				new HashMap<String,Pair<HashMap<String,Integer>, HashMap<String,Integer>>>();
		for(java.util.Map.Entry<String, EntryDG> event : dependencyGraph.entrySet()){
			
			HashMap<String,Integer> inputs = new HashMap<String,Integer>();
			int i = 0;
			for(String input : event.getValue().getInputs()){
				
				inputs.put(input, new Integer(i));
				i++;
			}
			
			HashMap<String,Integer> outputs = new HashMap<String,Integer>();
			i = 0;
			for(String output : event.getValue().getOutputs()){
				
				outputs.put(output, new Integer(i));
				i++;
			}
			
			index.put(event.getKey(), new Pair<HashMap<String,Integer>, HashMap<String,Integer>>(inputs,outputs));
		}
//		System.out.println(index);
			
		for(java.util.Map.Entry<String, EntrySJ<Integer[]>> event : patterns.entrySet()){
			
			EntrySJ<Integer[]> eventSJ = event.getValue();
			
			Object[] eventInputs = index.get(event.getKey()).getFirst().keySet().toArray();
			Object[] eventOutputs = index.get(event.getKey()).getSecond().keySet().toArray();
			
//			System.out.println(event.getKey());
//			System.out.println("Inputs: ");
//			for(int i = 0; i < eventInputs.length; i++) System.out.print(eventInputs[i]+"  ");
//			System.out.println("\nOutputs: ");
//			for(int i = 0; i < eventOutputs.length; i++) System.out.print(eventOutputs[i]+"  ");
//			System.out.println();
			
//			System.out.println("JOINS");
				for(java.util.Map.Entry<String, Integer[]> join : eventSJ.getJoins().entrySet()){
				
				String traceID = join.getKey().substring(0, join.getKey().indexOf(":") + 1);
				int eventID = Integer.valueOf(join.getKey().substring(join.getKey().indexOf(":") + 1));
				Integer[] joinIndices = join.getValue();
				
					for(int i = 0; i < joinIndices.length; i++){
						
						if(joinIndices[i] != null){
							
							EntrySJ<Integer[]> inputEvent = patterns.get((String) eventInputs[i]);
							if(inputEvent == null){
								continue;
							}
							Integer[] inputSplitIndices = inputEvent.getSplits().get(traceID+joinIndices[i]);
							if(inputSplitIndices == null){
								continue;
							}
							Integer outputIndex = index.get((String) eventInputs[i]).getSecond().get(event.getKey());
							if(outputIndex == null){
								continue;
							}
							if(outputIndex.intValue() < 0 || outputIndex.intValue() >= inputSplitIndices.length){
								continue;
							}
							inputSplitIndices[outputIndex.intValue()] = eventID;						
						}
					}

//				System.out.print(join.getKey()+": ");
//				for(int i = 0; i < join.getValue().length; i++) System.out.print(join.getValue()[i]+"  ");
//				System.out.println();
			}
			
//			System.out.println("SPLITS");
			for(java.util.Map.Entry<String, Integer[]> split : eventSJ.getSplits().entrySet()){
				
				String traceID = split.getKey().substring(0, split.getKey().indexOf(":") + 1);
				int eventID = Integer.valueOf(split.getKey().substring(split.getKey().indexOf(":") + 1));
				Integer[] splitIndices = split.getValue();
				
					for(int i = 0; i < splitIndices.length; i++){
						
						if(splitIndices[i] != null){
							
							EntrySJ<Integer[]> outputEvent = patterns.get((String) eventOutputs[i]);
							if(outputEvent == null){
								continue;
							}
							Integer[] inputJoinIndices = outputEvent.getJoins().get(traceID+splitIndices[i]);
							if(inputJoinIndices == null){
								continue;
							}
							Integer inputIndex = index.get((String) eventOutputs[i]).getFirst().get(event.getKey());
							if(inputIndex == null){
								continue;
							}
							if(inputIndex.intValue() < 0 || inputIndex.intValue() >= inputJoinIndices.length){
								continue;
							}
							inputJoinIndices[inputIndex.intValue()] = eventID;
						}
					}
				
//				System.out.print(split.getKey()+": ");
//				for(int i = 0; i < split.getValue().length; i++) System.out.print(split.getValue()[i]+"  ");
//				System.out.println();
			}
//			System.out.println();
		}
		
		return patterns;
	}
	
	
	protected static HashMap<String, EntryDG> computeLongDistanceDependencies(HashMap<String, EntryDG> dg, HashMap<String, EntrySJ<Counter>> sj, LatticeValues values, FlexibleHeuristicsMinerSettings settings){
		
		HashMap<String, EntryDG> longDistanceDependencies = new HashMap<String, EntryDG>();
		
		for(EntryDG event : dg.values()){
			
			longDistanceDependencies.put(event.getKey(), new EntryDG(event.getID()));
		}
		
		LatticeIterator it = new LatticeIterator(values);
		while(it.hasNext()){
			
			Pair<ArrayList<Pair<String, String>>, HashMap<String, Object>> pair = it.next();
			
			StringBuffer buffer = new StringBuffer();
			boolean flag = true;
			for(Pair<String,String> dimValue : pair.getFirst()){
				
				if(flag){
					
					buffer.append(dimValue.getSecond());
					flag = false;
				}
				else buffer.append(":"+dimValue.getSecond());
			}
			String event = buffer.toString();
			
			EntryDG entryDG = dg.get(event);
			EntryDG entryLDD = longDistanceDependencies.get(event);
			
			@SuppressWarnings("unchecked")
			AbstractMap<String, Float> measures = (AbstractMap<String, Float>) pair.getSecond().get(EventLongDistanceDependencyMeasure.DESIGNATION);
			
			for(java.util.Map.Entry<String, Float> entry : measures.entrySet()){
				
				if(entry.getValue() < settings.getLongDistanceThreshold()) continue;
				
				if(entryDG.containsOutput(entry.getKey())) continue;
				
				HashSet<String> visitedEvents = new HashSet<String>();
				visitedEvents.add(entry.getKey());

				if(!escapeToEnd(dg, sj, event, visitedEvents)) continue;
				
				entryLDD.addOutput(entry.getKey(), entry.getValue());
				
				EntryDG temp = longDistanceDependencies.get(entry.getKey());
				temp.addInput(event, entry.getValue());
			}
		}
		
		return longDistanceDependencies;
	}
	
	private static boolean escapeToEnd(HashMap<String, EntryDG> dg, HashMap<String, EntrySJ<Counter>> sj, String event, HashSet<String> visitedEvents){
		
		boolean result = false;
		
		visitedEvents.add(event);
		
		EntryDG entryDG = dg.get(event);
		EntrySJ<Counter> entrySJ = sj.get(event);
		
		String[] outputs = new String[entryDG.outputsSize()];
		int index = 0;
		for(String output : entryDG.getOutputs()){
			
			outputs[index] = output;
			index++;
		}
		
//		System.out.println(event+"\t"+visitedEvents.toString());
//		System.out.println(entrySJ.getSplits());
		
		if(outputs.length == 0) result = true;
		else{
			
			for(String pattern : entrySJ.getSplits().keySet()){
				
				boolean patternResult = true;
				boolean validPattern = false;
				for(int i = 0; i < pattern.length(); i++){
					
					if(pattern.charAt(i) == '1'){
						
						validPattern = true;
						
						String output = String.valueOf(outputs[i]);
						
						if(visitedEvents.contains(output)) patternResult = false;
						else{
							
							patternResult &= escapeToEnd(dg, sj, output, visitedEvents);
						}
						
						if(!patternResult) break;
					}
				}
				if(validPattern) result |= patternResult;
				
				if(result) break;
			}
		}
		
//		System.out.println(result+"\t"+event+"\t"+visitedEvents.toString());
		
		return result;
	}

		
	public static Pair<List<Pair<String, String>>, String> split(List<Pair<String, String>> values, List<Dimension> constraints){
		
		ArrayList<Pair<String, String>> nodeValue = new ArrayList<Pair<String, String>>(constraints.size());
		StringBuffer arcValue = new StringBuffer();
		
		int index = 0;
		for(Dimension dim : constraints){
			
			if(dim == null) nodeValue.add(values.get(index));
			else{
				
				if(arcValue.length() > 0) arcValue.append(":"+values.get(index).getSecond());
				else arcValue.append(values.get(index).getSecond());
			}
			
			index++;
		}
		nodeValue.trimToSize();
		arcValue.trimToSize();
		
//		System.out.println(nodeValue.toString()+"\t"+arcValue.toString());
		return new Pair<List<Pair<String, String>>, String>(nodeValue, arcValue.toString());
	}
	
	protected static HashMap<String, EntrySJ<Counter>> computeSplitsJoinsFrequencies(HashMap<String, EntryDG> dg, HashMap<String, EntrySJ<Integer[]>> sj){
		
		HashMap<String, EntrySJ<Counter>> frequencies = new HashMap<String, EntrySJ<Counter>>();
		for(java.util.Map.Entry<String, EntrySJ<Integer[]>> entry : sj.entrySet()){
			
			EntryDG eventEntry = dg.get(entry.getKey());
			
			HashMap<String, Counter> joinsCount = count(entry.getValue().getJoins());
			HashMap<String, Counter> splitsCount = count(entry.getValue().getSplits());
			
			frequencies.put(entry.getKey(), new EntrySJ<Counter>(eventEntry.getID(), joinsCount, splitsCount));
		}
		
		return frequencies;
	}
	
	protected static HashMap<String, Counter> count(HashMap<String, Integer[]> patterns){
		
		HashMap<String, Counter> stack = new HashMap<String, Counter>();
		for(Integer[] input : patterns.values()){
			
			StringBuffer code = new StringBuffer();
			for(int i = 0; i < input.length; i++){
				
				if(input[i] == null) code.append("0");
				else code.append("1");
			}
			
			if(stack.containsKey(code.toString())) stack.get(code.toString()).increment();
			else stack.put(code.toString(), new Counter(1));
		}
		
		return stack;
	}
		
}
