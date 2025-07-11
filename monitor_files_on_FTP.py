import argparse
import configparser
import ftplib
import os
import re
import datetime
import sys
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from telebot import TeleBot

# Fill Required Information
HOSTNAME = "192.168.1.1"
USERNAME = "anonymous"
PASSWORD = ""
SMB_PORT = "A"  # Port of the mapped disk

ftp = ftplib.FTP(HOSTNAME, USERNAME, PASSWORD)

folders = [
    'Folder1',
    'Folder2',
    'Folder3',
    'Folder4',
    'Folder5',
]

parser = argparse.ArgumentParser()
parser.add_argument('-i', '--ignore', nargs='*', default=[])
args = parser.parse_args()

config = configparser.ConfigParser()
config.read(Path(__file__).parent.joinpath('telegram_settings.ini'))
chat_id = config.get('Creds', 'chat_id')
access_token = config.get('Creds', 'access_token')


class TelegramBot:
    def __init__(self, chat_id, access_token):
        self._chat_id = int(chat_id)
        self._telegram_bot = TeleBot(access_token)

    def send_message(
            self,
            text: tuple
            ) -> None:
        message = ''
        for i in text:
            message += i + '\n'
        self._telegram_bot.send_message(self._chat_id,
                                        text=message)


telebot = TelegramBot(chat_id=chat_id, access_token=access_token)

# Dataclass with results for reporting
@dataclass
class ReportData:
    folder: str
    files_for_last_date: list[dict] = field(default_factory=list)
    files_for_previous_date: list[dict] = field(default_factory=list)
    access: str = None


def files_checker(
        ftp_server: ftplib.FTP = None,
        path: str | os.PathLike = None,
        access: str = 'FTP'
) -> None:
    """
    Checks files for date and size
    :param ftp_server: FTP connection object
    :param path: path to files
    :param access: FTP or SMB
    :return: Dataclass with results for reporting
    """
    files = []
    if access == 'FTP':
        ftp_server.dir(f'{path}', files.append)
    if access == 'SMB':  # Some folders are symlinks, access is via SMB
        os.chdir(path)
        files = os.listdir()

    for file in files:
        if file.split()[0].startswith('d') or os.path.isdir(file):  # If directory to call the function recursively
            filename = file.split()[-1] if access == 'FTP' else file
            if access == 'FTP':
                files_checker(ftp_server=ftp, path=f"{path}/{filename}")
            if access == 'SMB':
                files_checker(path=f'{path}/{file}', access='SMB')

        if file.split()[0].startswith('l'):  # If file is symlink go via SMB
            files_checker(path=f'{SMB_PORT}:/{path}', access='SMB')
            return None

    files = [file for file in files if re.search(r'202\d{5}_', file)]

    # Initializing dataclass
    report_data = ReportData(
        folder=path if access == 'FTP' else path.split(':')[1][1:]  # To leave just folders name
    )

    if len(files) == 0:
        report(rd=report_data)
        return

    files_dict = {}

    for file in files:
        creation_time = re.match(r'.*(202\d{5}).*', file).group(1)
        filename = re.sub(' +', ' ', file).split(' ')[-1] if access == 'FTP' else file
        files_dict[filename] = datetime.datetime.strptime(creation_time, '%Y%m%d').date()

    sorted_files_dict = {k: v for k, v in sorted(
        files_dict.items(), key=lambda x: x[1], reverse=True
    )
                         }
    last_file_date = sorted_files_dict[next(iter(sorted_files_dict))]
    previous_file_date = None
    for k, v in sorted_files_dict.items():
        if v != last_file_date:
            previous_file_date = v
            break

    files_for_previous_date = [k for k, v in sorted_files_dict.items() if v == previous_file_date]
    files_for_last_date = [k for k, v in sorted_files_dict.items() if v == last_file_date]

    for file in files_for_last_date:
        if access == 'FTP':
            file_size = int(ftp_server.size(f"{path}/{file}"))
        else:
            file_size = int(os.path.getsize(file))
        report_data.files_for_last_date.append(
            {
                'name': file,
                'date': files_dict[file],
                'size': file_size
            }
        )

    for file in files_for_previous_date:
        if access == 'FTP':
            file_size = int(ftp_server.size(f"{path}/{file}"))
        else:
            file_size = int(os.path.getsize(file))
        report_data.files_for_previous_date.append(
            {
                'name': file,
                'date': files_dict[file],
                'size': file_size
            }
        )

    if access != 'FTP':
        os.chdir("..")  # Return to parent directory when diving into folders
    report(rd=report_data)
    return

def report(
        rd: ReportData
) -> None:

    for data in args.ignore:
        if rd.folder == data:
            return

    if len(rd.files_for_last_date) == 0 and len(rd.files_for_previous_date) == 0:
        print_report((rd.folder, 'There are no files', ''))
        return

    for file in rd.files_for_last_date:
        if file['size'] < 5 * 1024 * 1024:
            print_report((rd.folder, 'Size is small', file['name']))

    last_file_date = rd.files_for_last_date[0]['date']
    if (datetime.datetime.today().date() - last_file_date).days > 1:
        print_report((rd.folder, 'No new data since', f'{last_file_date}'))

    if len(rd.files_for_previous_date) != 0:
        for file in rd.files_for_previous_date:
            if file['size'] < 50 * 1024 * 1024:
                print_report((rd.folder, 'Size is small', file['name']))

        previous_file_date = rd.files_for_previous_date[0]['date']
        if (last_file_date - previous_file_date).days > 1:
            print_report((
                    rd.folder, 'More than 1 day between', f"{previous_file_date} and {last_file_date}")
            )
    return


def print_report(
        result: tuple,
        print_format: str = '%-30s%-35s%-70s\n',
):
    global problems
    problems += 1
    f.write(print_format % result)
    print(print_format % result)
    telebot.send_message(result)


if __name__ == '__main__':
    problems = 0
    with open('check_files.txt', 'w') as f:
        for folder in folders:
            try:
                files_checker(ftp_server=ftp, path=folder)
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print_report((f'{folder}', 'Exception', f"{e}"))
                continue
        if problems == 0:
            telebot.send_message(('Today is OK',))
