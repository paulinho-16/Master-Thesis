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
import xml.etree.cElementTree as ET

from .utils import load_config, get_node_sensors, get_sensors_coverage, get_free_variables, get_entry_exit_nodes, get_calibrators
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
        routers[poi.get('id')] = [poi.get('x'), poi.get('y'), poi.get('name')]
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

        controlFile = np.zeros((1, len(oldVehIDs)*2 + 1)) # controlFile -> guarda os resultados periodicamente? -> o segundo número é o dobro de entradas e saídas, mais 1 para o TTS
        flow_speed_min = reset_flow_speed_min(entry_nodes, exit_nodes)

        step = 0
        while step <= total_steps:
            traci.simulationStep()

            if step % (1/step_length) == 0: # a second has passed
                # TODO: update the flow in variables for each entry on the network -> done
                for node in entry_nodes:
                    start_edge = network.getNode(node).getOutgoing()[0]
                    next_edge = start_edge.getToNode().getOutgoing()[0]
                    flow, speed, oldVehIDs[node], newVehIDs = fn.edgeVehParameters(start_edge.getID(), next_edge.getID(), oldVehIDs[node]) # TODO: newVehIDs é usado para quê?
                    flow_speed_min[node] = (flow_speed_min[node][0], flow_speed_min[node][1] + flow, flow_speed_min[node][2] + speed) # TODO: somar speed porquê?

                # TODO: update the flow out variables for each exit on the network -> done
                for node in exit_nodes:
                    next_edge = network.getNode(node).getIncoming()[0]
                    start_edge = next_edge.getFromNode().getIncoming()[0]
                    flow, speed, oldVehIDs[node], newVehIDs = fn.edgeVehParameters(start_edge.getID(), next_edge.getID(), oldVehIDs[node]) # TODO: newVehIDs é usado para quê?
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
                    for edge_id in sensors_edges.keys(): # save the flow values of the sensor edges
                        controlFile_list.extend([variables_values[variables[edge_id]['root_var']][0], flow_speed_min[node][1] * 60])
                    controlFile_list.append(round(TTS)) # TODO: understand what TTS means and how it is updated
                    for edge_id in entry_exit_variables.keys(): # save the flow values of the remaining entry and exit edges
                        if not any(edge_id in lst[1] for lst in sensors_coverage.values()):
                            controlFile_list.extend([entry_exit_variables[edge_id][1], flow_speed_min[node][1] * 60]) # TODO: no código do artigo usa Xcomplete nalgumas vars, adaptar isso
                    
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

                # TODO: for each SUMO router, calculate the route distribution probabilities on its bifurcations (but how many routers, and where?)

            if step % (1/step_length) == 0: # write results of the second?
                if step % (60 * (1/step_length)) == 0: # is this condition really needed?
                    # TODO: add flags/markers to vehicles with routes assigned
                    sim_time = round(traci.simulation.getTime())
                    if step == 0:
                        # TODO: initialize temporary empty array for each route distribution
                        # TODO: append new vehicles on the entries/calibrators, route probabilities, and simulation time to each array
                        pass
                    else:
                        # TODO: for each distribution, check if new vehicles entered the network, and if so, append to the permanent distribution array
                        # then empty the respective temporary array of that distribution, set current_routes_dist and reappend the new vehicles, route distributions and simulation time
                        pass
                
                # TODO: for each new vehicle inserted in each entry, append it to the temporary array of each distribution

                # TODO: DFC mechanism
                if step > 0:
                    if sim_time % time_clean == 0: 
                        # get the ID list of all vehicles currently running within the scenario
                        pass

                    # TODO: for each distribution, dinamically assign routes to the vehicles according to the probability distribution model

            # TODO: slow down or speed up the simulation based on the predefined value
            time.sleep(time_sleep)

            if step % (3600 * (1/step_length)) == 0 and step > 0: # an hour has passed
                # TODO: store the "controlFile" content in an Excel file
                # TODO: reset the "controlFile" variable
                current_hour += 1

            step += 1

        traci.close()