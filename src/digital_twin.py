"""Digital Twin Implementation

This script contains all the logic of the VCI Digital Twin, running the simulations.

"""

import os, re, sys, time
import numpy as np
import pandas as pd
import traci
import pickle
import herepy
import sumolib
import requests
import xml.etree.cElementTree as ET

from .utils import load_config, get_sensors_coverage, get_free_variables
import src.logic_functions as fn

# TODO: Initialization of the variables
# - for each permanent distribution, set an array with an array with two empty arrays and an array with a 0 element -> done
# - for each detector, set two zeroed arrays of size 4 (carFlows, carSpeed, truckFlows, truckSpeed), for the new and old values -> done
# - for each entry and exit, set an empty array -> done
def initialize_variables(node_name, network_file, additionals_file, entries_exits_file):
    # initialize the variables for each router (permanent distribution)
    tree = ET.parse(network_file.replace('.net', '_poi'))
    root = tree.getroot()

    routers, perm_dists = {}, {}
    router_pois = [poi for poi in root.findall('poi') if poi.get('type') == 'router']
    for poi in router_pois:
        routers[poi.get('id')] = [poi.get('x'), poi.get('y'), poi.get('name')]
        perm_dists[poi.get('id')] = [[[],[],[0]]]

    # initialize the variables for each sensor
    add_tree = ET.parse(additionals_file)
    add_root = add_tree.getroot()

    calibrators = {} # id : [old_values, new_values, lane]
    calibrators_elems = [calibrator for calibrator in add_root.findall('calibrator')]
    for calibrator in calibrators_elems:
        calibrators[calibrator.get('id')] = [[0,0,0,0], [0,0,0,0], calibrator.get('lane')]

    # store the IDs of the vehicles that entered and exited the network
    oldVehIDs = {} # node_id : [vehIDs]
    with open(entries_exits_file, 'r') as eef:
        pattern = fr'### Entry and exit nodes of {re.escape(node_name)}:\nEntry nodes: \[(.*?)\]\nExit nodes: \[(.*?)\]'
        match = re.search(pattern, eef.read(), re.DOTALL)

        if match:
            entry_nodes = [node.strip("'") for node in match.group(1).split(', ')]
            exit_nodes = [node.strip("'") for node in match.group(2).split(', ')]

            for node in entry_nodes + exit_nodes:
                oldVehIDs[node] = []
        else:
            raise Exception(f'Node {node_name} not found in the `entries_exits.md` file')

    return entry_nodes, exit_nodes, routers, perm_dists, calibrators, oldVehIDs

def get_entry_exit_variables(entry_nodes, exit_nodes, variables):
    entry_exit_variables = {} # edge_id : (variable, flow)
    for node in entry_nodes:
        edge_id = network.getNode(node).getOutgoing()[0].getID()
        entry_exit_variables[edge_id] = (variables[edge_id]['root_var'], 0)
    for node in exit_nodes:
        edge_id = network.getNode(node).getIncoming()[0].getID()
        entry_exit_variables[edge_id] = (variables[edge_id]['root_var'], 0)

    return entry_exit_variables

def get_calibrators_edges(network, calibrators):
    calibrators_edges = {} # edge_id : [calibrator_id]
    for calibrator_id, values in calibrators.items():
        calibrators_edges.setdefault(network.getLane(values[2]).getEdge().getID(), []).append(calibrator_id)
    
    return calibrators_edges

def get_calibrators_data(calibrators, data_file):
    calibrators_dfs = {} # id : dataframe
    df_timestamp = pd.read_excel(data_file, sheet_name='timestamp').values.tolist()
    
    for calibrator_id in calibrators.keys():
        dataframe = pd.read_excel(data_file, sheet_name=calibrator_id).values.tolist()
        calibrators_dfs[calibrator_id] = dataframe

    return df_timestamp, calibrators_dfs

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
    additionals_file = config.get('sumo', 'CALIBRATORS_ARTICLE', fallback='./sumo/calibrators_article.add.xml') # TODO: definir qual o ficheiro de additionals com base na rede utilizada
    entries_exits_file = config.get('nodes', 'ENTRIES_EXITS', fallback='./nodes/entries_exits.md')
    data_file = config.get('sensors', 'DATA_ARTICLE', fallback='./data/article_data.xlsx') if node_name == 'Article' else config.get('sensors', 'DATA', fallback='./data/sensor_data.xlsx')
    free_variables_file = config.get('nodes', 'FREE_VARIABLES', fallback='./nodes/free_variables.md')
    sensors_coverage = get_sensors_coverage(coverage_file)
    free_variables = get_free_variables(free_variables_file)
    free_variables_target = {var: 5 for var in free_variables[node_name][0]} # TODO: read the target values of the free variables from the Here API
    entry_nodes, exit_nodes, routers, perm_dists, calibrators, oldVehIDs = initialize_variables(node_name, network_file, additionals_file, entries_exits_file)
    calibrators_edges = get_calibrators_edges(network, calibrators)
    nodes_dir = config.get('dir', 'NODES', fallback='./nodes')
    with open(f"{nodes_dir}/variables_{network_file.split('.')[-3].split('/')[-1]}.pkl", 'rb') as f:
        variables = pickle.load(f)
    variables_values = {} # variable : [flow, speed]
    entry_exit_variables = get_entry_exit_variables(entry_nodes, exit_nodes, variables)
    timestamp_hours, calibrators_data = get_calibrators_data(calibrators, data_file)
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
                    # TODO: for each of the entries/exits with calibrators (qX - constants), get the total flow (cars + trucks) -> done
                    # TODO: for each of the entries/exits with calibrators (qX - constants), get the speed (cars + trucks) -> done
                    for edge_id in calibrators_edges.keys():
                        variables_values[variables[edge_id]['root_var']] = [0, 0]
                        speed_list = []
                        for calibrator_id in calibrators_edges[edge_id]:
                            variables_values[variables[edge_id]['root_var']][0] += calibrators[calibrator_id][1][0] + calibrators[calibrator_id][1][2] # update the flow of the variable
                            speed_list.extend([calibrators[calibrator_id][1][1], calibrators[calibrator_id][1][3]])

                        x = 0.001 + sum(s > 0 for s in speed_list)
                        variables_values[variables[edge_id]['root_var']][1] = sum(speed_list) / x # update the speed of the variable

                    # TODO: np.vstack of "controlFile" variable (25 values), first the main entries/exits (real/simulated values), then rounded TTS, then the remaining entries/exits -> done
                    controlFile_list = []
                    for edge_id in calibrators_edges.keys(): # save the flow values of the calibrators edges
                        controlFile_list.extend([variables_values[variables[edge_id]['root_var']][0], flow_speed_min[node][1] * 60])
                    controlFile_list.append(round(TTS)) # TODO: understand what TTS means and how it is updated
                    for edge_id in entry_exit_variables.keys(): # save the flow values of the remaining entry and exit edges
                        if not any(edge_id in lst for lst in sensors_coverage.values()):
                            controlFile_list.extend([entry_exit_variables[edge_id][1], flow_speed_min[node][1] * 60]) # TODO: no código do artigo usa Xcomplete nalgumas vars, adaptar isso
                    
                    controlFile = np.vstack([controlFile, controlFile_list])

                    # TODO: reset values of the flows and speedSums of the minute to zero -> done
                    flow_speed_min = reset_flow_speed_min(entry_nodes, exit_nodes)

                # TODO: fill the vectors of each detector (array of size 4) with the values read from the real data -> done
                for calibrator_id in calibrators.keys():
                    for i in range(4):
                        calibrators[calibrator_id][1][i] = calibrators_data[calibrator_id][current_min][i]

                # TODO: for each of the main entries/exits (qX - constants I guess), get the total flow (cars + trucks) -> repeated with the first line after the step>0 condition - maybe move up -> done
                for edge_id in calibrators_edges.keys():
                    variables_values[variables[edge_id]['root_var']] = [0, 0]
                    for calibrator_id in calibrators_edges[edge_id]:
                        variables_values[variables[edge_id]['root_var']][0] += calibrators[calibrator_id][1][0] + calibrators[calibrator_id][1][2] # update the flow of the variable

                # TODO: define the intensity levels of the free variables based on the current hour of the day
                for var in free_variables[node_name][0]:
                    free_variables_target[var] = 5 # TODO: read the target values of the free variables from the Here API and depending on the hour of the day

                # TODO: apply the Simplex algorithm
                while True:
                    # TODO: calculate the closest feasible error, that gives the values for the free variables
                    closest_feasible_X_free_relative_error = fn.restrictedFreeVarRange(variables_values, free_variables[node_name][1], free_variables[node_name][2], free_variables[node_name][3], free_variables[node_name][4], num_simplex_runs)
                    # closest_feasible_X_free_relative_error = fn.restrictedFreeVarRange(q1,q2,q3,q4,q5,q6, num_simplex_runs, target_idx_x6, target_idx_x11,target_idx_x12, target_idx_x14, target_idx_x15, target_idx_x16)
                    
                    # TODO: to calculate the solution for the entire equation system (Xcomplete), define the matrices Xparticular and Xnull

                    # TODO: if all variables are positive, break the loop (solution found?)
                    # if np.all(Xcomplete >= 0):
                    #     break
                    break
                
                # TODO: update TTS
                # TODO: generate (calibrate) traffic flows - set flows of the calibrators (for cars and trucks)
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