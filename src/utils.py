import re
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

def get_eq_variables(node_name, equations_file):
    with open(equations_file, 'r') as f:
        lines = f.readlines()

        for i, line in enumerate(lines):
            if line.startswith('###'):
                current_node = remove_chars(line.strip(), '#:')
                eq_node_name = current_node.split(' - ')[0].split(' of ')[1].strip()
                if eq_node_name == node_name:
                    num_equations = int(current_node.split(' - ')[1])
                    equations = [remove_chars(eq.strip(), '$_{}\\') for eq in lines[i+1:i+num_equations+1]]
                    variables = get_variables(equations)
                    break
    
    return variables

def get_node_sensors(node_sensors_file):
    node_sensors = {} # node : [sensors]
    with open(node_sensors_file, 'r') as f:
        lines = f.readlines()

        for line in lines:
            if line.startswith('###'):
                node = line.split('Sensors of')[-1].strip()[:-1]
                node_sensors[node] = []
            elif line != '\n':
                node_sensors[node].append(line.strip())

    return node_sensors

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
    free_variables = {} # node : ([free variables], [inequality constraint matrix], [inequality constraint vector], [Xparticular], [Xnull])
    with open(free_variables_file, 'r') as f:
        content = f.read()

        pattern = r"### Free variables of (.+?): (\[.+?\])\nInequality constraint matrix of [^:]+: (\[\[.*?\]\])\nInequality constraint vector of [^:]+: (\[.+?\])\nXparticular vector of [^:]+: (\[\[.*?\]\])\nXnull matrix of [^:]+: (\[\[.*?\]\])"
        matches = re.findall(pattern, content, re.DOTALL)
        results = [(node, eval(free_vars), eval(ic_matrix), eval(ic_vector), eval(x_particular), eval(x_null)) for node, free_vars, ic_matrix, ic_vector, x_particular, x_null in matches]

        for match in results:
            free_variables[match[0]] = (match[1], match[2], match[3], match[4], match[5])

    return free_variables

def get_entry_exit_nodes(entries_exits_file, node_name):
    with open(entries_exits_file, 'r') as eef:
        pattern = fr'### Entry and exit nodes of {re.escape(node_name)}:\nEntry nodes: \[(.*?)\]\nExit nodes: \[(.*?)\]'
        match = re.search(pattern, eef.read(), re.DOTALL)

        if match:
            entry_nodes = [node.strip("'") for node in match.group(1).split(', ')]
            exit_nodes = [node.strip("'") for node in match.group(2).split(', ')]

        else:
            raise Exception(f'Node {node_name} not found in the `entries_exits.md` file')
    
    return entry_nodes, exit_nodes

def get_calibrators(additionals_file):
    add_tree = ET.parse(additionals_file)
    add_root = add_tree.getroot()

    calibrators = {} # id : edge
    calibrators_elems = [calibrator for calibrator in add_root.findall('calibrator')]
    for calibrator in calibrators_elems:
        calibrators[calibrator.get('id')] = calibrator.get('edge')

    return calibrators