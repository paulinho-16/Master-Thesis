"""Digital Twin Implementation

This script contains all the logic of the VCI Digital Twin, running the simulations.

"""

import os, sys, time
import numpy as np
import pandas as pd
import traci
import pickle
import herepy
import sumolib
import requests
from pathlib import Path
import xml.etree.cElementTree as ET

from .utils import load_config, get_eq_variables, get_node_sensors, get_sensors_coverage, get_free_variables, get_entry_exit_nodes, get_calibrators
import src.logic_functions as fn

# TODO: Initialization of the variables
# - for each permanent distribution, set an array with an array with two empty arrays and an array with a 0 element -> done
# - for each detector, set two zeroed arrays of size 4 (carFlows, carSpeed, truckFlows, truckSpeed), for the new and old values -> done
# - for each entry and exit, set an empty array -> done
def initialize_variables(node_name, network_file, node_sensors, entries_exits_file):
    # initialize the variables for each router (permanent distribution)
    tree = ET.parse(network_file.replace('.net', '_poi'))
    root = tree.getroot()

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
    entry_nodes, exit_nodes = get_entry_exit_nodes(entries_exits_file, node_name)
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

def get_sensors_data(node_name, sensors, data_file):
    sensors_dfs = {} # id : dataframe
    df_timestamp = pd.read_excel(data_file, sheet_name='timestamp').values.tolist()
    
    for sensor_id in sensors.keys():
        sheet_name = sensor_id.replace('CH', 'X').replace(':', '_').replace('.', '_') if node_name == 'Article' else sensor_id
        dataframe = pd.read_excel(data_file, sheet_name=sheet_name).values.tolist()
        sensors_dfs[sensor_id] = dataframe

    return df_timestamp, sensors_dfs

def prepare_sumo(config, node_name):
    if 'SUMO_HOME' in os.environ:
        tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
        sys.path.append(tools)
    else:
        sys.exit("Please declare environment variable 'SUMO_HOME'")

    sumo_binary = config.get('sumo', 'BINARY', fallback='sumo-gui.exe')
    sumo_config = config.get('sumo', 'CONFIG_ARTICLE', fallback='./sumo/article.sumocfg') if node_name == 'Article' else config.get('sumo', 'CONFIG', fallback='./sumo/vci.sumocfg')

    return [sumo_binary, '-c', sumo_config, '--seed', str(28815), '--start', '1', '--quit-on-end', '1']

def reset_flow_speed_min(entry_nodes, exit_nodes):
    # reset the variables for the flow and speed in each entry and exit during the current minute
    flow_speed_min = {} # node_id : (in/out, flow, speed)
    for node in entry_nodes:
        flow_speed_min[node] = ('in', 0, 0)
    for node in exit_nodes:
        flow_speed_min[node] = ('out', 0, 0)

    return flow_speed_min

def get_traffic_intensity(api_key, coordinates):
    base_url = 'https://traffic.ls.hereapi.com/traffic/6.3/flow.json'
    params = {
        'apiKey': api_key,
        'bbox': f'{coordinates[0]},{coordinates[1]},{coordinates[2]},{coordinates[3]}',
    }

    print(base_url, '-', params)

    response = requests.get(base_url, params=params)
    data = response.json()

    print('RESPONSE DATA')
    print(data)

    if 'RWS' in data and 'RW' in data['RWS'][0] and 'CF' in data['RWS'][0]['RW'][0]:
        jam_factor = data['RWS'][0]['RW'][0]['CF'][0]['JF']
        return jam_factor
    else:
        return None

def experimentar_api():
    network = sumolib.net.readNet(config.get('sumo', 'NETWORK', fallback='./sumo/vci.net.xml'))

    # get the latitude and longitude of the nodes of a given edge in SUMO
    coords_from = network.getEdge('915252792').getFromNode().getCoord()
    coords_to = network.getEdge('915252792').getToNode().getCoord()

    # convert the coords to latitude and longitude
    latitude_start = network.convertXY2LonLat(coords_from[0], coords_from[1])[1]
    longitude_start = network.convertXY2LonLat(coords_from[0], coords_from[1])[0]
    latitude_end = network.convertXY2LonLat(coords_to[0], coords_to[1])[1]
    longitude_end = network.convertXY2LonLat(coords_to[0], coords_to[1])[0]

    print(latitude_start, longitude_start)
    print(latitude_end, longitude_end)

    here_api = herepy.TrafficApi('jVB_JfWYklIufkIHgaEGNg')
    start_coord = [latitude_start, longitude_start]
    end_coord = [latitude_end, longitude_end]

    print(f'{start_coord}-{end_coord}')

    api_key = 'SGLZFO2SFShUtNG4aGSjjBrR1W-VjqYFKrvDMRxXfuk'
    coordinates = [start_coord[0], start_coord[1], end_coord[0], end_coord[1]]
    traffic_intensity = get_traffic_intensity(api_key, coordinates)
    if traffic_intensity is not None:
        print(f"Traffic Intensity (Jam Factor) for Coordinates {coordinates}: {traffic_intensity}")
    else:
        print("Unable to retrieve traffic intensity for the specified location.")

    print(f"Average Traffic Intensity: {traffic_intensity}")

if __name__ == '__main__':
    config = load_config()
    node_name, network_file = config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml').split(',') # TODO: set the node that we want to analyse in the Makefile
    network = sumolib.net.readNet(network_file)
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')
    eq_variables = get_eq_variables(node_name, equations_file)
    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')
    calibrators_dir = config.get('dir', 'CALIBRATORS', fallback='./sumo/calibrators')
    additionals_file = f"{calibrators_dir}/calib_{network_file.split('.')[-3].split('/')[-1]}.add.xml"
    calibrators = get_calibrators(additionals_file)
    entries_exits_file = config.get('nodes', 'ENTRIES_EXITS', fallback='./nodes/entries_exits.md')
    data_file = config.get('sensors', 'DATA_ARTICLE', fallback='./data/article_data.xlsx') if node_name == 'Article' else config.get('sensors', 'DATA', fallback='./data/sensor_data.xlsx')
    free_variables_file = config.get('nodes', 'FREE_VARIABLES', fallback='./nodes/free_variables.md')
    node_sensors_file = config.get('nodes', 'SENSORS', fallback='./nodes/node_sensors.md')
    sensors_coverage = get_sensors_coverage(coverage_file)
    node_sensors = {}
    for sensor_id in get_node_sensors(node_sensors_file)[node_name]:
        node_sensors[sensor_id] = sensors_coverage[sensor_id][0]
    free_variables = get_free_variables(free_variables_file)
    free_variables_target = {var: 5 for var in free_variables[node_name][0]} # TODO: read the target values of the free variables from the Here API
    entry_nodes, exit_nodes, routers, perm_dists, sensors, oldVehIDs = initialize_variables(node_name, network_file, node_sensors, entries_exits_file)
    sensors_edges = get_sensors_edges(network, sensors)
    covered_calibrators = {}
    for calib in calibrators.keys():
        if calibrators[calib] in sensors_edges.keys():
            covered_calibrators[calib] = sensors_edges[calibrators[calib]]
    nodes_dir = config.get('dir', 'NODES', fallback='./nodes')
    with open(f"{nodes_dir}/variables_{network_file.split('.')[-3].split('/')[-1]}.pkl", 'rb') as f:
        variables = pickle.load(f)
    variables_values = {} # variable : [flow, speed]
    entry_exit_variables = get_entry_exit_variables(entry_nodes, exit_nodes, variables)
    timestamp_hours, sensors_data = get_sensors_data(node_name, sensors, data_file)
    sumo_cmd = prepare_sumo(config, node_name)
    results_dir = config.get('dir', 'RESULTS', fallback='./sumo/results')
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    vehIDs_all = []

    # experimentar_api() # TODO: apagar função após meter requests da API a funcionar

    current_hour = current_min = TTS = 0
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
                    start_edge = network.getNode(node).getOutgoing()[0]
                    next_edge = start_edge.getToNode().getOutgoing()[0]
                    flow, speed, oldVehIDs[node], newVehIDs = fn.edgeVehParameters(start_edge.getID(), next_edge.getID(), oldVehIDs[node])
                    new_veh_ids[node] = newVehIDs
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

                # TODO: define the intensity levels of the free variables based on the current hour of the day
                for var in free_variables[node_name][0]:
                    free_variables_target[var] = 5 # TODO: read the target values of the free variables from the Here API and depending on the hour of the day

                # TODO: apply the Simplex algorithm
                while True:
                    # TODO: calculate the closest feasible error, that gives the values for the free variables -> done
                    Xnull = free_variables[node_name][4]
                    free_variables_order = sorted(list(free_variables_target.keys()), key=lambda x: int(x[1:]))
                    closest_feasible_X_free_relative_error, targets, Xparticular = fn.restrictedFreeVarRange(variables_values, free_variables_order, free_variables_target, free_variables[node_name][1], free_variables[node_name][2], free_variables[node_name][3], Xnull, num_simplex_runs)

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
                        # TODO: definir rotas como route_cali_E_NS5...
                        traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, vehsPerHour, speed, veh_type, 'route_cali_E_NS5', departLane='free', departSpeed='max')
                    else:
                        var_index = free_variables_order.index(variables[calibrators[calib_id]]['root_var'])
                        if '_car_' in calib_id:
                            traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, closest_feasible_X_free_relative_error[var_index], 22.22, 'vtype_car', 'route_cali_N_ES152_onRamp1', departLane='free', departSpeed='max')
                        elif '_truck_' in calib_id: # TODO: porquê que mete o fluxo a zero para trucks?
                            traci.calibrator.setFlow(calib_id, step * step_length, (step * step_length) + 60, 0, 22.22, 'vtype_truck', 'route_cali_N_ES152_onRamp1', departLane='free', departSpeed='max')
                
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

                # TODO: criar ficheiros com as routes distributions
                # TODO: averiguar se a ordem de escrita dos valores prob não varia
                r_dists = {} # router_id : route_distribution_name
                for router in routers.keys():
                    first_prob, second_prob = prob_dists[router].values()
                    r_dists[router] = f'routedist_{router}_{first_prob}_{second_prob}'

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
                            # temp_dists[router].append()

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
                        edgeStartPlusOne = routers[router][2] # TODO: qual a edgeStart a enviar? Pode ser a do router? Ou a anterior? Para já envio a anterior
                        incoming_edges = network.getEdge(edgeStartPlusOne).getFromNode().getIncoming()
                        if len(incoming_edges) != 1:
                            raise Exception(f"Router {router}'s edge {edgeStartPlusOne} has more than one incoming edge. Please adapt the network so that it has only one incoming edge.")
                        edgeStart = incoming_edges[0].getID()
                        edgeStart_extra = "APAGAR" # TODO: ver que edges meter aqui
                        temp_dists[router], perm_dists[router] = fn.routingDinamically(edgeStart, temp_dists[router], perm_dists[router], edgeStart_extra, time_clean, sim_time, vehIDs_all)

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

            step += 1

        traci.close()