import os
import sys
import re
import math
import time as t
import logging
import configparser
import numpy as np
import shutil
from tqdm import tqdm
from datetime import datetime, timedelta


def find_string(line: bytes,
                reg_expr: str
                ) -> bool:
    """
    Returns True if pattern is found
    """
    if re.search(reg_expr.encode(), line):
        return True


def time_in_sec(time_str: str
                ) -> float:
    """
    Returns time from MESSAGE in seconds
    """
    return timedelta(hours=int(time_str[0:2]), minutes=int(time_str[2:4]),
                     seconds=int(time_str[4:6])).total_seconds()


def delta_ll(lat: bytes,
             lon: bytes,
             true_lat: float,
             true_lon: float
             ) -> float:
    """
    Compares with reference position and returns delta in meters
    """
    lat = float(lat.decode())
    lon = float(lon.decode())
    delta_lat = true_lat - lat
    delta_lon = true_lon - lon
    delta_lat_m = delta_lat * 111134.8611
    delta_lon_m = math.cos(math.radians(true_lat)) * 111321.3778 * delta_lon
    delta_m = math.sqrt(delta_lat_m ** 2 + delta_lon_m ** 2)
    return delta_m


def process_data(
        flag: int,
        true_lat: float,
        true_lon: float,
        event: str,
        pos_threshold: int,
        duration: int,
        good_pos_counter: int,
        file: str,
        ) -> dict | None:
    """
    Analyzes data and returns statistics of tts (time to start) in dict format for further demonstration
    """
    # Prepare or clean result folder
    result_folder = os.path.join(os.getcwd(), 'results')
    if not os.path.exists(result_folder):
        os.makedirs(result_folder)
    else:
        for filename in os.listdir(result_folder):
            file_path = os.path.join(result_folder, filename)
            if os.path.splitext(file)[0] in file_path:
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    logging.debug(f'Error when removing {file_path}: {e}')

    event = event.encode()
    trials = []
    with open(file, 'rb') as f:
        trial = 0
        pos_counter = 0
        start_stop = []
        time_is_empty = False
        switch_message_search = False
        trial_stop_time = {}
        for line in tqdm(f, desc='In process...',unit=''):
            if (b'MESSAGE,' in line or event in line) and switch_message_search is False:
                if b'MESSAGE' in line:
                    if find_string(line, f'MESSAGE,\d+,\d+,\d+\.\d\d,'):
                        time = re.match(f'.*MESSAGE,\d+,\d+,(\d+\.\d\d),'.encode(), line).group(1)
                        message_time = time_in_sec(time)
                if event in line:
                    trial += 1
                    if trial > 1:
                        trial_stop_time[trial-1] = t.strftime('%H:%M:%S', t.gmtime(message_time))
                    start_stop.append(message_time)
                    switch_message_search = True
                    logging.debug('*'*20)
                    start_time = t.strftime('%H:%M:%S', t.gmtime(message_time))
                    logging.debug(f'Trial {trial} start:{message_time}; {start_time}')
                continue
            if (b'MESSAGE' in line or event in line) and switch_message_search is True:
                if find_string(line, f'MESSAGE,{flag},\d+,\d*\.\d\d,\d+\.\d+,N,\d+\.\d+,E'):
                    time = re.match(r'.*MESSAGE,\d+,\d+,(\d+\.\d\d),(\d+\.\d+),N,(\d+\.\d+),E'.encode(), line).group(1)
                    lat = re.match(r'.*MESSAGE,\d+,\d+,(\d+\.\d\d),(\d+\.\d+),N,(\d+\.\d+),E'.encode(), line).group(2)
                    lon = re.match(r'.*MESSAGE,\d+,\d+,(\d+\.\d\d),(\d+\.\d+),N,(\d+\.\d+),E'.encode(), line).group(3)
                    message_time = time_in_sec(time)
                    time_is_empty = False
                    if delta_ll(lat=lat, lon=lon, true_lat=true_lat, true_lon=true_lon) > pos_threshold:
                        logging.debug(f'delta {delta_ll(lat=lat, lon=lon, true_lat=true_lat, true_lon=true_lon)}; {time}')
                        pos_counter = 0
                        continue
                    if pos_counter == 0:
                        expected_tts = time_in_sec(time)
                        if expected_tts - start_stop[0] < 0:
                            expected_tts += 86400
                        start_stop.append(expected_tts)
                    pos_counter += 1
                    if pos_counter < good_pos_counter:
                        continue
                    tts = start_stop[-1] - start_stop[0]
                    if tts < 0:   # if day rollover
                        tts += 86400
                    trials.append(tts)
                    stop_time = t.strftime('%H:%M:%S', t.gmtime(expected_tts))
                    logging.debug(f'Trial {trial} stop:sec {expected_tts}; tts {tts}; {stop_time}')
                    start_stop = []
                    pos_counter = 0
                    switch_message_search = False
                    continue
                if find_string(line, f'MESSAGE,\d*,\d*,,'):
                    time_is_empty = True
                if find_string(line, f'MESSAGE,\d*,\d*,\d*\.\d\d,.*?\*'):
                    time = re.match(r'.*MESSAGE,\d*,\d*,(\d*\.\d\d),.*?\*'.encode(), line).group(1)
                    message_time = time_in_sec(time)
                    time_is_empty = False
                if event in line:
                    if not time_is_empty:
                        stop_time = t.strftime('%H:%M:%S', t.gmtime(message_time))
                    else:
                        message_time = (datetime.strptime(trial_stop_time[trial-1], '%H:%M:%S') + timedelta(seconds=duration)).time()
                        message_time = (message_time.hour * 60 + message_time.minute) * 60 + message_time.second
                        stop_time = t.strftime('%H:%M:%S', t.gmtime(message_time))
                    trial_stop_time[trial] = stop_time
                    logging.debug(f'Trial {trial} stop: FAIL; {stop_time}')
                    trial += 1
                    trials.append('fail')
                    start_stop.clear()
                    start_stop.append(message_time)
                    logging.debug('*'*20)
                    start_time = t.strftime('%H:%M:%S', t.gmtime(message_time))
                    logging.debug(f'Trial {trial} start:{message_time}; {start_time}')
                    continue

    success_trials = [x for x in trials if x != 'fail']
    logging.debug(success_trials)
    logging.debug(trials)

    if len(success_trials) == 0:
        return None

    trials_dict = {}
    for i, v in enumerate(trials):
        trials_dict[i+1] = v

    result_stat = {
        'Total trials': len(trials),
        'Failed trials': trials.count('fail'),
        'Average': np.mean(success_trials),
        'Min': min(success_trials),
        'Max': max(success_trials),
        'P50': round(np.percentile(np.array(success_trials), 50),2),
        'P90': round(np.percentile(np.array(success_trials), 90),2),
        'Trials_dict': trials_dict
    }

    if not os.path.exists(os.path.dirname(result_folder)):
        os.makedirs(os.path.dirname(result_folder))
    result_filename = os.path.join(result_folder, os.path.splitext(file)[0]+'_results.txt')
    with open(result_filename, 'w') as result_file:
        for key, value in result_stat.items():
            result_file.write(f"{key}: {value}\n")
            logging.info(f"{key}: {value}")

    return result_stat


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    config = configparser.ConfigParser()
    config.read('settings.txt')

    process_data(
        flag=int(config.get('Settings', 'flag')),
        true_lat=float(config.get('Settings', 'true_lat')),
        true_lon=float(config.get('Settings', 'true_lon')),
        event=config.get('Settings', 'event'),
        pos_threshold=int(config.get('Settings', 'pos_threshold')),
        duration=int(config.get('Settings', 'duration')),
        good_pos_counter=int(config.get('Settings', 'good_pos_counter')),
        file=config.get('Settings', 'file'),
    )


