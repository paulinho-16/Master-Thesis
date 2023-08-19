"""Digital Twin Implementation

This script contains all the logic of the VCI Digital Twin, running the simulations.

"""

import os, sys, time
import numpy as np
import pandas as pd
import json
import traci
import pickle
import sumolib
from pathlib import Path
from datetime import datetime
import xml.etree.cElementTree as ET

from .utils import load_config, get_eq_variables, get_network_sensors, get_sensors_coverage, get_free_variables, get_entry_exit_nodes, get_calibrators, get_probability_distributions, write_xml
import src.logic_functions as fn

# TODO: Initialization of the variables
# - for each permanent distribution, set an array with an array with two empty arrays and an array with a 0 element -> done
# - for each sensor, set two zeroed arrays of size 4 (carFlows, carSpeed, truckFlows, truckSpeed), for the new and old values -> done
# - for each entry and exit, set an empty array -> done
def initialize_variables(network_name, network_file, node_sensors, entries_exits_file):
    tree = ET.parse(network_file.replace('.net', '_poi'))
    root = tree.getroot()

    # initialize the variables for each router (permanent distribution)
    routers, perm_dists = {}, {}
    router_pois = [poi for poi in root.findall('poi') if poi.get('type') == 'router']
    for poi in router_pois:
        routers[poi.get('id')] = [poi.get('x'), poi.get('y'), poi.get('name')] # router_id : [x, y, edge]
        perm_dists[poi.get('id')] = [[[],[],[0]]]

    # initialize the variables for each sensor
    sensors = {} # id : [old_values, new_values, lane]
    for sensor in node_sensors.keys():
        sensors[sensor] = [[0,0,0,0], [0,0,0,0], node_sensors[sensor]]

    # store the IDs of the vehicles that entered and exited the network
    oldVehIDs = {} # node_id : [vehIDs]
    entry_nodes, exit_nodes = get_entry_exit_nodes(entries_exits_file, network_name)
    for node in entry_nodes + exit_nodes:
        oldVehIDs[node] = []

    return entry_nodes, exit_nodes, routers, perm_dists, sensors, oldVehIDs

# get the edges that serve as a continuation of an entry/exit edge
def get_linear_edges(network, edge_id):
    edges = [edge_id]
    previous_edges = list(network.getEdge(edge_id).getIncoming().keys())
    following_edges = list(network.getEdge(edge_id).getOutgoing().keys())

    while len(previous_edges) == 1:
        outgoing_edges = list(previous_edges[0].getOutgoing().keys())
        if len(outgoing_edges) > 1:
            break
        edges.append(previous_edges[0].getID())
        previous_edges = list(previous_edges[0].getIncoming().keys())

    while len(following_edges) == 1:
        incoming_edges = list(following_edges[0].getIncoming().keys())
        if len(incoming_edges) > 1:
            break
        edges.append(following_edges[0].getID())
        following_edges = list(following_edges[0].getOutgoing().keys())

    return edges

def get_node(network, flow_speed_min, edge_id):
    for node in flow_speed_min.keys():
        if flow_speed_min[node][0] == 'in' and edge_id in get_linear_edges(network, network.getNode(node).getOutgoing()[0].getID()):
            return node
        elif flow_speed_min[node][0] == 'out' and edge_id in get_linear_edges(network, network.getNode(node).getIncoming()[0].getID()):
            return node

def get_entry_exit_variables(entry_nodes, exit_nodes, variables):
    entry_exit_variables = {} # edge_id : (variable, flow)
    for node in entry_nodes:
        edge_id = network.getNode(node).getOutgoing()[0].getID()
        entry_exit_variables[edge_id] = (variables[edge_id]['root_var'], 0)
    for node in exit_nodes:
        edge_id = network.getNode(node).getIncoming()[0].getID()
        entry_exit_variables[edge_id] = (variables[edge_id]['root_var'], 0)

    return entry_exit_variables

def get_sensors_edges(network, sensors):
    sensors_edges = {} # edge_id : [sensor_id]
    for sensor, values in sensors.items():
        sensors_edges.setdefault(network.getLane(values[2]).getEdge().getID(), []).append(sensor)
    
    return sensors_edges

def get_covered_calibrators(calibrators, sensors_edges, covered_edges):
    covered_calibrators = {}
    for calib in calibrators.keys():
        for edges in covered_edges:
            if calibrators[calib] in edges:
                covered_calibrators[calib] = sensors_edges[edges[0]]
    
    return covered_calibrators

def get_sensors_data(network_name, sensors, data_file):
    sensors_dfs = {} # id : dataframe
    df_timestamp = pd.read_excel(data_file, sheet_name='timestamp').values.tolist()
    
    for sensor_id in sensors.keys():
        sheet_name = sensor_id.replace('CH', 'X').replace(':', '_').replace('.', '_') if network_name == 'Article' else sensor_id
        dataframe = pd.read_excel(data_file, sheet_name=sheet_name).values.tolist()
        sensors_dfs[sensor_id] = dataframe

    return df_timestamp, sensors_dfs

def get_week_days(timestamp_hours):
    days = set()
    weekdays = []

    for date_str in timestamp_hours:
        date_obj = datetime.strptime(date_str[0], '%Y-%m-%d-%H-%M')
        date_only_str = date_obj.strftime('%Y-%m-%d')
        if date_only_str not in days:
            days.add(date_only_str)
            weekdays.append(date_obj.strftime('%A'))
    
    return weekdays

def prepare_sumo(config, network_name):
    if 'SUMO_HOME' in os.environ:
        tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
        sys.path.append(tools)
    else:
        sys.exit("Please declare environment variable 'SUMO_HOME'")

    sumo_binary = config.get('sumo', 'BINARY', fallback='sumo-gui.exe')
    sumo_config = config.get('sumo', 'CONFIG_ARTICLE', fallback='./sumo/article.sumocfg') if network_name == 'Article' else config.get('sumo', 'CONFIG', fallback='./sumo/vci.sumocfg')

    return [sumo_binary, '-c', sumo_config, '--seed', str(28815), '--start', '1', '--quit-on-end', '1']

def reset_flow_speed_min(entry_nodes, exit_nodes):
    # reset the variables for the flow and speed in each entry and exit during the current minute
    flow_speed_min = {} # node_id : (in/out, flow, speed)
    for node in entry_nodes:
        flow_speed_min[node] = ('in', 0, 0)
    for node in exit_nodes:
        flow_speed_min[node] = ('out', 0, 0)

    return flow_speed_min

def get_flow_edges(entry_node, routers, network):
    from_edge = entry_node.getOutgoing()[0].getID()
    next_edge = from_edge
    router_found = False
    router_edges = [routers[router][2] for router in routers]
    while not router_found:
        to_node = network.getEdge(next_edge).getToNode()
        if len(to_node.getOutgoing()) == 0: # no routers in the possible paths from the entry edge
            break
        elif len(to_node.getOutgoing()) != 1:
            raise Exception(f"Possible missing router on edge {next_edge}.")

        next_edge = to_node.getOutgoing()[0].getID()
        if next_edge in router_edges:
            router_found = True
        to_edge = next_edge
    
    return from_edge, to_edge

def get_counting_edge(initial_edge):
    following_edges = list(initial_edge.getOutgoing().keys())

    while len(following_edges) == 1:
        incoming_edges = list(following_edges[0].getIncoming().keys())
        if len(incoming_edges) > 1:
            break

        start_edge = incoming_edges[0]
        next_edge = following_edges[0]
        following_edges = list(following_edges[0].getOutgoing().keys())

    return start_edge, next_edge

def generate_calibrators(calibrators_file, entry_nodes, routers, network):
    additional_tag = ET.Element('additional')
    calib_routes = {} # calibrator_id : route_id

    for entry in entry_nodes:
        entry_node = network.getNode(entry)
        output_file_car = f'{output_dir}/calibrator_car_{entry}.xml'
        output_file_truck = f'{output_dir}/calibrator_truck_{entry}.xml'
        entry_edge = entry_node.getOutgoing()[0]
        calib_pos = entry_edge.getLength()

        # define the route for the calibrator
        router_edges = [routers[router][2] for router in routers]
        paths = get_possible_paths(entry_edge.getID(), router_edges, network)
        if len(paths) != 1:
            raise Exception(f"Possible missing router on edge {entry_edge.getID()}.")
        route = paths[0]
        route_name = f'route_calib_{entry_edge.getID()}'
        ET.SubElement(additional_tag, 'route', id=route_name, edges=route)

        calib_car_tag = ET.SubElement(additional_tag, 'calibrator', id=f'calib_car_{entry}', vTypes='vtype_car', edge=entry_edge.getID(), pos=str(calib_pos), jamThreshold='0.5', output=output_file_car)
        calib_truck_tag = ET.SubElement(additional_tag, 'calibrator', id=f'calib_truck_{entry}', vTypes='vtype_truck', edge=entry_edge.getID(), pos=str(calib_pos), jamThreshold='0.5', output=output_file_truck)

        for begin_time in range(0, 86400, 60):
            end_time = begin_time + 60
            ET.SubElement(calib_car_tag, 'flow', begin=str(begin_time), end=str(end_time), route=route_name, vehsPerHour='180', speed='27.78', type='vtype_car', departPos='random_free', departSpeed='max')
            ET.SubElement(calib_truck_tag, 'flow', begin=str(begin_time), end=str(end_time), route=route_name, vehsPerHour='180', speed='27.78', type='vtype_truck', departPos='random_free', departSpeed='max')

        calib_routes[f'calib_car_{entry}'] = route_name
        calib_routes[f'calib_truck_{entry}'] = route_name

    write_xml(additional_tag, calibrators_file)

    return calib_routes

def generate_flows(flows_file, entry_nodes, routers, network):
    routes_tag = ET.Element('routes')
    routes_tag.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    routes_tag.set('xsi:noNamespaceSchemaLocation', 'http://sumo.dlr.de/xsd/routes_file.xsd')

    for entry in entry_nodes:
        entry_node = network.getNode(entry)
        from_edge, to_edge = get_flow_edges(entry_node, routers, network)
        ET.SubElement(routes_tag, 'flow', id=f'flow_car_{entry_node.getID()}', type='vtype_car', begin='0.00', end='86400.0', **{'from': from_edge}, to=to_edge, departPos='free', departSpeed='max', probability='0.20')
        ET.SubElement(routes_tag, 'flow', id=f'flow_truck_{entry_node.getID()}', type='vtype_truck', begin='0.00', end='86400.0', **{'from': from_edge}, to=to_edge, departPos='free', departSpeed='max', probability='0.10')

    write_xml(routes_tag, flows_file) 

def generate_routes(routes_file, routers, network):
    routes_tag = ET.Element('routes')
    routes_tag.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    routes_tag.set('xsi:noNamespaceSchemaLocation', 'http://sumo.dlr.de/xsd/routes_file.xsd')

    colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'white', 'black', 'gray', 'lightgray', 'darkgray', 'orange', 'brown', 'purple', 'pink']

    router_edges = [routers[router][2] for router in routers]
    for r, router in enumerate(routers):
        router_edge = routers[router][2]
        paths = get_possible_paths(router_edge, router_edges, network)
        for i, path in enumerate(paths):
            ET.SubElement(routes_tag, 'route', id=f'route_{router_edge}_{i}', edges=path, color=colors[r % len(colors)])

        distributions = get_probability_distributions(len(paths))

        for dist in distributions:
            dist_id = f'routedist_{router_edge}' + ''.join([f'_{int(d*100)}' for d in dist])
            route_dist_tag = ET.SubElement(routes_tag, 'routeDistribution', id=dist_id)
            for i, path in enumerate(paths):
                ET.SubElement(route_dist_tag, 'route', refId=f'route_{router_edge}_{i}', probability=f'{dist[i]}')

    write_xml(routes_tag, routes_file)

def get_possible_paths(edge_id, router_edges, network):
    paths = []
    visited = set()

    def dfs(current_edge, path):
        visited.add(current_edge)
        path.append(current_edge)

        # check if we reached the end of a route: a network exit or another router edge
        if len(current_edge.getOutgoing()) == 0 or (current_edge.getID() in router_edges and current_edge.getID() != edge_id):
            paths.append(' '.join([edge.getID() for edge in path]))
            path.pop()
            visited.remove(current_edge)
            return

        for successor_edge in current_edge.getOutgoing():
            if successor_edge not in visited:
                dfs(successor_edge, path)

        path.pop()
        visited.remove(current_edge)

    start_edge = network.getEdge(edge_id)
    dfs(start_edge, [])

    return paths

if __name__ == '__main__':
    config = load_config()
    network_name, network_file = config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml').split(',') # TODO: set the node that we want to analyse in the Makefile
    node_filename = network_file.split('.')[-3].split('/')[-1]
    network = sumolib.net.readNet(network_file)

    entries_exits_file = config.get('nodes', 'ENTRIES_EXITS', fallback='./nodes/entries_exits.md')
    network_sensors_file = config.get('nodes', 'SENSORS', fallback='./nodes/network_sensors.md')
    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')

    sensors_coverage = get_sensors_coverage(coverage_file)
    node_sensors = {}
    for sensor_id in get_network_sensors(network_sensors_file)[network_name]:
        node_sensors[sensor_id] = sensors_coverage[sensor_id][0]

    entry_nodes, exit_nodes, routers, perm_dists, sensors, oldVehIDs = initialize_variables(network_name, network_file, node_sensors, entries_exits_file)

    # TODO: criar ficheiro dos calibrators -> done
    output_dir = config.get('dir', 'OUTPUT', fallback='./output')
    calibrators_dir = config.get('dir', 'CALIBRATORS', fallback='./sumo/calibrators')
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(calibrators_dir).mkdir(parents=True, exist_ok=True)
    calibrators_file = f'{calibrators_dir}/calib_{node_filename}.add.xml'
    calib_routes = generate_calibrators(calibrators_file, entry_nodes, routers, network)

    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')
    eq_variables = get_eq_variables(network_name, equations_file)
    calibrators = get_calibrators(calibrators_file)
    data_file = config.get('sensors', 'DATA_ARTICLE', fallback='./data/article_data.xlsx') if network_name == 'Article' else config.get('sensors', 'DATA', fallback='./data/sensor_data.xlsx')
    free_variables_file = config.get('nodes', 'FREE_VARIABLES', fallback='./nodes/free_variables.md')
    intensities_file = config.get('nodes', 'INTENSITIES', fallback='./nodes/intensities.json')
    free_variables = get_free_variables(free_variables_file)
    free_variables_target = {var: 5 for var in free_variables[network_name][0]} # TODO: read the target values of the free variables from the Here API
    sensors_edges = get_sensors_edges(network, sensors)
    covered_edges = [edges[1] for sensor, edges in sensors_coverage.items() if sensor in node_sensors.keys()]
    covered_calibrators = get_covered_calibrators(calibrators, sensors_edges, covered_edges)
    nodes_dir = config.get('dir', 'NODES', fallback='./nodes')
    with open(f"{nodes_dir}/variables_{node_filename}.pkl", 'rb') as f:
        variables = pickle.load(f)
    variables_values = {} # variable : [flow, speed]
    entry_exit_variables = get_entry_exit_variables(entry_nodes, exit_nodes, variables)
    timestamp_hours, sensors_data = get_sensors_data(network_name, sensors, data_file)
    week_days = get_week_days(timestamp_hours)
    sumo_cmd = prepare_sumo(config, network_name)
    results_dir = config.get('dir', 'RESULTS', fallback='./sumo/results')
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    vehIDs_all = []

    # TODO: criar ficheiro dos flows iniciais -> done
    flows_dir = config.get('dir', 'FLOWS', fallback='./sumo/flows')
    Path(flows_dir).mkdir(parents=True, exist_ok=True)
    flows_file = f'{flows_dir}/flows_{node_filename}.xml'
    generate_flows(flows_file, entry_nodes, routers, network)

    # TODO: criar ficheiro das rotas -> done
    routes_dir = config.get('dir', 'ROUTES', fallback='./sumo/routes')
    Path(routes_dir).mkdir(parents=True, exist_ok=True)
    routes_file = f'{routes_dir}/routes_{node_filename}.xml'
    generate_routes(routes_file, routers, network)

    # TODO: ler intensidades do tráfego nas edges em questão
    with open(intensities_file, 'r') as int_file:
        intensities = json.load(int_file)

    current_day = current_hour = current_min = TTS = 0
    total_hours = int(config.get('params', 'HOURS', fallback='24'))
    time_clean = int(config.get('params', 'TIME_CLEAN', fallback='2400')) # seconds to wait and then remove old vehicles from the permanent distribution lists (routing control)
    time_sleep = int(config.get('params', 'TIME_SLEEP', fallback='0')) # slow down or speed up the simulation

    num_simplex_runs = int(config.get('params', 'NUM_SIMPLEX_RUNS', fallback='300'))
    step_length = float(config.get('params', 'STEP_LENGTH', fallback='0.25')) # seconds each step takes
    total_steps = total_hours * 3600 * (1/step_length)

    while current_hour < total_hours:
        print(f"Running simulation for hour {current_hour + 1} of {total_hours}")
        traci.start(sumo_cmd)

        controlFile = np.zeros((1, len(oldVehIDs) * 2 + 1)) # controlFile -> guarda os resultados periodicamente? -> o segundo número é o dobro de entradas e saídas, mais 1 para o TTS
        flow_speed_min = reset_flow_speed_min(entry_nodes, exit_nodes)

        # if current_hour > 0:
        #     fn.loadState(current_hour - 1)
        #         time.sleep(0.05)

        step = 0
        while step <= total_steps:
            traci.simulationStep()

            if step % (1/step_length) == 0: # a second has passed
                # TODO: update the flow in variables for each entry on the network -> done
                new_veh_ids = {} # node : [vehIDs]

                for node in entry_nodes:
                    start_edge, next_edge = get_counting_edge(network.getNode(node).getOutgoing()[0])
                    flow, speed, oldVehIDs[node], new_veh_ids[node] = fn.edgeVehParameters(start_edge.getID(), next_edge.getID(), oldVehIDs[node])
                    flow_speed_min[node] = (flow_speed_min[node][0], flow_speed_min[node][1] + flow, flow_speed_min[node][2] + speed) # TODO: somar speed porquê?

                # TODO: update the flow out variables for each exit on the network -> done
                for node in exit_nodes:
                    next_edge = network.getNode(node).getIncoming()[0]
                    start_edge = next_edge.getFromNode().getIncoming()[0]
                    flow, speed, oldVehIDs[node], _ = fn.edgeVehParameters(start_edge.getID(), next_edge.getID(), oldVehIDs[node])
                    flow_speed_min[node] = (flow_speed_min[node][0], flow_speed_min[node][1] + flow, flow_speed_min[node][2] + speed) # TODO: somar speed porquê?

            if step % (60 * (1/step_length)) == 0: # a minute has passed
                # TODO: # store locally (in pandas dataframe) simulation data recorded during the last minute
                if step > 0:
                    # TODO: for each of the entries/exits with sensors (qX - constants), get the total flow (cars + trucks) -> done
                    # TODO: for each of the entries/exits with sensors (qX - constants), get the speed (cars + trucks) -> done
                    for edge_id in sensors_edges.keys():
                        variables_values[variables[edge_id]['root_var']] = [0, 0]
                        speed_list = []
                        for sensor_id in sensors_edges[edge_id]:
                            variables_values[variables[edge_id]['root_var']][0] += sensors[sensor_id][1][0] + sensors[sensor_id][1][2] # update the flow of the variable
                            speed_list.extend([sensors[sensor_id][1][1], sensors[sensor_id][1][3]])

                        x = 0.001 + sum(s > 0 for s in speed_list)
                        variables_values[variables[edge_id]['root_var']][1] = sum(speed_list) / x # update the speed of the variable

                    # TODO: np.vstack of "controlFile" variable (25 values), first the main entries/exits (real/simulated values), then rounded TTS, then the remaining entries/exits -> done
                    controlFile_list = []
                    for edge_id in sorted(sensors_edges.keys()): # save the flow values of the sensor edges
                        node = get_node(network, flow_speed_min, edge_id)
                        controlFile_list.extend([variables_values[variables[edge_id]['root_var']][0], flow_speed_min[node][1] * 60])
                    
                    controlFile_list.append(round(TTS)) # TODO: understand what TTS means and how it is updated

                    for edge_id in sorted(entry_exit_variables.keys()): # save the flow values of the remaining entry and exit edges
                        if not any(edge_id in lst[1] for lst in sensors_coverage.values()):
                            node = get_node(network, flow_speed_min, edge_id)
                            if variables[edge_id]['root_var'] in free_variables_order:
                                var_index = free_variables_order.index(variables[edge_id]['root_var'])
                                controlFile_list.extend([closest_feasible_X_free_relative_error[var_index], flow_speed_min[node][1] * 60])
                            else:
                                var_index = eq_variables.index(variables[edge_id]['root_var'])
                                controlFile_list.extend([Xcomplete[var_index][0], flow_speed_min[node][1] * 60])
                    
                    controlFile = np.vstack([controlFile, controlFile_list])

                    # TODO: reset values of the flows and speedSums of the minute to zero -> done
                    flow_speed_min = reset_flow_speed_min(entry_nodes, exit_nodes)

                # TODO: fill the vectors of each detector (array of size 4) with the values read from the real data -> done
                for sensor_id in sensors.keys():
                    for i in range(4):
                        sensors[sensor_id][1][i] = sensors_data[sensor_id][current_min][i]

                # TODO: for each of the main entries/exits (qX - constants I guess), get the total flow (cars + trucks) -> repeated with the first line after the step>0 condition - maybe move up -> done
                for edge_id in sensors_edges.keys():
                    variables_values[variables[edge_id]['root_var']] = [0, 0]
                    for sensor_id in sensors_edges[edge_id]:
                        variables_values[variables[edge_id]['root_var']][0] += sensors[sensor_id][1][0] + sensors[sensor_id][1][2] # update the flow of the variable

                # TODO: define the intensity levels of the free variables based on the current hour of the day -> done
                for var in free_variables[network_name][0]:
                    week_day = week_days[current_day]
                    free_variables_target[var] = intensities[network_name][week_day][var][current_hour % 24]

                # TODO: apply the Simplex algorithm
                while True:
                    # TODO: calculate the closest feasible error, that gives the values for the free variables -> done
                    Xnull = free_variables[network_name][4]
                    free_variables_order = sorted(list(free_variables_target.keys()), key=lambda x: int(x[1:]))
                    closest_feasible_X_free_relative_error, targets, Xparticular = fn.restrictedFreeVarRange(variables_values, free_variables_order, free_variables_target, free_variables[network_name][1], free_variables[network_name][2], free_variables[network_name][3], Xnull, num_simplex_runs)

                    # TODO: calculate the solution for the entire equation system (Xcomplete), by defining the matrices Xparticular and Xnull -> done
                    Xnull_cols = []
                    for i in range(len(free_variables_target)):
                        Xnull_cols.append(np.array([[row[i]] for row in Xnull]))

                    Xcomplete = Xparticular.astype(np.float64)
                    for i in range(len(free_variables_target)):
                        Xcomplete += closest_feasible_X_free_relative_error[i] * Xnull_cols[i]

                    # TODO: if all variables are positive, break the loop (solution found?) -> done
                    if np.all(Xcomplete >= 0):
                        break
                
                # TODO: update TTS -> done
                TTS += (traci.vehicle.getIDCount()) * (60 / 3600)

                # TODO: generate (calibrate) traffic flows - set flows of the calibrators in the entries of the network (for cars and trucks)
                for calib_id in calibrators.keys():
                    if calib_id in covered_calibrators.keys():
                        if '_car_' in calib_id:
                            flow_idx, speed_idx, veh_type = 0, 1, 'vtype_car'
                        elif '_truck_' in calib_id:
                            flow_idx, speed_idx, veh_type = 2, 3, 'vtype_truck'
                        
                        v_calib = [sensors[sensor_id][1][speed_idx] / 3.6 for sensor_id in covered_calibrators[calib_id]]
                        x = 0.001 + sum(x > 0 for x in v_calib)
                        vehsPerHour = 0
                        for sensor_id in covered_calibrators[calib_id]:
                            vehsPerHour += sensors[sensor_id][1][flow_idx]
                        speed = sum(v_calib) / x
                        traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, vehsPerHour, speed, veh_type, calib_routes[calib_id], departLane='free', departSpeed='max')
                    else:
                        var_index = free_variables_order.index(variables[calibrators[calib_id]]['root_var'])
                        if '_car_' in calib_id:
                            traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, closest_feasible_X_free_relative_error[var_index], 22.22, 'vtype_car', calib_routes[calib_id], departLane='free', departSpeed='max')
                        elif '_truck_' in calib_id: # TODO: porquê que mete o fluxo a zero para trucks?
                            traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, 0, 22.22, 'vtype_truck', calib_routes[calib_id], departLane='free', departSpeed='max')
                
                current_min += 1

                # TODO: for each SUMO router, calculate the route distribution probabilities on its bifurcations
                prob_dists = {} # router_id : {edge_id : prob_dist}
                for router in routers.keys():
                    var = variables[routers[router][2]]['root_var']
                    if var.startswith('q'):
                        var_value = variables_values[var][0]
                    elif var.startswith('x'):
                        var_value = float(Xcomplete[eq_variables.index(var)][0])

                    prob_dists[router] = {}
                    if var_value != 0:
                        split_edges = list(network.getEdge(routers[router][2]).getOutgoing().keys())
                        if len(split_edges) != 2: # TODO: como lidar com casos em que a edge se divide em mais do que duas?
                            raise Exception(f"Router {router} in split with more than 2 outgoing edges. Please adapt the network so that each split has only 2 outgoing edges.")
                        
                        var_index_1 = eq_variables.index(variables[split_edges[0].getID()]['root_var'])
                        prob_dists[router][split_edges[0].getID()] = int((np.round(10 * (Xcomplete[var_index_1]) / var_value)) * 10)
                        prob_dists[router][split_edges[1].getID()] = int(100 - prob_dists[router][split_edges[0].getID()])
                    else:
                        prob_dists[router][split_edges[0].getID()] = 50
                        prob_dists[router][split_edges[1].getID()] = 50

                # TODO: averiguar se a ordem de escrita dos valores prob não varia
                r_dists = {} # router_id : route_distribution_name
                for router in routers.keys():
                    first_prob, second_prob = prob_dists[router].values()
                    r_dists[router] = f'routedist_{routers[router][2]}_{first_prob}_{second_prob}'

            if step % (1/step_length) == 0: # write results of the second?
                if step % (60 * (1/step_length)) == 0: # is this condition really needed?
                    # TODO: add flags/markers to vehicles with routes assigned
                    sim_time = round(traci.simulation.getTime())
                    total_veh_ids = [vehID for sublist in new_veh_ids.values() for vehID in sublist]

                    if step == 0:
                        # TODO: initialize temporary empty array for each route distribution -> done
                        temp_dists = {} # router_id : [temp_dist]
                        for router in routers.keys():
                            temp_dists[router] = []

                        # TODO: append new vehicles on the network entries, route distributions, and simulation time to each array -> done
                        for router in routers.keys():
                            temp_dists[router].append([total_veh_ids, [r_dists[router]], [sim_time]])
                    else:
                        # TODO: for each router, check if new vehicles entered the network, and if so, append to the permanent distribution array -> done
                        for router in routers.keys():
                            if len(temp_dists[router][0][0]) != 0:
                                perm_dists[router].append(temp_dists[router][0])
                            temp_dists[router] = []
                            temp_dists[router].append([total_veh_ids, [r_dists[router]], [sim_time]])
                
                # TODO: for each new vehicle inserted in each entry, append it to the temporary array of each distribution -> done
                for veh_list in new_veh_ids.values():
                    for veh_id in veh_list:
                        for router in routers.keys():
                            temp_dists[router][0][0].append(veh_id)

                # TODO: DFC mechanism
                if step > 0:
                    if sim_time % time_clean == 0:
                        # TODO: get the ID list of all vehicles currently running within the scenario -> done
                        vehIDs_all = traci.vehicle.getIDList()

                    # TODO: for each distribution, dinamically assign routes to the vehicles according to the probability distribution model -> done
                    for router in routers.keys():
                        edgeStartPlusOne = routers[router][2] # TODO: qual a edgeStart a enviar? Para já envio a edge do router
                        incoming_edges = network.getEdge(edgeStartPlusOne).getFromNode().getIncoming()
                        if len(incoming_edges) != 1:
                            raise Exception(f"Router {router}'s edge {edgeStartPlusOne} has more than one incoming edge. Please adapt the network so that it has only one incoming edge.")
                        temp_dists[router], perm_dists[router] = fn.routingDinamically(edgeStartPlusOne, temp_dists[router], perm_dists[router], edgeStartPlusOne, time_clean, sim_time, vehIDs_all)

                    vehIDs_all = []

            # TODO: slow down or speed up the simulation based on the predefined value -> done
            time.sleep(time_sleep)

            if step % (3600 * (1/step_length)) == 0 and step > 0: # an hour has passed
                # TODO: store the "controlFile" content in an Excel file
                df_content = {}
                index = 0
                for edge_id in sorted(sensors_edges.keys()):
                    df_content[f'f_{edge_id}_ref'] = controlFile[1:, index]
                    df_content[f'f_{edge_id}'] = controlFile[1:, index + 1]
                    index += 2
                df_content['TTS'] = controlFile[1:, index]
                index += 1
                for edge_id in sorted(entry_exit_variables.keys()):
                    if not any(edge_id in lst[1] for lst in sensors_coverage.values()):
                        df_content[f'f_{edge_id}_ref'] = controlFile[1:, index]
                        df_content[f'f_{edge_id}'] = controlFile[1:, index + 1]
                        index += 2

                df = pd.DataFrame(df_content)

                # fn.saveState(current_hour)  # one can save simulation state e.g., each hour (simulation can be thus reloaded and simulated from this point in time)
                TTS = 0
                save_data_time = timestamp_hours[current_hour][0] # TODO: era current_hour - 1, mas não parece fazer sentido, vai buscar o último timestamp
                df.to_excel(f'{results_dir}/flow_{save_data_time}.xlsx', index=False)
                controlFile = np.zeros((1, len(oldVehIDs) * 2 + 1))
                current_hour += 1
                current_day += current_hour // 24

            step += 1

        traci.close()