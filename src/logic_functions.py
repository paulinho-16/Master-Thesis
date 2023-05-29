import traci

def edgeVehParameters(start_edge, next_edge, oldVehIDs): # TODO: não fazer distinção entre entry e exit nodes?
    # for small time step should capture only one veh on detector with the length of 5 [m]
    intersection = set(oldVehIDs).intersection(traci.edge.getLastStepVehicleIDs(next_edge))

    if len(list(intersection)) != 0:
        for idVeh in list(intersection):
            indexVeh = oldVehIDs.index(idVeh)
            del oldVehIDs[indexVeh]
    
    currentVehIDs = traci.edge.getLastStepVehicleIDs(start_edge)
    newVehIDs = []
    for vehID in currentVehIDs:
        if vehID not in oldVehIDs:
            newVehIDs.append(vehID)
    
    flow = speed = 0
    for vehID in newVehIDs:
        speed += traci.vehicle.getSpeed(vehID)
        oldVehIDs.append(vehID)
        flow += 1
        
    return flow, speed, oldVehIDs, newVehIDs