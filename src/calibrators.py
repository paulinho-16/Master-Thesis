"""Calibrators Generator

This script reads the location of the detectors from a spreadsheet and creates the calibrator objects in those positions, generating the file `detectors.add.xml` in the `sumo` folder.

"""

import sumolib
import operator
import pandas as pd
import xml.etree.cElementTree as ET

from .utils import load_config, remove_chars

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

def write_xml(body):
    ET.indent(body, space='\t')
    tree = ET.ElementTree(body)
    tree.write(config.get('sumo', 'CALIBRATORS', fallback='./sumo/calibrators.add.xml'))

def gen_calibrators(df, network):
    radius = 50

    additional_tag = ET.Element("additional")

    for i, coords in enumerate(df['coordenadas'].values):
        x, y = convert_coords_to_SUMO(network, coords)
        try:
            edge_id = get_closest_edge(network, x, y, radius)
        except Exception:
            print(f'No edges found within radius for the coordinates {coords}!')

        # TODO: Apparently the `output` attribute only accepts directories now, check if it works
        # ET.SubElement(additional_tag, "calibrator", id=f'calib_{i+1}', edge=edge_id, pos='30', output=f"{config.get('dir', 'OUTPUT', fallback='../output')}/calibrator_{i+1}.xml")
        # TODO: Instead of a fixed pos, look for the closest node to the detector
        ET.SubElement(additional_tag, "calibrator", id=f'calib_{i+1}', edge=edge_id, pos='20', output=f"{config.get('dir', 'OUTPUT', fallback='./output')}")

    write_xml(additional_tag)


if __name__ == '__main__':
    config = load_config()
    df = pd.read_excel(config.get('sensors', 'LOCATIONS', fallback='./data/sensor_locations.xlsx'))
    network = sumolib.net.readNet(config.get('sumo', 'NETWORK', fallback='./sumo/vci.net.xml.gz'))

    gen_calibrators(df, network)