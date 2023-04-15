"""Simulation Preparation

This script reads the location of the detectors from a spreadsheet and creates the calibrator objects in those positions, generating the file `detectors.add.xml` in the `sumo` folder.
It also prepares the simulation view, editing the file `vci.view.xml` in the `sumo` folder according to the parameters in the `config.ini` file.

"""

import sumolib
import operator
import pandas as pd
from pathlib import Path
import xml.etree.cElementTree as ET

from .utils import load_config, remove_chars, write_xml

def convert_coords_to_SUMO(network, coords):
    coords = remove_chars(coords, '()')
    long, lat = coords.split()

    return network.convertLonLat2XY(long, lat)

def get_closest_edge(network, x, y, radius):
    edges = network.getNeighboringEdges(x, y, radius)

    if len(edges) > 0:
        distancesAndEdges = [(dist, edge) for edge, dist in edges]
        distancesAndEdges.sort(key = operator.itemgetter(0))
        _, closestEdge = distancesAndEdges[0]

        return closestEdge.getID()
    else:
        raise Exception()

def gen_calibrators(df, network):
    radius = 50
    additional_tag = ET.Element('additional')

    output_dir = config.get('dir', 'OUTPUT', fallback='./output')
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')
    with open(coverage_file, 'w') as f:
        coverage = ''
        calib_id = 1

        for _, row in df.iterrows():
            sensor = row['Equipamento']
            coords = row['coordenadas']

            x, y = convert_coords_to_SUMO(network, coords)
            try:
                edge_id = get_closest_edge(network, x, y, radius)
            except Exception:
                print(f"No edges found within radius for the coordinates {coords}!")
                continue
            
            # TODO: Instead of a fixed pos, look for the closest node to the detector
            ET.SubElement(additional_tag, 'calibrator', id=f'calib_{calib_id}', edge=edge_id, pos='20', output=f'{output_dir}/calibrator_{calib_id}.xml')

            # define the edges whose flow is determined by the detector
            edge = network.getEdge(edge_id)
            coverage += f'\n### Edges covered by sensor {sensor}:\n'
            coverage += f'{edge_id}\n'

            previous_edges = list(edge.getIncoming().keys())
            following_edges = list(edge.getOutgoing().keys())

            while len(previous_edges) == 1:
                if len(list(previous_edges[0].getOutgoing().keys())) > 1:
                    break
                coverage += f'{previous_edges[0].getID()}\n'
                previous_edges = list(previous_edges[0].getIncoming().keys())

            while len(following_edges) == 1:
                if len(list(following_edges[0].getIncoming().keys())) > 1:
                    break
                coverage += f'{following_edges[0].getID()}\n'
                following_edges = list(following_edges[0].getOutgoing().keys())

            calib_id += 1

        f.write(coverage.strip())

    write_xml(additional_tag, config.get('sumo', 'CALIBRATORS', fallback='./sumo/calibrators.add.xml'))

def prepare_view():
    view_file = config.get('sumo', 'VIEW', fallback='./sumo/vci.view.xml')
    tree = ET.parse(view_file)
    root = tree.getroot()
    delay_elem = root.find('delay')
    delay_elem.set('value', config.get('params', 'DELAY', fallback='20'))
    write_xml(root, view_file)

if __name__ == '__main__':
    config = load_config()
    df = pd.read_excel(config.get('sensors', 'LOCATIONS', fallback='./data/sensor_locations.xlsx'))
    network = sumolib.net.readNet(config.get('sumo', 'NETWORK', fallback='./sumo/vci.net.xml'))

    gen_calibrators(df, network)
    prepare_view()