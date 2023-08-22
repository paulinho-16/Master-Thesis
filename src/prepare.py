"""Simulation Preparation

This script reads the location of the detectors from a spreadsheet and derives the corresponding network coverage of the sensors.
It also creates the calibrator objects in the network entries, generating the corresponding files in the `sumo/calibrators` folder.
It prepares the simulation view, editing the file `vci.view.xml` in the `sumo` folder according to the parameters in the `config.ini` file.
It also prepares sensor data, grouping counts into 1-minute blocks.

"""

import sumolib
import operator
import xlsxwriter
import numpy as np
import pandas as pd
from pathlib import Path
import xml.etree.cElementTree as ET

from .utils import load_config, remove_chars, write_xml

def convert_coords_to_SUMO(network, coords):
    coords = remove_chars(coords, '()')
    long, lat = coords.split()

    return network.convertLonLat2XY(long, lat)

def get_closest_edge(network, x, y, radius): # TODO: passar a usar apenas a get_closest_lane, é preciso adaptar os dados da VCI para lanes (coordenadas para cada uma)
    edges = network.getNeighboringEdges(x, y, radius)

    if len(edges) > 0:
        distancesAndEdges = [(dist, edge) for edge, dist in edges]
        distancesAndEdges.sort(key = operator.itemgetter(0))
        _, closestEdge = distancesAndEdges[0]

        return closestEdge.getID()
    else:
        raise Exception()
    
def get_closest_lane(network, x, y, radius):
    lanes = network.getNeighboringLanes(x, y, radius)

    if len(lanes) > 0:
        distancesAndLanes = [(dist, lane) for lane, dist in lanes]
        distancesAndLanes.sort(key=operator.itemgetter(0))
        _, closestLane = distancesAndLanes[0]

        return closestLane.getID()
    else:
        raise Exception()
    
def gen_entry_exit_nodes(network_name, nodes, eef):
    entry_nodes = []
    exit_nodes = []

    for node in nodes:
        incoming_edges = node.getIncoming()
        outgoing_edges = node.getOutgoing()

        if len(incoming_edges) == 0: # if it has no incoming edges, it is an entry node
            entry_nodes.append(node)
        elif len(outgoing_edges) == 0: # if it has no outgoing edges, it is an exit node
            exit_nodes.append(node)
        elif len(incoming_edges) == 1 and len(outgoing_edges) == 1 and not node.getConnections(): # case where it is simultaneously an entry and exit node (dead end, but with an entry and an exit of the network)
            entry_nodes.append(node)
            exit_nodes.append(node)
    
    print(f"\nFound {len(entry_nodes)} entry nodes and {len(exit_nodes)} exit nodes for the network node {network_name}.")
    print(f"Entry nodes: {[entry.getID() for entry in entry_nodes]}")
    print(f"Exit nodes: {[exit.getID() for exit in exit_nodes]}")

    # register the entry and exit nodes in the `entries_exits.md` file
    eef.write(f'### Entry and exit nodes of {network_name}:\n')
    eef.write(f'Entry nodes: {[entry.getID() for entry in entry_nodes]}\n')
    eef.write(f'Exit nodes: {[exit.getID() for exit in exit_nodes]}\n\n')

def gen_coverage(df, network, network_article):
    radius = 50
    coverage_file = config.get('sensors', 'COVERAGE', fallback='./sumo/coverage.md')

    with open(coverage_file, 'w') as f:
        coverage = ''
        for _, row in df.iterrows():
            network_name = row['Network']
            sensor = row['Equipamento']
            coords = row['coordenadas']

            x, y = convert_coords_to_SUMO(network, coords) if network_name == 'VCI' else convert_coords_to_SUMO(network_article, coords)
            try:
                # edge_id = get_closest_edge(network, x, y, radius) if network_name == 'VCI' else get_closest_lane(network_article, x, y, radius)
                edge_id = get_closest_lane(network, x, y, radius) if network_name == 'VCI' else get_closest_lane(network_article, x, y, radius)
            except Exception:
                print(f"No edges found within radius for the coordinates {coords}!")
                continue

            # define the edges whose flow is determined by the detector
            # edge = network.getEdge(edge_id) if network_name == 'VCI' else network_article.getLane(edge_id).getEdge()
            edge = network.getLane(edge_id).getEdge() if network_name == 'VCI' else network_article.getLane(edge_id).getEdge()
            coverage += f'\n### Edges covered by sensor {sensor} ({edge_id}):\n'
            coverage += f'{edge.getID()}\n'

            previous_edges = list(edge.getIncoming().keys())
            following_edges = list(edge.getOutgoing().keys())

            while len(previous_edges) == 1:
                outgoing_edges = list(previous_edges[0].getOutgoing().keys())
                if len(outgoing_edges) > 1:
                    break
                coverage += f'{previous_edges[0].getID()}\n'
                previous_edges = list(previous_edges[0].getIncoming().keys())

            while len(following_edges) == 1:
                incoming_edges = list(following_edges[0].getIncoming().keys())
                if len(incoming_edges) > 1:
                    break
                coverage += f'{following_edges[0].getID()}\n'
                following_edges = list(following_edges[0].getOutgoing().keys())

        f.write(coverage.strip())

def prepare_view():
    view_file = config.get('sumo', 'VIEW', fallback='./sumo/vci.view.xml')
    tree = ET.parse(view_file)
    root = tree.getroot()
    delay_elem = root.find('delay')
    delay_elem.set('value', config.get('params', 'DELAY', fallback='20'))
    write_xml(root, view_file)

def prepare_data():
    data_dir = config.get('dir', 'DATA', fallback='./data')
    data_file = f'{data_dir}/sensor_data.xlsx'
    workbook = xlsxwriter.Workbook(data_file)
    timestamp_sheet = workbook.add_worksheet('timestamp')
    days = np.empty(shape=(0,))

    # define the formats
    format = {'align': 'vcenter', 'valign': 'center'}
    base_format = workbook.add_format(format)
    format.update({'bold': True, 'border': 1, 'bottom': 1, 'right': 1})
    header_format = workbook.add_format(format)

    print(f"\n::: Starting processing sensor data :::\n")
    for file in Path(data_dir).iterdir():
        if file.is_dir():
            sensor = file.name
            worksheet_name = sensor if len(sensor) <= 31 else sensor[:31] # max sheet name length is 31
            if sensor == 'CAV401-2;CAV401-1' or sensor == 'AEDL - A1 297+975 CT3687' or sensor == 'AEDL - A1 300+250 CT3688':
                sensor_sheet_c = workbook.add_worksheet(f'{worksheet_name}_C')
                sensor_sheet_d = workbook.add_worksheet(f'{worksheet_name}_D')
            else:
                sensor_sheet = workbook.add_worksheet(worksheet_name)

            print(f"Processing data from the sensor {sensor}...")

            columns = ['carFlows', 'carSpeeds', 'truckFlows', 'truckSpeeds']
            result = pd.DataFrame(columns=columns)
            timestamp_days = np.array([])
            for data_sheet in file.iterdir():
                if data_sheet.is_file() and data_sheet.suffix == '.xlsx':
                    worksheets = pd.ExcelFile(data_sheet).sheet_names
                    for sheet_name in worksheets:
                        if sheet_name.startswith('Traffic'):
                            df = pd.read_excel(data_sheet, sheet_name=sheet_name)

                            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                            timestamp_days = np.append(timestamp_days, df['Timestamp'].dt.strftime('%Y-%m-%d').unique())

                            df['vehicle_type'] = df['classe_ep'].map({'A': 'car', 'B': 'car', 'C': 'truck', 'D': 'truck'}) if 'classe_ep' in df.columns else df['VehicleTypeId'].map({3: 'car', 4: 'car', 5: 'truck', 6: 'truck'}) # TODO: verify if the car and truck classes are correctly mapped
                            df.set_index('Timestamp', inplace=True)

                            count_id_col = 'trans_id' if 'trans_id' in df.columns else 'MedidasCCVDetailId'
                            speed_col = 'speed' if 'speed' in df.columns else 'Velocidade'

                            if sensor == 'CAV401-2;CAV401-1' or sensor == 'AEDL - A1 297+975 CT3687' or sensor == 'AEDL - A1 300+250 CT3688':
                                # Separate the data into two dataframes based on direction
                                if sensor == 'CAV401-2;CAV401-1':
                                    df_direction_c = df[(df['SensorCCVId'] == 76) | (df['SensorCCVId'] == 77) | (df['SensorCCVId'] == 78)]
                                    df_direction_d = df[(df['SensorCCVId'] == 73) | (df['SensorCCVId'] == 74) | (df['SensorCCVId'] == 75)]
                                if sensor == 'AEDL - A1 297+975 CT3687' or sensor == 'AEDL - A1 300+250 CT3688':
                                    df_direction_c = df[df['lane_direction'] == 'C']
                                    df_direction_d = df[df['lane_direction'] == 'D']

                                # Group and calculate for direction C
                                grouped_c = df_direction_c.groupby(['vehicle_type', pd.Grouper(freq='1T')])

                                result_sheet_c = pd.DataFrame({
                                    'carFlows': grouped_c[count_id_col].count()['car'],
                                    'carSpeeds': grouped_c[speed_col].mean()['car'],
                                    'truckFlows': grouped_c[count_id_col].count()['truck'],
                                    'truckSpeeds': grouped_c[speed_col].mean()['truck']
                                })

                                # Group and calculate for direction D
                                grouped_d = df_direction_d.groupby(['vehicle_type', pd.Grouper(freq='1T')])

                                result_sheet_d = pd.DataFrame({
                                    'carFlows': grouped_d[count_id_col].count()['car'],
                                    'carSpeeds': grouped_d[speed_col].mean()['car'],
                                    'truckFlows': grouped_d[count_id_col].count()['truck'],
                                    'truckSpeeds': grouped_d[speed_col].mean()['truck']
                                })

                                # Combine the results into separate dataframes
                                result_c = result_sheet_c.fillna(0)
                                result_d = result_sheet_d.fillna(0)

                            grouped = df.groupby(['vehicle_type', pd.Grouper(freq='1T')])

                            result_sheet = pd.DataFrame({
                                'carFlows': grouped[count_id_col].count()['car'],
                                'carSpeeds': grouped[speed_col].mean()['car'],
                                'truckFlows': grouped[count_id_col].count()['truck'],
                                'truckSpeeds': grouped[speed_col].mean()['truck']
                            })
                            result = pd.concat([result, result_sheet], ignore_index=True)
                            result = result.fillna(0)

            if days.size == 0:
                days = timestamp_days
            elif not np.array_equal(days, timestamp_days):
                print(f"Inconsistent timestamps in folder {sensor}!")

            # create the sensor worksheet
            if sensor == 'CAV401-2;CAV401-1' or sensor == 'AEDL - A1 297+975 CT3687' or sensor == 'AEDL - A1 300+250 CT3688':
                sensor_sheet_c.set_column('A:D', 15)
                sensor_sheet_d.set_column('A:D', 15)
                for title_cell, title_name, value_cell in [('A1', 'carFlows', 'A2'), ('B1', 'carSpeeds', 'B2'), ('C1', 'truckFlows', 'C2'), ('D1', 'truckSpeeds', 'D2')]:
                    sensor_sheet_c.write(title_cell, title_name, header_format)
                    sensor_sheet_d.write(title_cell, title_name, header_format)
                    sensor_sheet_c.write_column(value_cell, result_c[title_name], base_format)
                    sensor_sheet_d.write_column(value_cell, result_d[title_name], base_format)
            else:
                sensor_sheet.set_column('A:D', 15)
                for title_cell, title_name, value_cell in [('A1', 'carFlows', 'A2'), ('B1', 'carSpeeds', 'B2'), ('C1', 'truckFlows', 'C2'), ('D1', 'truckSpeeds', 'D2')]:
                    sensor_sheet.write(title_cell, title_name, header_format)
                    sensor_sheet.write_column(value_cell, result[title_name], base_format)

    # create the timestamp worksheet
    timestamp_sheet.set_column('A:A', 15)
    timestamp_sheet.write('A1', 'timestamp', header_format)
    cell_number = 2
    for day in days:
        for hour in range(24):
            timestamp_sheet.write(f'A{cell_number}', f'{day}-{hour:02d}-00', base_format)
            cell_number += 1

    workbook.close()


if __name__ == '__main__':
    config = load_config()
    df = pd.read_excel(config.get('sensors', 'LOCATIONS', fallback='./data/sensor_locations.xlsx'))
    # network = sumolib.net.readNet(config.get('sumo', 'NETWORK', fallback='./sumo/vci.net.xml'))
    network_article = sumolib.net.readNet(config.get('nodes', 'NODE_ARTICLE', fallback='Article,./nodes/no_artigo.net.xml').split(',')[1])
    network_coimbroes = sumolib.net.readNet(config.get('nodes', 'NODE_COIMBROES', fallback='Nó de Coimbroes,./nodes/no_coimbroes.net.xml').split(',')[1])
    entries_exits_file = config.get('nodes', 'ENTRIES_EXITS', fallback='./nodes/entries_exits.md')

    gen_coverage(df, network_coimbroes, network_article)

    with open(entries_exits_file, 'w') as eef:
        for var, value in list(config.items('nodes')):
            if var.startswith('node_'):
                node_name, network_file = value.split(',')
                node_network = sumolib.net.readNet(network_file)
                gen_entry_exit_nodes(node_name, node_network.getNodes(), eef)
    
    prepare_view()
    prepare_data()