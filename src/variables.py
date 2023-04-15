"""Variable Definitions

TODO: write description

"""

import sumolib
from collections import deque
import xml.etree.cElementTree as ET

from .utils import load_config, write_xml

# TODO: automatically determine the roads whose flow is known due to the detectors (qX variables)

def get_entry_exit_nodes(nodes):
    entry_nodes = []
    exit_nodes = []

    for node in nodes:
        if len(node.getIncoming()) == 0: # if it has no incoming edges, it is an entry node
            entry_nodes.append(node)
        elif len(node.getOutgoing()) == 0: # if it has no outgoing edges, it is an exit node
            exit_nodes.append(node)
    
    return entry_nodes, exit_nodes

def gen_pinpoint(edge, variable, color, additional_tag):
    # get the coordinates of the center of an edge: if its shape has only 2 tuples, the center is calculated directly by averaging the two points
    shape = edge.getShape()
    center = shape[int(len(shape) / 2)] if len(shape) != 2 else ((shape[0][0] + shape[1][0]) / 2, (shape[0][1] + shape[1][1]) / 2)

    ET.SubElement(additional_tag, 'poi', id=variable, color=color, layer='202.00', x=str(center[0]), y=str(center[1]), type='flow variable', name=edge.getID())

def calculate_intermediate_variables(network, process_list, variable_count, variables, additional_tag):
    while process_list:
        edge = process_list.popleft()

        merging_edges = edge.getToNode().getIncoming()
        following_edges = edge.getToNode().getOutgoing()

        if len(merging_edges) == 1 and len(following_edges) == 1: # case where the following edge is just a continuation of the previous edge
            if following_edges[0].getID() not in variables:
                variables[following_edges[0].getID()] = variables[edge.getID()]
                process_list.append(following_edges[0])

        elif len(merging_edges) > 1 and len(following_edges) == 1: # case of a merging junction, analyse if it can be processable            
            if following_edges[0].getID() in variables:
                continue
            
            processable = True
            for m_edge in merging_edges:
                if m_edge.getID() != edge.getID() and m_edge.getID() not in variables:
                    processable = False
                    break

            if processable:
                variable = f'x{variable_count}'
                variables[following_edges[0].getID()] = variable
                gen_pinpoint(following_edges[0], variable, 'cyan', additional_tag)

                variable_count += 1
                process_list.append(following_edges[0])

        elif len(merging_edges) == 1 and len(following_edges) > 1: # case of a splitting edge , assign new variables
            for f_edge in following_edges:
                if f_edge.getID() not in variables:
                    variable = f'x{variable_count}'
                    variables[f_edge.getID()] = variable
                    gen_pinpoint(f_edge, variable, 'cyan', additional_tag)

                    variable_count += 1
                    process_list.append(f_edge)

    for edge in network.getEdges():
        if edge.getID() not in variables:
            print(f"Edge {edge.getID()} has no variable assigned.")

    return variable_count

def gen_variables(network, entry_nodes, exit_nodes, network_file):
    additional_tag = ET.Element('additional')
    variable_count = 1
    variables = {} # edge : variable
    process_list = []

    for entry in entry_nodes:
        if len(entry.getOutgoing()) > 1:
            print(f"Entry node {entry.getID()} has more than one outgoing edge. Please adapt the network so that each entry node has only one outgoing edge.")
            continue
        
        edge_id = entry.getOutgoing()[0].getID()
        edge = network.getEdge(edge_id)

        variable = f'x{variable_count}'
        variables[edge_id] = variable
        gen_pinpoint(edge, variable, 'yellow', additional_tag)

        process_list.append(edge)
        variable_count += 1

    for exit in exit_nodes:
        if len(exit.getIncoming()) > 1:
            print(f"Exit node {exit.getID()} has more than one incoming edge. Please adapt the network so that each exit node has only one incoming edge.")
            continue
        
        edge_id = exit.getIncoming()[0].getID()
        edge = network.getEdge(edge_id)

        variable = f'x{variable_count}'
        variables[edge_id] = variable
        gen_pinpoint(edge, variable, '128,128,0', additional_tag)

        # define the variables of the edges that serve as a continuation of the exit edges
        previous_edges = list(edge.getIncoming().keys())
        while len(previous_edges) == 1:
            if len(list(previous_edges[0].getOutgoing().keys())) > 1:
                break
            variables[previous_edges[0].getID()] = variable
            previous_edges = list(previous_edges[0].getIncoming().keys())

        variable_count += 1
    
    process_list = deque(process_list)
    variable_count = calculate_intermediate_variables(network, process_list, variable_count, variables, additional_tag)
    
    write_xml(additional_tag, network_file.replace('.net', '_poi'))

    return variable_count

if __name__ == '__main__':
    config = load_config()
    # network_file = config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml')
    network_file = config.get('nodes', 'NODE_AREINHO', fallback='./nodes/no_areinho.net.xml')
    network = sumolib.net.readNet(network_file)

    entry_nodes, exit_nodes = get_entry_exit_nodes(network.getNodes())
    print(f"Found {len(entry_nodes)} entry nodes and {len(exit_nodes)} exit nodes.")
    print(f"Entry nodes: {[entry.getID() for entry in entry_nodes]}")
    print(f"Exit nodes: {[exit.getID() for exit in exit_nodes]}")

    variable_count = gen_variables(network, entry_nodes, exit_nodes, network_file)
    print(f"Generated {variable_count - 1} variables.")