"""Variable Definitions and Equation Systems Generation

This script creates the flow variables of the network and generates the corresponding POIs.
It also deduces the equation systems for the VCI nodes, generating the file `equations.md` in the `nodes` folder.

"""

import re
import sympy
import sumolib
import itertools
from collections import deque
import xml.etree.cElementTree as ET

from .utils import load_config, remove_chars, write_xml

def get_entry_exit_nodes(nodes):
    entry_nodes = []
    exit_nodes = []

    for node in nodes:
        if len(node.getIncoming()) == 0: # if it has no incoming edges, it is an entry node
            entry_nodes.append(node)
        elif len(node.getOutgoing()) == 0: # if it has no outgoing edges, it is an exit node
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

def get_variable_name(edge_id, covered_edges, variable_count):
    return f'q{variable_count}' if edge_id in covered_edges else f'x{variable_count}'

def gen_pinpoint(edge, variable, color, additional_tag):
    # get the coordinates of the center of an edge: if its shape has only 2 tuples, the center is calculated directly by averaging the two points
    shape = edge.getShape()
    center = shape[int(len(shape) / 2)] if len(shape) != 2 else ((shape[0][0] + shape[1][0]) / 2, (shape[0][1] + shape[1][1]) / 2)

    ET.SubElement(additional_tag, 'poi', id=variable, color=color, layer='202.00', x=str(center[0]), y=str(center[1]), type='flow variable', name=edge.getID())

def calculate_intermediate_variables(network, process_list, variable_count, variables, covered_edges, additional_tag):
    equations = []
    while process_list:
        edge = process_list.popleft()

        merging_edges = edge.getToNode().getIncoming()
        following_edges = edge.getToNode().getOutgoing()

        if len(merging_edges) == 1 and len(following_edges) == 1: # case where the following edge is just a continuation of the previous edge
            if following_edges[0].getID() not in variables:
                variables[following_edges[0].getID()] = variables[edge.getID()]
                process_list.append(following_edges[0])

        elif len(merging_edges) > 1 and len(following_edges) == 1: # case of a merging junction, analyse if it can be processable                        
            processable = True
            for m_edge in merging_edges:
                if m_edge.getID() != edge.getID() and m_edge.getID() not in variables:
                    processable = False
                    break

            if processable:
                if following_edges[0].getID() not in variables:
                    variable = get_variable_name(following_edges[0].getID(), covered_edges, variable_count)
                    variables[following_edges[0].getID()] = variable
                    gen_pinpoint(following_edges[0], variable, 'cyan', additional_tag)

                    # remove all merging edges from the process list, as they do not need more processing
                    merging_edges_ids = [m_edge.getID() for m_edge in merging_edges]
                    for elem in process_list.copy():
                        if elem.getID() in merging_edges_ids:
                            process_list.remove(elem)

                    variable_count += 1
                    process_list.append(following_edges[0])

                # append a new equation
                eq = f'{variables[following_edges[0].getID()]} = ' + ' + '.join([variables[m_edge.getID()] for m_edge in merging_edges])
                equations.append(eq)

        elif len(merging_edges) == 1 and len(following_edges) > 1: # case of a splitting edge , assign new variables
            for f_edge in following_edges:
                if f_edge.getID() not in variables:
                    variable = get_variable_name(f_edge.getID(), covered_edges, variable_count)
                    variables[f_edge.getID()] = variable
                    gen_pinpoint(f_edge, variable, 'cyan', additional_tag)

                    variable_count += 1
                    process_list.append(f_edge)
            
            # append a new equation
            eq = f'{variables[edge.getID()]} = ' + ' + '.join([variables[f_edge.getID()] for f_edge in following_edges])
            equations.append(eq)

    for edge in network.getEdges():
        if edge.getID() not in variables:
            print(f"Edge {edge.getID()} has no variable assigned.")

    return variable_count, equations

def gen_variables(network, entry_nodes, exit_nodes, covered_edges, network_file):
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

        variable = get_variable_name(edge_id, covered_edges, variable_count)
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

        variable = get_variable_name(edge_id, covered_edges, variable_count)
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
    variable_count, equations = calculate_intermediate_variables(network, process_list, variable_count, variables, covered_edges, additional_tag)
    
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


if __name__ == '__main__':
    config = load_config()
    node_name, network_file = config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml').split(',')
    # node_name, network_file = config.get('nodes', 'NODE_AREINHO', fallback='./nodes/no_areinho.net.xml').split(',')
    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')

    sensors_coverage = get_sensors_coverage(coverage_file)
    covered_edges = set(itertools.chain(*sensors_coverage.values()))

    network = sumolib.net.readNet(network_file)

    entry_nodes, exit_nodes = get_entry_exit_nodes(network.getNodes())
    print(f"Found {len(entry_nodes)} entry nodes and {len(exit_nodes)} exit nodes.")
    print(f"Entry nodes: {[entry.getID() for entry in entry_nodes]}")
    print(f"Exit nodes: {[exit.getID() for exit in exit_nodes]}")

    with open(equations_file, 'w') as ef:
        variable_count, equations = gen_variables(network, entry_nodes, exit_nodes, covered_edges, network_file)

        if node_name == 'Article':
            print('entrou')
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

    print(f"Generated {variable_count - 1} variables.")