"""Equation System Solver

This script reads the equations of the VCI nodes from the file `equations.md` in the `docs` folder, presenting the free variables of each equation system.

"""

import sympy

from .utils import load_config, remove_chars

def get_variables(equations):
    variables = set()
    for eq in equations:
        vars = remove_chars(eq, '+-=').split()
        for var in vars:
            if var.startswith('x'):
                variables.add(var)
    
    variables = sorted(list(variables), key=lambda x: int(x[1:]))
    return variables


if __name__ == '__main__':
    config = load_config()
    equations_file = config.get('nodes', 'EQUATIONS', fallback='./nodes/equations.md')
    free_variables_file = config.get('nodes', 'FREE_VARIABLES', fallback='./nodes/free_variables.md')

    with open(equations_file, 'r') as f:
        lines = f.readlines()

        # open free_variables.md file
        with open(free_variables_file, 'w') as fv:
            for i, line in enumerate(lines):
                if line.startswith('###'):
                    current_node = remove_chars(line.strip(), '#:')
                    node_name = current_node.split(' - ')[0].split(' of ')[1].strip()
                    num_equations = int(current_node.split(' - ')[1])
                    equations = [remove_chars(eq.strip(), '$_{}\\') for eq in lines[i+1:i+num_equations+1]]

                    variables = get_variables(equations)
                    num_variables = len(variables)

                    print(variables) # TODO: apagar print

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
                    
                    for row in matrix: # TODO: apagar print
                        print(row)

                    # find the reduced row echelon form of the matrix
                    matrix = sympy.Matrix(matrix).rref()

                    # find the free variables of the matrix
                    free_variables = [variables[i] for i in range(num_variables) if i not in matrix[1]]

                    num_free_variables = num_variables - num_equations
                    if len(free_variables) != num_free_variables:
                        raise Exception(f"Number of free variables ({len(free_variables)}) is not equal to 'num_variables - num_equations' ({num_free_variables})")
                    
                    fv.write(f'### Equations of {node_name}: {free_variables}\n')
                    print(f"The free variables of the equation system of node {node_name} are: {free_variables}")