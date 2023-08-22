import pandas as pd
import matplotlib.pyplot as plt

from .utils import load_config
from matplotlib.dates import DateFormatter, HourLocator

config = load_config()
results_dir = config.get('dir', 'RESULTS', fallback='./sumo/results')

data = pd.DataFrame()

for hour in range(24):
    formatted_hour = f"{hour:02}"
    # excel_file = f'{results_dir}/flow_2022-03-24-{formatted_hour}-00.xlsx'
    excel_file = f'{results_dir}/flow_2023-05-24-{formatted_hour}-00.xlsx'
    df = pd.read_excel(excel_file)
    # edge_data = df[['f_S_NE11_ref', 'f_S_NE11']]
    edge_data = df[['f_405899851_ref', 'f_405899851']]
    # edge_data['Time'] = pd.to_datetime(f'2022-03-24 {formatted_hour}:00:00') + pd.to_timedelta(edge_data.index, unit='m')
    edge_data['Time'] = pd.to_datetime(f'2023-05-24 {formatted_hour}:00:00') + pd.to_timedelta(edge_data.index, unit='m')
    data = data.append(edge_data)

# Calculate the moving average of the "Real Count" and "Simulated Count" data with a window of 20 minutes
# data['Moving Average'] = data['f_S_NE11_ref'].rolling(window=20).mean()
# data['Simulated Count'] = data['f_S_NE11'].rolling(window=20).mean()
data['Moving Average'] = data['f_405899851_ref'].rolling(window=20).mean()
data['Simulated Count'] = data['f_405899851'].rolling(window=20).mean()

fig, ax = plt.subplots()

# Plot the real values in salmon color
# ax.plot(data['Time'], data['f_S_NE11_ref'], label='Real Count', color='salmon')
ax.plot(data['Time'], data['f_405899851_ref'], label='Real Count', color='salmon')

# Plot the moving average of the real values in red color
ax.plot(data['Time'], data['Moving Average'], label='Moving Average', color='red')

# Plot the moving average of the simulated values in blue color
ax.plot(data['Time'], data['Simulated Count'], label='Simulated Count', color='blue', linestyle='dashed')

ax.set_xlabel('Time [h]')
ax.set_ylabel('Traffic Volume [veh/h]')
# ax.set_title(f'Real vs Simulated Vehicle Count for Edge S_NE11')
ax.set_title(f'Real vs Simulated Vehicle Count for Edge 405899851')

hour_locator = HourLocator(interval=2)
hour_formatter = DateFormatter('%H:%M')

ax.xaxis.set_major_locator(hour_locator)
ax.xaxis.set_major_formatter(hour_formatter)

plt.xticks(rotation=45)

ax.legend()
ax.grid(True)

plt.show()