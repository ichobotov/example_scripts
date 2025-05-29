from datetime import datetime
import sys
import re
import argparse
import os
from tqdm import tqdm

record = False


def find_string(line, reg_expr):
    if re.search(reg_expr.encode('utf-8'), line):
        return True

usage='''python bincut.py <Input file> <-t|-p> [<Message type> <Start time> <End time>] or [<Start percent> <End percent>]
         Use -t for time mode and -p for percent mode
         For example:
         python bincut.py inp.txt -t GNGGA 101112.00 201122.50
         python bincut.py inp.txt -p 10 50'''

parser = argparse.ArgumentParser(description='Tool to cut files. ', usage=usage)

if '-h' in sys.argv:
    args = parser.parse_args()
    sys.exit()
if len(sys.argv) == 1:
    print(usage)
    sys.exit()

if '-t' in sys.argv:
    sys.argv.remove('-t') # to remove '-t' in sys.argv for parse_args -> parse_known_args function
    parser.add_argument('input_file', type=str, help='Input file')
    parser.add_argument('message_type', type=str, help='Message type without $, e.g. GNGGA, NAV')
    parser.add_argument('start_time', type=str, help='Start time, e.g. 131415.10')
    parser.add_argument('end_time', type=str, help='End time, e.g. 131415.10')
    parser.add_argument("-t", "--time_mode", action="store_false", default="True", help="Enable time mode")
if '-p' in sys.argv:
    sys.argv.remove('-p')  # to remove '-p' in sys.argv for parse_args -> parse_known_args function
    parser.add_argument('input_file', type=str, help='Input file')
    parser.add_argument('start_percent', type=str, help='Start percent')
    parser.add_argument('end_percent', type=str, help='End percent')
    parser.add_argument("-p", "--percent_mode", action="store_false", default="True", help="Enable percent mode")

args = parser.parse_args(args=sys.argv[1:])

start_time = datetime.now()

try:
    if args.time_mode:
        with open(args.input_file, 'rb') as f:
            file_output = os.path.splitext(args.input_file)[0]+'.out'
            with open(file_output, 'wb') as fo:

                try:
                    args.start_time = str(int(args.start_time))+'.00'
                except ValueError:
                    pass
                try:
                    args.end_time = str(int(args.end_time))+'.00'
                except ValueError:
                    pass

                for line in tqdm(f, desc='in progress', unit=''):
                    if args.message_type.encode('utf-8') in line:
                        if find_string(line,f'\${args.message_type},.*{args.start_time}'):
                            fo.write(line[line.index(f'${args.message_type}'.encode('utf-8')):])
                            record = True
                            continue
                        if find_string(line,f'\${args.message_type},.*{args.end_time}'):
                            fo.write(line[:line.index(f'${args.message_type}'.encode('utf-8'))])
                            record = False
                            break
                    if record:
                        fo.write(line)
        if os.path.getsize(file_output) == 0:
            sys.exit("Output is zero. Please check input parameters")
        sys.exit("Success!")
except AttributeError:
    pass
except FileNotFoundError:
    sys.exit("File not found")

try:
    if args.percent_mode:
        with open(args.input_file, 'rb') as f:
            file_output = os.path.splitext(args.input_file)[0]+'.out'
            with open(file_output, 'wb') as fo:
                file_size = os.stat(args.input_file).st_size
                start = int(args.start_percent)
                end = int(args.end_percent)
                start_from = file_size * start / 100
                end_to = file_size * end / 100
                to_cut = end_to - start_from
                if to_cut >= 4096:
                    chunk = 4096
                    chunk_number = to_cut // chunk
                    residual = to_cut % chunk
                    f.seek(int(start_from))
                    for i in tqdm(range(int(chunk_number)), desc='in progress', unit='',ncols=50,
                                  bar_format="{desc}: {percentage:3.0f}%|{bar}| [{elapsed_s:0.2f} sec]"):
                        data = f.read(chunk)
                        fo.write(data)
                    data = f.read(int(residual))
                    fo.write(data)
                else:
                    f.seek(int(start_from))
                    for i in tqdm(range(int(to_cut)), desc='in progress', unit='',ncols=50,
                                  bar_format="{desc}: {percentage:3.0f}%|{bar}| [{elapsed_s:0.2f} sec]"):
                        data = f.read(1)
                        fo.write(data)
        if os.path.getsize(file_output) == 0:
            sys.exit("Output is zero. Please check input parameters")
        sys.exit("Success!")
except AttributeError:
    pass
except FileNotFoundError:
    sys.exit("File not found")

print(f'Time elapsed = {(datetime.now() - start_time).total_seconds()} sec')