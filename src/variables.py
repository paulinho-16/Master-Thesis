"""Variable Definitions and Equation Systems Generation

This script creates the flow variables of the network and generates the corresponding POIs.
It deduces the equation systems for the VCI nodes, generating the file `equations.md` in the `nodes` folder.
It also generates the POIs for the routers of the network.

"""

import re
import sympy
import sumolib
import collections
import xml.etree.cElementTree as ET
from shapely.geometry import LineString

from .utils import load_config, remove_chars, write_xml

def get_entry_exit_nodes(nodes):
    entry_nodes = []
    exit_nodes = []

    for node in nodes:
        incoming_edges = node.getIncoming()
        outgoing_edges = node.getOutgoing()

        if len(incoming_edges) == 0: # if it has no incoming edges, it is an entry node
            entry_nodes.append(node)
        elif len(outgoing_edges) == 0: # if it has no outgoing edges, it is an exit node
            exit_nodes.append(node)
        elif len(incoming_edges) == 1 and len(outgoing_edges) == 1 and not node.getConnections(): # case where it is simultaneously an entry and exit node (dead end, but with an entry and an exit of the network)
            entry_nodes.append(node)
            exit_nodes.append(node)
        elif len(incoming_edges) == 1 and len(outgoing_edges) == 2: # case of an entry of the network through a roundabout
            if 'rotunda' in incoming_edges[0].getName().lower() or 'roundabout' in incoming_edges[0].getName().lower():
                for edge in outgoing_edges:
                    if 'rotunda' not in edge.getName().lower() and 'roundabout' not in edge.getName().lower():
                        entry_nodes.append(node)
        elif len(incoming_edges) == 2 and len(outgoing_edges) == 1: # case of an exit of the network through a roundabout
            if 'rotunda' in outgoing_edges[0].getName().lower() or 'roundabout' in outgoing_edges[0].getName().lower():
                for edge in incoming_edges:
                    if 'rotunda' not in edge.getName().lower() and 'roundabout' not in edge.getName().lower():
                        exit_nodes.append(node)
    
    return entry_nodes, exit_nodes

def get_sensors_coverage(coverage_file):
        sensors_coverage = {} # sensor : [edges]
        with open(coverage_file, 'r') as f:
            lines = f.readlines()

            for line in lines:
                if line.startswith('###'):
                    sensor = line.split('sensor')[-1].strip()[:-1]
                    sensors_coverage[sensor] = []
                elif line != '\n':
                    sensors_coverage[sensor].append(line.strip())

        return sensors_coverage

def get_variable_name(edge_id, node_name, sensors_coverage, node_sensors, variable_count):
    variable = f'x{variable_count}'
    for sensor, edges in sensors_coverage.items():
        if edge_id in edges:
            variable = f'q{variable_count}'
            node_sensors[node_name].append(sensor)
    return variable

def gen_pinpoint(edge, id, type, color, additional_tag):
    shape = edge.getShape()
    if type == 'flow variable': # get the coordinates of the center of an edge: if its shape only has 2 tuples, the center is calculated directly by averaging the two points
        pos = shape[int(len(shape) / 2)] if len(shape) != 2 else ((shape[0][0] + shape[1][0]) / 2, (shape[0][1] + shape[1][1]) / 2)
    elif type == 'router': # position the router a little further in front of the center of the edge
        line = LineString(shape)
        midpoint = line.interpolate(0.75, normalized=True)
        pos = midpoint.coords[0]
    # TODO: after handling the lane variables, uncomment this block
    # elif type == 'flow variable (lane)': # position the lane variable near the respective lane
    #     line = LineString(shape)
    #     midpoint = line.interpolate(0.85, normalized=True)
    #     pos = midpoint.coords[0]

    ET.SubElement(additional_tag, 'poi', id=id, color=color, layer='202.00', x=str(pos[0]), y=str(pos[1]), type=type, name=edge.getID())

def process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, additional_tag):
    while process_list:
        edge = process_list.popleft()
        connections = edge.getToNode().getConnections()
        router_generated = False
        pending_merge_appended = False

        # TODO: em vez de "for" em baixo, usar isto de alguma forma
        # connection_pairs = {} # from_edge: [(to_edge, conn), ...)]
        # for conn in connections:
        #     connection_pairs.setdefault(conn.getFrom().getID(), []).append((conn.getTo().getID(), conn))

        for conn in connections:
            from_edge = conn.getFrom()
            to_edge = conn.getTo()

            conn_incoming = list(to_edge.getIncoming().keys())
            conn_outgoing = list(from_edge.getOutgoing().keys())

            if len(conn_incoming) == 1 and len(conn_outgoing) == 1: # case where the following edge is just a continuation of the previous edge
                if conn_outgoing[0].getID() not in variables:
                    lane_variables = {}
                    variables[conn_outgoing[0].getID()] = {'root_var': variables[edge.getID()]['root_var']}
                    for lane in conn_outgoing[0].getLanes():
                        variable = variables[edge.getID()]['root_var']
                        lane_variables[lane.getID()] = variable
                    variables[conn_outgoing[0].getID()] |= lane_variables

                    process_list.append(conn_outgoing[0])

            elif len(conn_incoming) > 1 and len(conn_outgoing) == 1: # case of a merging junction, analyse if it can be processable                        
                processable = True
                for m_edge in conn_incoming:
                    if m_edge.getID() != edge.getID() and m_edge.getID() not in variables:
                        processable = False
                        break

                if processable:
                    if conn_outgoing[0].getID() not in variables:
                        variable = get_variable_name(conn_outgoing[0].getID(), node_name, sensors_coverage, node_sensors, variable_count)
                        lane_variables = {}
                        variables[conn_outgoing[0].getID()] = {'root_var': variable}
                        for lane in conn_outgoing[0].getLanes():
                            lane_variables[lane.getID()] = variable
                        variables[conn_outgoing[0].getID()] |= lane_variables
                        gen_pinpoint(conn_outgoing[0], variable, 'flow variable', 'cyan', additional_tag)

                        # remove all merging edges from the process list, as they do not need more processing
                        conn_incoming_ids = [m_edge.getID() for m_edge in conn_incoming]
                        for elem in process_list.copy():
                            if elem.getID() in conn_incoming_ids:
                                process_list.remove(elem)

                        variable_count += 1
                        process_list.append(conn_outgoing[0])

                    # append a new equation
                    following_variable = variables[conn_outgoing[0].getID()]['root_var']
                    eq = f'{following_variable} = ' + ' + '.join([variables[m_edge.getID()]['root_var'] for m_edge in conn_incoming])
                    equations.add(eq)

                    while conn_outgoing[0] in pending_merges:
                        pending_merges.remove(conn_outgoing[0])
                else:
                    if not pending_merge_appended:
                        pending_merges.append(conn_outgoing[0])
                        pending_merge_appended = True

            elif len(conn_incoming) == 1 and len(conn_outgoing) > 1: # case of a splitting edge, assign new variables
                # assign new variables to the following edges
                for f_edge in conn_outgoing:
                    if f_edge.getID() not in variables:
                        variable = get_variable_name(f_edge.getID(), node_name, sensors_coverage, node_sensors, variable_count)
                        lane_variables = {}
                        variables[f_edge.getID()] = {'root_var': variable}
                        for lane in f_edge.getLanes():
                            lane_variables[lane.getID()] = variable
                        variables[f_edge.getID()] |= lane_variables
                        gen_pinpoint(f_edge, variable, 'flow variable', 'cyan', additional_tag)

                        variable_count += 1
                        process_list.append(f_edge)
                
                # append a new equation
                following_variable = variables[edge.getID()]['root_var']
                eq = f'{following_variable} = ' + ' + '.join([variables[f_edge.getID()]['root_var'] for f_edge in conn_outgoing])
                equations.add(eq)

                # place a router on the split edge if not already placed
                if not router_generated:
                    gen_pinpoint(edge, f'router_{router_count}', 'router', 'green', additional_tag)
                    router_count += 1
                    router_generated = True

            else:
                # TODO: descomentar estas duas linhas para verificar os nós complexos de algumas redes (após edição topológica)
                # print('ENTROU NO ELSEEEEEEE com o node ', edge.getToNode().getID())
                # print(f'INCOMING {conn_incoming} OUTGOING {conn_outgoing}')
                pass
    
    return variable_count, router_count, pending_merges

def calculate_intermediate_variables(network, node_name, process_list, variable_count, variables, sensors_coverage, node_sensors, additional_tag):
    equations = set()
    router_count = 1
    pending_merges = []
    
    variable_count, router_count, pending_merges = process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, additional_tag)

    print(f"Generated {router_count - 1} routers.")
    
    pending_edges = []
    for edge in network.getEdges():
        if edge.getID() not in variables:
            pending_edges.append(edge)
            # print(f"Edge {edge.getID()} has no variable assigned.")

    # continue the algorithm by assigning a new variable to one of the pending edges, allowing processing of pending merges
    while pending_merges:
        following_edge = pending_merges.pop(0)
        merging_edges = following_edge.getFromNode().getIncoming()
        for edge in merging_edges:
            if edge in pending_edges:
                variable = get_variable_name(edge.getID(), node_name, sensors_coverage, node_sensors, variable_count)
                lane_variables = {}
                variables[edge.getID()] = {'root_var': variable}
                for lane in edge.getLanes():
                    lane_variables[lane.getID()] = variable
                variables[edge.getID()] |= lane_variables
                gen_pinpoint(edge, variable, 'flow variable', 'blue', additional_tag)
                
                variable_count += 1
                pending_edges.remove(edge)
                process_list.append(edge)
                break
        
        variable_count, router_count, pending_merges = process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, additional_tag)

    pending_edges = []
    for edge in network.getEdges():
        if edge.getID() not in variables:
            pending_edges.append(edge)
            print(f"Edge {edge.getID()} has no variable assigned.")

    return variable_count, list(equations)

def gen_variables(network, node_name, entry_nodes, exit_nodes, sensors_coverage, node_sensors, network_file):
    additional_tag = ET.Element('additional')
    variable_count = 1
    variables = {} # edge_id : {root_var: variable, lane_id : variable, ...}
    process_list = []

    for entry in entry_nodes:
        if len(entry.getOutgoing()) > 1:
            if not (len(entry.getOutgoing()) == 2 and any('rotunda' in edge.getName().lower() or 'roundabout' in edge.getName().lower() for edge in entry.getOutgoing())):
                print(f"Entry node {entry.getID()} has more than one outgoing edge. Please adapt the network so that each entry node has only one outgoing edge.")
                continue

        entry_edge = next(filter(lambda edge: 'rotunda' not in edge.getName().lower() and 'roundabout' not in edge.getName().lower(), entry.getOutgoing()))
        edge_id = entry_edge.getID()
        edge = network.getEdge(edge_id)

        variable = get_variable_name(edge_id, node_name, sensors_coverage, node_sensors, variable_count)
        lane_variables = {}
        variables[edge_id] = {'root_var': variable}
        for lane in edge.getLanes():
            lane_variables[lane.getID()] = variable
        variables[edge_id] |= lane_variables
        gen_pinpoint(edge, variable, 'flow variable', 'yellow', additional_tag)

        process_list.append(edge)
        variable_count += 1

    for exit in exit_nodes:
        if len(exit.getIncoming()) > 1:
            if not (len(exit.getIncoming()) == 2 and any('rotunda' in edge.getName().lower() or 'roundabout' in edge.getName().lower() for edge in exit.getIncoming())):
                print(f"Exit node {exit.getID()} has more than one incoming edge. Please adapt the network so that each exit node has only one incoming edge.")
                continue
        
        exit_edge = next(filter(lambda edge: 'rotunda' not in edge.getName().lower() and 'roundabout' not in edge.getName().lower(), exit.getIncoming()))
        edge_id = exit_edge.getID()
        edge = network.getEdge(edge_id)

        variable = get_variable_name(edge_id, node_name, sensors_coverage, node_sensors, variable_count)
        lane_variables = {}
        variables[edge_id] = {'root_var': variable}
        for lane in edge.getLanes():
            lane_variables[lane.getID()] = variable
        variables[edge_id] |= lane_variables
        gen_pinpoint(edge, variable, 'flow variable', '128,128,0', additional_tag)

        # define the variables of the edges that serve as a continuation of the exit edges
        previous_edges = list(edge.getIncoming().keys())
        while len(previous_edges) == 1:
            if len(list(previous_edges[0].getOutgoing().keys())) > 1:
                break

            lane_variables = {}
            variables[previous_edges[0].getID()] = {'root_var': variable}
            for lane in previous_edges[0].getLanes():
                lane_variables[lane.getID()] = variable
            variables[previous_edges[0].getID()] |= lane_variables
            previous_edges = list(previous_edges[0].getIncoming().keys())

        variable_count += 1
    
    process_list = collections.deque(process_list)
    variable_count, equations = calculate_intermediate_variables(network, node_name, process_list, variable_count, variables, sensors_coverage, node_sensors, additional_tag)

    write_xml(additional_tag, network_file.replace('.net', '_poi'))

    return variable_count, equations

def highest_variable(equation):
    """
    Find the highest variable in a given equation.
    Arguments:
        equation: a string representing an equation
    Returns:
        The highest variable in the equation
    """

    highest = 'x0'
    vars = remove_chars(equation, '+-=').split()
    for var in vars:
        if var.startswith('x') or var.startswith('q'):
            num = int(var[1:])
            if num > int(highest[1:]):
                highest = var

    return highest

def reduce_equations(equations):
    """
    Formats and simplifies a system of equations, passing constants to the right-hand side and variables to the left-hand side.
    Arguments:
        equations: a list of strings representing equations
    Returns:
        A new formatted and simplified list of strings representing equations
    """

    simplified_equations = []
    removed_rhs_equations = []
    new_equations = []

    print(f'Initial equations: {equations}')

    # Simplify the equations
    for eq in equations:
        simplified = False
        old_lhs, old_rhs = eq.split('=')
        lhs_expr = sympy.sympify(old_lhs)

        lhs_var = lhs_expr.free_symbols.pop()
        for eq2 in equations:
            new_lhs, rhs = eq2.split('=')
            rhs_expr = sympy.sympify(rhs)
            rhs_vars = rhs_expr.free_symbols
            if eq != eq2 and lhs_var in rhs_vars and lhs_var.name == highest_variable(eq):
                new_rhs = rhs.replace(lhs_var.name, old_rhs.strip())
                new_eq = f'{new_lhs}={new_rhs}'
                simplified_equations.append(new_eq)
                removed_rhs_equations.append(eq2)
                simplified = True
        
        if not simplified and eq not in removed_rhs_equations:
            simplified_equations.append(eq)

    # Format the equations
    for eq in simplified_equations:
        lhs, rhs = eq.split('=')
        lhs_expr = sympy.sympify(lhs)
        rhs_expr = sympy.sympify(rhs)
        lhs_vars = list(lhs_expr.free_symbols)
        rhs_vars = list(rhs_expr.free_symbols)

        # Move constants from left hand side to right hand side
        lhs_const = [sympy.Symbol(var.name) for var in lhs_vars if var.name.startswith('q')]
        new_lhs_expr = lhs_expr - sum(var for var in lhs_const)
        new_rhs_expr = rhs_expr - sum(var for var in lhs_const)

        # Move variables from right hand side to left hand side
        rhs_vars = [sympy.Symbol(var.name) for var in rhs_vars if var.name.startswith('x')]
        new_lhs_expr = new_lhs_expr - sum(var for var in rhs_vars)
        new_rhs_expr = new_rhs_expr - sum(var for var in rhs_vars)

        new_lhs_expr = sympy.factor(new_lhs_expr)
        new_rhs_expr = sympy.factor(new_rhs_expr)

        new_eq = sympy.Eq(new_lhs_expr, new_rhs_expr)

        if sum(str(term).count('-') for term in new_eq.args) > sum(str(term).count('+') for term in new_eq.args):
            new_eq = sympy.Eq(-1 * new_eq.lhs, -1 * new_eq.rhs)

        new_equations.append(f'{str(new_eq.lhs)} = {str(new_eq.rhs)}')

    print(f'Simplified equations: {new_equations}')

    return new_equations

def process_node(node_name, network_file, nsf, ef, sensors_coverage, node_sensors):
    network = sumolib.net.readNet(network_file)

    entry_nodes, exit_nodes = get_entry_exit_nodes(network.getNodes())
    print(f"Found {len(entry_nodes)} entry nodes and {len(exit_nodes)} exit nodes.")
    print(f"Entry nodes: {[entry.getID() for entry in entry_nodes]}")
    print(f"Exit nodes: {[exit.getID() for exit in exit_nodes]}")

    variable_count, equations = gen_variables(network, node_name, entry_nodes, exit_nodes, sensors_coverage, node_sensors, network_file)

    nsf.write(f'### Sensors of {node_name}:\n')
    for sensor in node_sensors[node_name]:
        nsf.write(f'{sensor}\n')
    nsf.write('\n')

    if node_name == 'Article':
        patterns = {'x12': 'q12', 'x4': 'q4', 'x10': 'q10', 'x5': 'q5', 'x8': 'q8', 'x7': 'q7'} # TODO: if I integrate the article sensors coords, remove this conditional block
        for i, eq in enumerate(equations):
            for pattern, replacement in patterns.items():
                equations[i] = equations[i].replace(pattern, replacement)

    equations = reduce_equations(equations)

    last_equation = len(equations) - 1
    ef.write(f'### Equations of {node_name} - {len(equations)}:\n')
    for i, eq in enumerate(equations):
        eq = re.sub(r'x(\d+)', r'x_{\1}', eq)
        eq = re.sub(r'q(\d+)', r'q_{\1}', eq)
        ef.write(f'${eq}$')
        if (i != last_equation):
            ef.write('\\')
        ef.write('\n')
    ef.write('\n')

    print(f"Generated {variable_count - 1} variables.\n")


if __name__ == '__main__':
    config = load_config()
    node_sensors_file = config.get('nodes', 'SENSORS', fallback='./nodes/node_sensors.md')
    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')

    node_sensors = {}
    sensors_coverage = get_sensors_coverage(coverage_file)

    with open(node_sensors_file, 'w') as nsf, open(equations_file, 'w') as ef:
        for var, value in list(config.items('nodes')):
            if var.startswith('node_'):
                node_name, network_file = value.split(',')
                node_sensors[node_name] = []
                print(f"::: Processing node {node_name} :::\n")
                process_node(node_name, network_file, nsf, ef, sensors_coverage, node_sensors)
