#Script calculates statistics of time to first correct position after powering on

import os
from datetime import datetime, time, timedelta
import re
import math
import io
import numpy as np
import shutil
from tqdm import tqdm
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Tuple


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='settings.txt',
        env_file_encoding='utf-8',
    )
    directory: str
    board: str
    flag: int
    true_lat: float
    true_lon: float
    pos_threshold: int
    file: str

settings = Settings()

PATH = settings.directory
BOARD = settings.board
FLAG = settings.flag
TRUE_LAT = settings.true_lat
TRUE_LON = settings.true_lon
POS_THRESHOLD = settings.pos_threshold
FILE = settings.file


result_folder = BOARD+'_trials'
dir_with_files = os.path.join(PATH,result_folder)


logging.basicConfig(level=logging.INFO, datefmt="%Y-%m-%d %H:%M:%S", format="%(asctime)s %(levelname)s %(message)s",
                    filename=f"result.log",filemode="w")




def find_pwr_events(file:str) -> list:
    '''
    :param file: origin file to find PWR events in
    :return: list with PWR-ON and PWR-OFF events, [(start1, end1), (start2, end2),...]. Then it is used to split the origin file to the separate trials
    '''
    pwr_on_time = []
    pwr_off_time = []
    switch_time_search = False
    switch_pwr = False
    pwr = None
    with open(file, 'rb') as f:
        for line in f:
            if find_string(line, 'PWR-ON'):
                switch_time_search = True
                switch_pwr = True
                pwr = 'on'
                continue
            if find_string(line, '\[--\d+\.\d{2}\--]') and switch_time_search:
                line=line.rstrip()
                line=line[1:-1]
                if pwr == 'on':
                    pwr_on_time.append(line.rstrip().decode())
                if pwr == 'off':
                    pwr_off_time.append(line.rstrip().decode())
                switch_time_search = False
                switch_pwr = True
            if find_string(line, 'PWR-OFF') and switch_pwr:
                switch_time_search = True
                switch_pwr = False
                pwr = 'off'
                continue
    if len(pwr_on_time) > len(pwr_off_time):
        del pwr_on_time[-1]

    pwr_events = list(zip(pwr_on_time, pwr_off_time))
    return pwr_events



def split_to_trials(RESULT_FOLDER: str, FILE: str, PATH: str , time_list: list) -> None :
    '''
    :param RESULT_FOLDER: separate folder to put trials. Then it's used for going through the files.
    :param FILE: origin file
    :param PATH: set working directory
    :param time_list: list of PWR events, e.g [(start1, end1), (start2, end2),...]
    :return: None. RESULT_FOLDER contains list of files
    '''
    os.chdir(PATH)
    if os.path.exists(RESULT_FOLDER):
        shutil.rmtree(RESULT_FOLDER)
        os.mkdir(RESULT_FOLDER)
    else:
        os.mkdir(RESULT_FOLDER)

    i = 1
    switch_pwron_search = True
    switch_pwroff_search = False

    with open (FILE, 'rb') as f:
        for time in time_list:
            for line in tqdm(file_reader(f), desc='creating files, please wait...', bar_format="{desc} "):
                if find_string(line, time[0]) and switch_pwron_search:
                    filename = str(i) + '.txt'
                    trial = open(os.path.join(PATH, RESULT_FOLDER, filename), 'wb')
                    trial.write(line)
                    switch_pwron_search = False
                    switch_pwroff_search = True
                    continue
                while not find_string(line, time[1]) and switch_pwroff_search:
                    trial.write(line)
                    try:
                        line = next(file_reader(f))
                    except StopIteration:
                        break
                try:
                    io.TextIOWrapper.__instancecheck__(trial)
                except NameError:
                    continue
                trial.write(line)
                trial.close()
                del trial
                switch_pwron_search = True
                switch_pwroff_search = False
                i+=1
                break


def main_analysis() -> Tuple[list, list]:
    '''
    :return: List of all the trials and list of successful only ones
    '''
    files_sorted = sorted(os.listdir(dir_with_files), key=lambda x: int(os.path.splitext(x)[0]))
    trials = []

    for filename in tqdm(files_sorted, desc='Files'):
        with open(os.path.join(dir_with_files, filename), 'rb') as f:
            start_stop = []
            switch_pos_search = False
            switch_time_search = True
            for line in f:
                if switch_time_search and b'[--' in line:
                    if find_string(line, '\[--\d+\.\d{2}\--]'):
                        print_time = re.match(r'.*\[--(\d+\.\d{2})\--]'.encode(), line).group(1).decode()
                        print_time_sec = time_in_sec(print_time)

                        if len(start_stop) == 0:
                            start_stop.append(print_time_sec)
                            switch_time_search = False
                            switch_pos_search = True
                            continue
                        else:
                            start_stop.append(print_time_sec)
                            ttff = start_stop[1] - start_stop[0]

                            if ttff < 0:
                                ttff = ttff + 86400

                            trials.append(ttff)
                            start_stop = []
                            break
                if switch_pos_search and b'GGA' in line:
                    if find_string(line, f'.*\$G.GGA,\d*\.\d*,.*(?<=[E|W],){FLAG},'):
                        group = re.match(r'.*\$G.GGA,(\d{6}.\d{2}),(\d+\.\d+),.,(\d+\.\d+),'.encode(), line)
                        time_stamp = group.group(1)
                        lat = group.group(2)
                        lon = group.group(3)

                        if position_delta(lat, lon) > POS_THRESHOLD:
                            logging.warning('position is out of the tolerance in the file "%s" at time "%s"', filename, time_stamp.decode())
                            continue
                        switch_time_search = True
                        switch_pos_search = False
                        continue
            if len(start_stop) != 0:
                trials.append('fail')
    success_trials = [x for x in trials if x != 'fail']
    return trials, success_trials


if __name__ == '__main__':

    #Get lists of PWR ON/OFF events
    pwr_events = find_pwr_events('poweroffon.log')
    logging.info('%s trials to be analyzed', len(pwr_events))

    # Split to separate files
    split_to_trials(result_folder, FILE, PATH, pwr_events)
    logging.info('%s files are created successfully', len(os.listdir(os.path.join(PATH, result_folder))))

    # Analyze data
    trials, success_trials = main_analysis()
    print('Ready! Please see result.log file')


    logging.info(f"""
    Total trials = {len(trials)}
    Failed trials = {trials.count('fail')}
    Average = {round(np.mean(success_trials), 2)}
    Min = {min(success_trials)}
    Max = {max(success_trials)}
    P50 = {np.percentile(np.array(success_trials), 50)}
    P90 = {np.percentile(np.array(success_trials), 90)}
    Stdev = {round(np.std(np.array(success_trials)), 2)}
    Trials = {trials}""")
