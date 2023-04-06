"""Variable Definitions

TODO: write description

"""

import sumolib

from .utils import load_config

def get_entry_exit_nodes(nodes):
    entry_nodes = []
    exit_nodes = []

    for node in nodes:
        if len(node.getIncoming()) == 0: # if it has no incoming edges, it is an entry node
            entry_nodes.append(node)
        elif len(node.getOutgoing()) == 0: # if it has no outgoing edges, it is an exit node
            exit_nodes.append(node)
    
    return entry_nodes, exit_nodes

if __name__ == '__main__':
    config = load_config()
    network = sumolib.net.readNet(config.get('nodes', 'NODE_ARTICLE', fallback='./nodes/no_artigo.net.xml'))

    entry_nodes, exit_nodes = get_entry_exit_nodes(network.getNodes())
    print(f"Found {len(entry_nodes)} entry nodes and {len(exit_nodes)} exit nodes.")

    print("Entry nodes:")
    print([entry.getID() for entry in entry_nodes])

    print("Exit nodes:")
    print([exit.getID() for exit in exit_nodes])