"""Equation System Solver

This script reads the equations of the VCI nodes from the file `equations.md` in the `docs` folder, presenting the free variables of each equation system.

"""

import sympy

from .utils import load_config, remove_chars, get_variables

def get_inequality_constraint_matrix(matrix, free_variables):
    ic_matrix = []
    for row in matrix:
        ic_row = []
        for index in free_variables.values():
            ic_row.append(row[index])
        ic_matrix.append(ic_row)
        
    return ic_matrix

if __name__ == '__main__':
    config = load_config()
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')
    free_variables_file = config.get('nodes', 'FREE_VARIABLES', fallback='./nodes/free_variables.md')

    with open(equations_file, 'r') as f:
        lines = f.readlines()

        with open(free_variables_file, 'w') as fv:
            for i, line in enumerate(lines):
                if line.startswith('###'):
                    current_node = remove_chars(line.strip(), '#:')
                    node_name = current_node.split(' - ')[0].split(' of ')[1].strip()
                    num_equations = int(current_node.split(' - ')[1])
                    equations = [remove_chars(eq.strip(), '$_{}\\') for eq in lines[i+1:i+num_equations+1]]

                    variables = get_variables(equations)
                    num_variables = len(variables)

                    matrix = []
                    for eq in equations:
                        row = [0] * num_variables
                        vars = remove_chars(eq, '=').split()
                        for k, var in enumerate(vars):
                            if var.startswith('x'):
                                pos = variables.index(var)
                                row[pos] = -1 if vars[k-1] == '-' else 1
                            elif var.startswith('-x'):
                                pos = variables.index(var[1:])
                                row[pos] = -1
                        
                        # append the constant side of the equation
                        constants = eq.split('=')[1].strip()
                        expr = sympy.parse_expr(constants)
                        row.append(expr)

                        matrix.append(row)

                    # find the reduced row echelon form of the matrix
                    matrix = sympy.Matrix(matrix).rref()

                    # find the free variables of the matrix
                    free_variables = {} # variable : index
                    for i in range(num_variables):
                        if i not in matrix[1]:
                            free_variables[variables[i]] = i

                    A_ub = get_inequality_constraint_matrix(matrix[0].tolist(), free_variables)
                    b_ub = [str(row[-1]) for row in matrix[0].tolist()]

                    # build the Xparticular vector
                    Xparticular = []
                    b_ub_index = 0
                    for i in range(num_variables):
                        if i not in matrix[1]:
                            Xparticular.append(['0'])
                        else:
                            Xparticular.append([b_ub[b_ub_index]])
                            b_ub_index += 1

                    # build the Xnull matrix
                    Xnull = []
                    A_ub_index = free_var_index = 0
                    for i in range(num_variables):
                        if i not in matrix[1]:
                            new_row = [0] * len(free_variables)
                            new_row[free_var_index] = 1
                            Xnull.append(new_row)
                            free_var_index += 1
                        else:
                            new_row = [-x for x in A_ub[A_ub_index]]
                            Xnull.append(new_row)
                            A_ub_index += 1

                    num_free_variables = num_variables - num_equations
                    if len(free_variables) != num_free_variables:
                        raise Exception(f"Number of free variables ({len(free_variables)}) is not equal to 'num_variables - num_equations' ({num_free_variables})")
                    
                    variables = sorted(list(variables), key=lambda x: int(x[1:]))

                    fv.write(f'### Free variables of {node_name}: {list(free_variables.keys())}\n')
                    fv.write(f'Inequality constraint matrix of {node_name}: {A_ub}\n')
                    fv.write(f'Inequality constraint vector of {node_name}: {b_ub}\n')
                    fv.write(f'Xparticular vector of {node_name}: {Xparticular}\n')
                    fv.write(f'Xnull matrix of {node_name}: {Xnull}\n')
                    fv.write(f'Equation variables of {node_name}: {variables}\n')
                    if i != len(lines) - 1: fv.write('\n')
                    print(f"The free variables of the equation system of node {node_name} are: {list(free_variables.keys())}")