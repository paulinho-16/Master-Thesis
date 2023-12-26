import pandas as pd
import matplotlib.pyplot as plt

from .utils import load_config
from matplotlib.dates import DateFormatter, HourLocator

config = load_config()
results_dir = config.get('dir', 'RESULTS', fallback='./sumo/results')

data = pd.DataFrame()
dfs_data = {} # edge_id : data

for hour in range(24):
    formatted_hour = f"{hour:02}"
    excel_file = f'{results_dir}/flow_2022-03-24-{formatted_hour}-00.xlsx'
    # excel_file = f'{results_dir}/flow_2023-05-24-{formatted_hour}-00.xlsx'
    # excel_file = f'{results_dir}/flow_2023-05-25-{formatted_hour}-00.xlsx'
    # excel_file = f'{results_dir}/flow_2023-05-26-{formatted_hour}-00.xlsx'
    df = pd.read_excel(excel_file)

    for column_name in df.columns:
        if column_name.startswith('TTS'):
            break
        if column_name.endswith('_ref'):
            continue

        column_data = df[column_name]

        edge_data = df[[f'{column_name}_ref', column_name]]

        edge_data = edge_data.copy()
        edge_data.loc[:, 'Time'] = pd.to_datetime(f'2022-03-24 {formatted_hour}:00:00') + pd.to_timedelta(edge_data.index, unit='m')

        dfs_data.setdefault(column_name[2:], []).append(edge_data)

for edge_id, edge_data in dfs_data.items():
    data = pd.concat(edge_data)

    # Calculate the moving average of the "Real Count" and "Simulated Count" data with a window of 20 minutes
    data['Moving Average'] = data[f'f_{edge_id}_ref'].rolling(window=20).mean()
    data['Simulated Count'] = data[f'f_{edge_id}'].rolling(window=20).mean()

    fig, ax = plt.subplots()

    # Plot the real values in salmon color
    ax.plot(data['Time'], data[f'f_{edge_id}_ref'], label='Real Count', color='salmon')

    # Plot the moving average of the real values in red color
    ax.plot(data['Time'], data['Moving Average'], label='Moving Average', color='red')

    # Plot the moving average of the simulated values in blue color
    ax.plot(data['Time'], data['Simulated Count'], label='Simulated Count', color='blue', linestyle='dashed')

    ax.set_xlabel('Time [h]')
    ax.set_ylabel('Traffic Volume [veh/h]')
    ax.set_title(f'Real vs Simulated Vehicle Count for Edge {edge_id}')

    hour_locator = HourLocator(interval=2)
    hour_formatter = DateFormatter('%H:%M')

    ax.xaxis.set_major_locator(hour_locator)
    ax.xaxis.set_major_formatter(hour_formatter)

    plt.xticks(rotation=45)

    ax.legend()
    ax.grid(True)

    plt.savefig(f'{results_dir}/flow_{edge_id}.png')
    # plt.show()