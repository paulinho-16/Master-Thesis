import re
from itertools import product
import xml.etree.cElementTree as ET
from configparser import ConfigParser, ExtendedInterpolation

def load_config():
    config = ConfigParser(interpolation=ExtendedInterpolation())
    config.read('config.ini')
    return config

def remove_chars(string, chars):
    return string.translate({ord(i): None for i in chars})

def write_xml(body, file):
    ET.indent(body, space='\t')
    tree = ET.ElementTree(body)
    tree.write(file, encoding='UTF-8', xml_declaration=True)

def get_variables(equations):
    variables = set()
    for eq in equations:
        vars = remove_chars(eq, '+-=').split()
        for var in vars:
            if var.startswith('x'):
                variables.add(var)
    
    variables = sorted(list(variables), key=lambda x: int(x[1:]))
    return variables

def get_eq_variables(network_name, equations_file):
    with open(equations_file, 'r') as f:
        lines = f.readlines()

        for i, line in enumerate(lines):
            if line.startswith('###'):
                current_network = remove_chars(line.strip(), '#:')
                eq_network_name = current_network.split(' - ')[0].split(' of ')[1].strip()
                if eq_network_name == network_name:
                    num_equations = int(current_network.split(' - ')[1])
                    equations = [remove_chars(eq.strip(), '$_{}\\') for eq in lines[i+1:i+num_equations+1]]
                    variables = get_variables(equations)
                    break
    
    return variables

def get_network_sensors(network_sensors_file):
    network_sensors = {} # network_name : [sensors]
    with open(network_sensors_file, 'r') as f:
        lines = f.readlines()

        for line in lines:
            if line.startswith('###'):
                network_name = line.split('Sensors of')[-1].strip()[:-1]
                network_sensors[network_name] = []
            elif line != '\n':
                network_sensors[network_name].append(line.strip())

    return network_sensors

def get_sensors_coverage(coverage_file):
    sensors_coverage = {} # sensor : [lane_id, edges]
    with open(coverage_file, 'r') as f:
        lines = f.readlines()

        for line in lines:
            if line.startswith('###'):
                sensor_lane = line.split('sensor')[-1].strip()[:-1]
                sensor = sensor_lane[:sensor_lane.rindex('(')].strip()
                lane_id = re.findall(r'\((.*?)\)', sensor_lane)[-1]
                sensors_coverage[sensor] = [lane_id, []]
            elif line != '\n':
                sensors_coverage[sensor][1].append(line.strip())

    return sensors_coverage

def get_free_variables(free_variables_file):
    free_variables = {} # network_name : ([free variables], [inequality constraint matrix], [inequality constraint vector], [Xparticular], [Xnull])
    with open(free_variables_file, 'r') as f:
        content = f.read()

        pattern = r"### Free variables of (.+?): (\[.+?\])\nInequality constraint matrix of [^:]+: (\[\[.*?\]\])\nInequality constraint vector of [^:]+: (\[.+?\])\nXparticular vector of [^:]+: (\[\[.*?\]\])\nXnull matrix of [^:]+: (\[\[.*?\]\])"
        matches = re.findall(pattern, content, re.DOTALL)
        results = [(network_name, eval(free_vars), eval(ic_matrix), eval(ic_vector), eval(x_particular), eval(x_null)) for network_name, free_vars, ic_matrix, ic_vector, x_particular, x_null in matches]

        for match in results:
            free_variables[match[0]] = (match[1], match[2], match[3], match[4], match[5])

    return free_variables

def get_entry_exit_nodes(entries_exits_file, network_name):
    with open(entries_exits_file, 'r') as eef:
        pattern = fr'### Entry and exit nodes of {re.escape(network_name)}:\nEntry nodes: \[(.*?)\]\nExit nodes: \[(.*?)\]'
        match = re.search(pattern, eef.read(), re.DOTALL)

        if match:
            entry_nodes = [node.strip("'") for node in match.group(1).split(', ')]
            exit_nodes = [node.strip("'") for node in match.group(2).split(', ')]

        else:
            raise Exception(f'Network {network_name} not found in the `entries_exits.md` file')
    
    return entry_nodes, exit_nodes

def get_calibrators(additionals_file):
    add_tree = ET.parse(additionals_file)
    add_root = add_tree.getroot()

    calibrators = {} # id : edge
    calibrators_elems = [calibrator for calibrator in add_root.findall('calibrator')]
    for calibrator in calibrators_elems:
        calibrators[calibrator.get('id')] = calibrator.get('edge')

    return calibrators

def get_probability_distributions(num_routes):
    elements = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1]
    combinations = []

    for combo in product(elements, repeat=num_routes):
        if sum(combo) == 1:
            combinations.append(combo)

    combinations.sort(reverse=True)

    return combinations