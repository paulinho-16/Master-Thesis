"""Variable Definitions and Equation Systems Generation

This script creates the flow variables of the network and generates the corresponding POIs.
It deduces the equation systems for the VCI nodes, generating the file `equations.md` in the `nodes` folder.
It also generates the POIs for the routers of the network.

"""

import re
import sys
import sympy
import pickle
import sumolib
import collections
import xml.etree.cElementTree as ET
from shapely.geometry import LineString

from .utils import load_config, remove_chars, write_xml, get_sensors_coverage, get_entry_exit_nodes

def get_variable_name(edge_id, node_name, sensors_coverage, node_sensors, variable_count):
    variable = f'x{variable_count}'
    for sensor, values in sensors_coverage.items():
        if edge_id in values[1]:
            variable = f'q{variable_count}'
            node_sensors[node_name].append(sensor)

    if node_name == 'Article': # TODO: APAGAR - é só para ficar com a mesma numeração que o artigo
        replacement_mapping = {'q12': 'q1', 'q4': 'q2', 'q10': 'q3', 'q5': 'q4', 'q8': 'q5', 'q7': 'q6', 'x13': 'x1', 'x22': 'x2', 'x18': 'x3', 'x19': 'x4', 'x14': 'x5', 'x23': 'x6', 'x16': 'x7', 'x21': 'x8', 'x24': 'x10', 'x6': 'x11', 'x3': 'x12', 'x11': 'x13', 'x15': 'x14', 'x2': 'x15', 'x1': 'x16'}
        variable = replacement_mapping[variable] if variable in replacement_mapping.keys() else variable
    
    return variable

def gen_pinpoint(edge, id, type, color, additional_tag):
    shape = edge.getShape()
    if type == 'flow variable': # get the coordinates of the center of an edge: if its shape only has 2 tuples, the center is calculated directly by averaging the two points
        pos = shape[int(len(shape) / 2)] if len(shape) != 2 else ((shape[0][0] + shape[1][0]) / 2, (shape[0][1] + shape[1][1]) / 2)
    elif type == 'router': # position the router a little further in front of the center of the edge
        line = LineString(shape)
        midpoint = line.interpolate(0.75, normalized=True)
        pos = midpoint.coords[0]
    elif type == 'flow variable (lane)': # position the lane variable near the respective lane
        line = LineString(shape)
        midpoint = line.interpolate(0.85, normalized=True)
        pos = midpoint.coords[0]
        # TODO: nos casos de uma edge apenas mas dois sentidos (ex: nó do Amial), posicionar as duas variáveis em sítios diferentes

    ET.SubElement(additional_tag, 'poi', id=id, color=color, layer='202.00', x=str(pos[0]), y=str(pos[1]), type=type, name=edge.getID())

def process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, future_processing, additional_tag, divided_edges):
    while process_list:
        edge = process_list.popleft()
        connections = edge.getToNode().getConnections()
        router_generated = False
        pending_merge_appended = False
        connection_pairs = {} # from_edge: [(to_edge, conn), ...)]

        for conn in connections:
            from_edge = conn.getFrom()
            to_edge = conn.getTo()

            conn_incoming = list(to_edge.getIncoming().keys())
            conn_outgoing = list(from_edge.getOutgoing().keys())

            if len(conn_incoming) == 1 and len(conn_outgoing) == 1: # case where the following edge is just a continuation of the previous edge
                if conn_incoming[0].getID() not in variables:
                    if conn_outgoing[0] not in future_processing:
                        future_processing.append(conn_outgoing[0])
                    continue

                if conn_outgoing[0].getID() not in variables:
                    lane_variables = {}
                    variables[conn_outgoing[0].getID()] = {'root_var': variables[conn_incoming[0].getID()][conn.getFromLane().getID()]}
                    for lane in conn_outgoing[0].getLanes():
                        variable = variables[conn_incoming[0].getID()]['root_var']
                        lane_variables[lane.getID()] = variable
                    variables[conn_outgoing[0].getID()] |= lane_variables

                    process_list.append(conn_outgoing[0])

            elif len(conn_incoming) > 1 and len(conn_outgoing) == 1: # case of a merging junction, analyse if it can be processable
                processable = True
                for m_edge in conn_incoming:
                    if m_edge.getID() not in variables:
                        processable = False
                    else:
                        for lane in m_edge.getLanes():
                            if lane.getID() not in variables[m_edge.getID()]:
                                processable = False
                    if not processable:
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

                    # check if the equation is ready to be added (updated variables)
                    conns_edge_lane = [(conn.getFrom(), conn.getFromLane(), conn) for conn in connections if conn.getFrom() in conn_incoming and conn.getTo() == conn_outgoing[0]]
                    incoming_lanes = {}
                    for edge_lane in conns_edge_lane:
                        incoming_lanes.setdefault(edge_lane[0], set()).add(edge_lane[1].getID())

                    equation_ready = True
                    for edge in incoming_lanes.keys():
                        if len(incoming_lanes[edge]) != len(edge.getLanes()) and edge.getID() not in divided_edges:
                            equation_ready = False

                    # append a new equation
                    if equation_ready:
                        following_variable = variables[conn_outgoing[0].getID()]['root_var']
                        equation = f'{following_variable} = ' + ' + '.join(set([variables[edge.getID()][lane.getID()] if type(variables[edge.getID()][lane.getID()]) == str else variables[edge.getID()][lane.getID()][connection] for (edge, lane, connection) in conns_edge_lane]))
                        equations.add(equation)

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
                if from_edge.getID() == edge.getID():
                    following_variable = variables[edge.getID()]['root_var']
                    equation = f'{following_variable} = ' + ' + '.join([variables[f_edge.getID()]['root_var'] for f_edge in conn_outgoing])
                    equations.add(equation)

                # place a router on the split edge if not already placed
                if not router_generated:
                    gen_pinpoint(edge, f'router_{router_count}', 'router', 'green', additional_tag)
                    router_count += 1
                    router_generated = True

            else:
                connection_pairs.setdefault(conn.getFrom(), []).append((conn.getTo(), conn))

        # extreme cases, in which it is necessary to associate a variable for each possible direction in a single edge
        for from_edge in connection_pairs.keys():
            if len(connection_pairs[from_edge]) > 1 and from_edge.getID() in variables and from_edge.getID() not in divided_edges:
                lane_variables = {}
                variables[from_edge.getID()] = {'root_var': variables[from_edge.getID()]['root_var']}
                added_variables = set()

                to_edges = {} # to_edge : [(lane_id, conn), ...]
                for conn in connection_pairs[from_edge]:
                    to_edges.setdefault(conn[0], []).append((conn[1].getFromLane(), conn[1]))

                for to_edge in to_edges.keys():
                    var_lane = to_edges[to_edge][-1][0] # place the variable on the last lane
                    variable = get_variable_name(from_edge, node_name, sensors_coverage, node_sensors, variable_count)

                    for lane, conn in to_edges[to_edge]:
                        if lane.getID() not in lane_variables:
                            lane_variables[lane.getID()] = {conn: variable}
                        else:
                            lane_variables[lane.getID()][conn] = variable
                    
                    gen_pinpoint(var_lane, variable, 'flow variable (lane)', '0,0,128', additional_tag)

                    variable_count += 1
                    added_variables.add(variable)

                variables[from_edge.getID()] |= lane_variables

                # append a new equation
                edge_variable = variables[from_edge.getID()]['root_var']
                equation = f'{edge_variable} = ' + ' + '.join([var for var in added_variables])
                equations.add(equation)

                divided_edges.add(from_edge.getID())

        # reverse the connection pairs dictionary
        reversed_pairs = {}
        for key, values in connection_pairs.items():
            for value in values:
                edge = value[0]
                if edge in reversed_pairs:
                    if key not in [from_edge[0] for from_edge in reversed_pairs[edge]]:
                        reversed_pairs[edge].append((key, value[1]))
                else:
                    reversed_pairs[edge] = [(key, value[1])]

        # extreme cases of merges in complex nodes, having many incoming and outgoing edges
        for to_edge in reversed_pairs.keys():
            if to_edge.getID() not in variables:
                # check if the from edges have all been processed
                processed = True
                for from_edge in reversed_pairs[to_edge]:
                    if from_edge[0].getID() not in variables:
                        processed = False
                if not processed:
                    break

                variable = get_variable_name(to_edge.getID(), node_name, sensors_coverage, node_sensors, variable_count)
                lane_variables = {}
                variables[to_edge.getID()] = {'root_var': variable}
                for lane in to_edge.getLanes():
                    lane_variables[lane.getID()] = variable
                variables[to_edge.getID()] |= lane_variables
                gen_pinpoint(to_edge, variable, 'flow variable', '128,0,128', additional_tag)
                variable_count += 1

                previous_variables = []
                for from_edge in reversed_pairs[to_edge]:
                    from_lane = from_edge[1].getFromLane().getID()
                    previous_variables.append(variables[from_edge[0].getID()][from_lane][from_edge[1]])

                # append a new equation
                edge_variable = variables[to_edge.getID()]['root_var']
                equation = f'{edge_variable} = ' + ' + '.join([var for var in previous_variables])
                equations.add(equation)

                # update the pending_merges list
                outgoing_edges = list(to_edge.getOutgoing().keys())
                if len(outgoing_edges) == 1:
                    pending = False
                    for incoming_edge in outgoing_edges[0].getIncoming().keys():
                        if incoming_edge != to_edge and incoming_edge.getID() not in variables:
                            pending = True

                    if not pending:
                        while outgoing_edges[0] in pending_merges:
                            pending_merges.remove(outgoing_edges[0])
                        process_list.append(to_edge)
    
    return variable_count, router_count, pending_merges

def calculate_intermediate_variables(network, network_file, node_name, nodes_dir, process_list, variable_count, variables, sensors_coverage, node_sensors, additional_tag):
    equations = set()
    router_count = 1
    pending_merges = []
    future_processing = [] # edges that are not ready to be processed in the first iteration of the algorithm
    divided_edges = set()
    
    variable_count, router_count, pending_merges = process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, future_processing, additional_tag, divided_edges)

    print(f"Generated {router_count - 1} routers.")

    pending_edges = []
    for edge in network.getEdges():
        if edge.getID() not in variables:
            pending_edges.append(edge)

    for pending_edge in pending_edges:
        previous_edges = list(pending_edge.getIncoming().keys())
        for p_edge in previous_edges:
            if p_edge in pending_edges:
                pending_edges.remove(pending_edge)
                break

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

        variable_count, router_count, pending_merges = process(node_name, process_list, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, future_processing, additional_tag, divided_edges)

    # process the pending edges in future_processing
    future_processing = collections.deque(future_processing)
    variable_count, router_count, pending_merges = process(node_name, future_processing, variables, equations, variable_count, router_count, sensors_coverage, node_sensors, pending_merges, future_processing, additional_tag, divided_edges)

    pending_edges = []
    for edge in network.getEdges():
        if edge.getID() not in variables:
            pending_edges.append(edge)
            print(f"Edge {edge.getID()} has no variable assigned.")

    # register the variables assignments in a pickle file
    with open(f"{nodes_dir}/variables_{network_file.split('.')[-3].split('/')[-1]}.pkl", 'wb') as f:
        pickle.dump(variables, f)

    return variable_count, sorted(equations)

def gen_variables(network, node_name, nodes_dir, entry_nodes, exit_nodes, sensors_coverage, node_sensors, network_file):
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
    variable_count, equations = calculate_intermediate_variables(network, network_file, node_name, nodes_dir, process_list, variable_count, variables, sensors_coverage, node_sensors, additional_tag)

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

def get_sort_key(x, coefficient):
    if x.is_number:
        return sys.maxsize
    number = int(re.findall(r'\d+', str(x))[0])
    coefficient_score = 1 if coefficient < 0 else -1
    return coefficient_score, number

def order_terms(expression):
    terms = expression.as_coefficients_dict()
    if all(key.is_number for key in terms.keys()): # case where there is only constants in the expression
        return expression
    sorted_terms = sorted(terms, key=lambda term: get_sort_key(term, terms[term]))

    ordered_expr = f'{sorted_terms[0]}'
    for term in sorted_terms[1:]:
        coefficient = terms[term]
        full_term = term * coefficient
        ordered_expr += f' - {full_term*-1}' if coefficient < 0 else f' + {full_term}'

    return ordered_expr

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

    print(f'Initial equations ({len(equations)}): {equations}')

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

    for eq in removed_rhs_equations:
        if eq in simplified_equations:
            simplified_equations.remove(eq)

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

        ordered_lhs = order_terms(new_eq.lhs)
        ordered_rhs = order_terms(new_eq.rhs)

        new_equations.append(f'{str(ordered_lhs)} = {str(ordered_rhs)}')

    print(f'Simplified equations ({len(new_equations)}): {new_equations}')

    return new_equations

def process_node(node_name, network_file, nodes_dir, entries_exits_file, nsf, ef, sensors_coverage, node_sensors):
    network = sumolib.net.readNet(network_file)
    entry_nodes_ids, exit_nodes_ids = get_entry_exit_nodes(entries_exits_file, node_name)
    entry_nodes, exit_nodes = [network.getNode(node_id) for node_id in entry_nodes_ids], [network.getNode(node_id) for node_id in exit_nodes_ids]

    variable_count, equations = gen_variables(network, node_name, nodes_dir, entry_nodes, exit_nodes, sensors_coverage, node_sensors, network_file)

    nsf.write(f'### Sensors of {node_name}:\n')
    for sensor in node_sensors[node_name]:
        nsf.write(f'{sensor}\n')
    nsf.write('\n')

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
    entries_exits_file = config.get('nodes', 'ENTRIES_EXITS', fallback='./nodes/entries_exits.md')
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')
    nodes_dir = config.get('dir', 'NODES', fallback='./nodes')

    node_sensors = {}
    sensors_coverage = get_sensors_coverage(coverage_file)

    with open(node_sensors_file, 'w') as nsf, open(equations_file, 'w') as ef:
        for var, value in list(config.items('nodes')):
            if var.startswith('node_'):
                node_name, network_file = value.split(',')
                node_sensors[node_name] = []
                print(f"::: Processing node {node_name} :::\n")
                process_node(node_name, network_file, nodes_dir, entries_exits_file, nsf, ef, sensors_coverage, node_sensors)
