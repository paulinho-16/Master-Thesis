import traci
import numpy as np
from sympy import sympify

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

def calc_inequality_constraint_vector(b_con_expr, variables_values):
    b_con = []
    for i in range(len(b_con_expr)):
        if b_con_expr[i] in variables_values:
            value = variables_values[b_con_expr[i]][0]
            b_con.append(int(value))
        else:
            variables = variables_values.keys()
            expr = sympify(b_con_expr[i])
            expr = expr.subs([(symbol, variables_values[symbol][0]) for symbol in variables])
            b_con.append(int(expr))

    return np.array(b_con)

def restrictedFreeVarRange(variables_values, A_con, b_con_expr):
    A_con = np.array(A_con)
    b_con = calc_inequality_constraint_vector(b_con_expr, variables_values)
    # TODO: continuar a desenvolver função