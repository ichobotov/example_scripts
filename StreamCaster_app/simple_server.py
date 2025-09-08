import base64
import socket
import datetime
import sys
import time


server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.connect(('0.0.0.0', 2101))
streampoint = sys.argv[1]
server_socket.sendall(f'SOURCE server_password /{streampoint}'.encode())

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect(('0.0.0.0', 2101))
user = sys.argv[2]
password = sys.argv[3]
auth_data = base64.b64encode(f'{user}:{password}'.encode())
client_socket.sendall(f'GET /{streampoint} HTTP/1.1\r\nAuthorization: Basic {auth_data.decode()}\r\n'.encode())

while True:
    data = f"{str(datetime.datetime.now())} example data \r\n".encode()
    server_socket.sendall(data)
    received_data = client_socket.recv(4096)
    print(f'Client {user} received "{received_data.decode().rstrip()}" from server for streampoint {streampoint}')
