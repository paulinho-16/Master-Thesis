"""Digital Twin Implementation

This script contains all the logic of the VCI Digital Twin, running the simulations.

"""

import os, sys
import traci

from .utils import load_config

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
    
    current_hour = 0
    total_hours = int(config.get('params', 'HOURS', fallback='24'))

    while(current_hour < total_hours):
        print(f"Running simulation for hour {current_hour + 1} of {total_hours}")
        traci.start(sumo_cmd)

        step = 0
        while step < 1000:
            traci.simulationStep()

            step += 1

        traci.close()