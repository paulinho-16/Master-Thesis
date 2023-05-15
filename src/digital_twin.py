"""Digital Twin Implementation

This script contains all the logic of the VCI Digital Twin, running the simulations.

"""

import os, sys
import time
import traci
import xml.etree.cElementTree as ET

from .utils import load_config

# TODO: Initialization of the variables
# - for each permanent distribution, set an array with an array with two empty arrays and an array with a 0 element
# - for each detector, set two zeroed arrays of size 4 (carFlows, carSpeed, truckFlows, truckSpeed), for the new and old values

def initialize_variables(network_file):
    tree = ET.parse(network_file.replace('.net', '_poi'))
    root = tree.getroot()

    # initialize the variables for each router (permanent distribution)
    routers, perm_dists = {}, {}
    router_pois = [poi for poi in root.findall('poi') if poi.get('type') == 'router']
    for poi in router_pois:
        routers[poi.get('id')] = [poi.get('x'), poi.get('y'), poi.get('name')]
        perm_dists[poi.get('id')] = [[[],[],[0]]]

    return routers, perm_dists

def prepare_sumo(config):
    if 'SUMO_HOME' in os.environ:
        tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
        sys.path.append(tools)
    else:
        sys.exit("Please declare environment variable 'SUMO_HOME'")

    sumo_binary = config.get('sumo', 'BINARY', fallback='sumo-gui.exe')
    sumo_config = config.get('sumo', 'CONFIG', fallback='./sumo/vci.sumocfg')

    return [sumo_binary, '-c', sumo_config, '--seed', str(28815), '--start', '1', '--quit-on-end', '1']


if __name__ == '__main__':
    config = load_config()
    sumo_cmd = prepare_sumo(config)
    node_name, network_file = config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml').split(',') # TODO: set the node that we want to analyse in the Makefile
    routers, perm_dists = initialize_variables(network_file)
    
    current_hour = 0
    total_hours = int(config.get('params', 'HOURS', fallback='24'))
    time_clean = int(config.get('params', 'TIME_CLEAN', fallback='2400')) # seconds to wait and then remove old vehicles from the permanent distribution lists (routing control)
    time_sleep = int(config.get('params', 'TIME_SLEEP', fallback='0')) # slow down or speed up the simulation

    step_length = float(config.get('params', 'STEP_LENGTH', fallback='0.25')) # seconds each step takes
    total_steps = total_hours * 3600 * (1/step_length)

    while current_hour < total_hours:
        print(f"Running simulation for hour {current_hour + 1} of {total_hours}")
        traci.start(sumo_cmd)
        step = 0

        while step <= total_steps:
            traci.simulationStep()

            if step % (1/step_length) == 0: # a second has passed
                # TODO: update the flow in variables for each entry on the network
                # TODO: update the flow out variables for each exit on the network
                pass

            if step % (60 * (1/step_length)) == 0: # a minute has passed
                # TODO: # store locally (in pandas dataframe) simulation data recorded during the last minute

                # TODO: understand the step>0 condition: what differs?
                if step > 0:
                    # TODO: for each of the main entries/exits (qX - constants I guess), get the total flow (cars + trucks)
                    # TODO: for each of the main entries/exits (qX - constants I guess), get the speed (cars + trucks)
                    # TODO: np.vstack of "controlFile" variable (25 values), first the main entries/exits (real/simulated values), then rounded TTS, then the remaining entries/exits
                    # TODO: understand what TTS means and how it is updated
                    # TODO: reset values of the flows and speedSums of the minute to zero
                    pass

                # TODO: fill the vectors of each detector (array of size 4) with the values read from the real data
                # TODO: for each of the main entries/exits (qX - constants I guess), get the total flow (cars + trucks) -> repeated with the first line after the step>0 condition - maybe move up
                # TODO: define the intensity levels of the free variables based on the current hour of the day
                # TODO: apply the Simplex algorithm
                while True:
                    # TODO: calculate the closest feasible error, that gives the values for the free variables
                    # TODO: to calculate the solution for the entire equation system (Xcomplete), define the matrices Xparticular and Xnull

                    # TODO: if all variables are positive, break the loop (solution found?)
                    # if np.all(Xcomplete >= 0):
                    #     break
                    pass
                
                # TODO: update TTS
                # TODO: generate (calibrate) traffic flows - set flows of the calibrators (for cars and trucks)
                # TODO: update timeID (number of minutes?)

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