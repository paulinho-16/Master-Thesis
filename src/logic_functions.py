import traci
import numpy as np
from sympy import sympify
from scipy.optimize import linprog

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

def calc_list_expr(b_con_expr, variables_values):
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

    return b_con

def calc_x_particular(Xparticular_expr, variables_values):
    Xparticular = []
    for i in range(len(Xparticular_expr)):
        Xparticular.append(calc_list_expr(Xparticular_expr[i], variables_values))

    return Xparticular

def calc_x_complete(free_variables_target, Xparticular, Xnull, new_x):
    Xnull_cols = []
    for i in range(len(free_variables_target)):
        Xnull_cols.append(np.array([[row[i]] for row in Xnull]))

    Xcomplete = Xparticular.astype(np.float64)
    for i in range(len(free_variables_target)):
        Xcomplete += new_x[i] * Xnull_cols[i]

    return Xcomplete

def freeVarRange(free_variables_target, A_con, b_con, Xparticular, Xnull, num_simplex_runs):
    X_free_range = np.zeros((len(free_variables_target), 1))

    for i in range(num_simplex_runs):
        c = np.array([np.random.uniform(-1,1) for _ in range(len(free_variables_target))])
        res = linprog(c, A_ub=A_con, b_ub=b_con)

        if res.success == True:
            new_x = (np.round(res.x)).reshape(len(free_variables_target), 1)
            Xcomplete = calc_x_complete(free_variables_target, Xparticular, Xnull, new_x)

            # for some unknown reason, linprog sometimes returns a solution with negative values (even if the linear program is constrained to be positive), check if this is the case and just ignore that solution
            xx = 0
            for kk in Xcomplete:
                xx += kk < 0

            if xx == 0:
                if i == 0:
                    X_free_range[:, 0] = new_x[:, 0]
                else:
                    X_free_range = np.hstack((X_free_range, new_x))
            else:
                print("Negative solution generated during first iteration")

    return X_free_range

def restrictedFreeVarRange(variables_values, free_variables_target, A_con, b_con_expr, Xparticular_expr, Xnull, num_simplex_runs):
    free_variables_order = sorted(list(free_variables_target.keys()), key=lambda x: int(x[1:]))
    A_con = np.array(A_con)
    b_con = np.array(calc_list_expr(b_con_expr, variables_values))
    Xparticular = np.array(calc_x_particular(Xparticular_expr, variables_values))

    X_free_range = freeVarRange(free_variables_target, A_con, b_con, Xparticular, Xnull, num_simplex_runs)
    X_free_bound_feasible = np.zeros((len(free_variables_target), 1))

    d_vars = {}
    a0_vars = {}
    vars_bin = {}
    for i, var in enumerate(free_variables_order):
        d_vars[var] = (np.nanmax(X_free_range[i,:]) - np.nanmin(X_free_range[i,:])) / 9
        a0_vars[var] = np.nanmin(X_free_range[i,:])
        vars_bin[var] = []

    for k in range (0, 10):
        for i, var in enumerate(free_variables_order):
            vars_bin[var].append(a0_vars[var] + k * d_vars[var])

    ii = 0
    for i in range(num_simplex_runs):
        i_vars = [np.random.randint(0,10) for _ in range(len(free_variables_target))]

        vars_bounds = []
        for i, var in enumerate(free_variables_order):
            vars_bounds.append((np.floor(vars_bin[var][i_vars[i]]), np.floor(vars_bin[var][i_vars[i]] + d_vars[var])))

        c = np.array([np.random.uniform(-1,1) for _ in range(len(free_variables_target))])
        res = linprog(c, A_ub=A_con, b_ub=b_con, bounds=vars_bounds)

        if res.success == True:
            new_x = (np.round(res.x)).reshape(len(free_variables_target), 1)
            Xcomplete = calc_x_complete(free_variables_target, Xparticular, Xnull, new_x)

            # for some unknown reason, linprog sometimes returns a solution with negative values (even if the linear program is constrained to be positive), check if this is the case and just ignore that solution
            xx = 0
            for kk in Xcomplete:
                xx += kk < 0

            if xx == 0:
                if ii == 0:
                    X_free_bound_feasible[:, 0] = new_x[:, 0]
                    ii = 1
                else:
                    X_free_bound_feasible = np.hstack((X_free_bound_feasible, new_x))
            else:
                print("Negative solution generated during second iteration")

    for i, var in enumerate(free_variables_order):
        vars_bin[var] = np.floor(vars_bin[var])

    targets = {}
    for i, var in enumerate(free_variables_order):
        targets[var] = vars_bin[var][free_variables_target[var]]

    target_vec = np.array([[targets[var]] for var in free_variables_order])
    norm_target = np.linalg.norm(target_vec, axis=0)
    norm_diff_target_feasible_array = np.linalg.norm(X_free_bound_feasible - target_vec, axis=0)
    relative_error = norm_diff_target_feasible_array / norm_target

    relative_error_index = relative_error.argmin()
    closest_feasible_X_free_relative_error = X_free_bound_feasible[:, relative_error_index]

    return closest_feasible_X_free_relative_error, targets, Xparticular