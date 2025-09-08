import base64
import socket
import datetime
import sys
import time

streampoint = sys.argv[1]
user = sys.argv[2]
password = sys.argv[3]

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.connect(('0.0.0.0', 2101))
server_socket.sendall(f'SOURCE server_password /{streampoint}'.encode())
server_socket.recv(1024)

clients = []
for i in range(1, 6):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect(('0.0.0.0', 2101))
    clients.append((f"Client_{i}", client_socket))
    auth_data = base64.b64encode(f'{user}:{password}'.encode())
    client_socket.sendall(f'GET /{streampoint} HTTP/1.1\r\nAuthorization: Basic {auth_data.decode()}\r\n'.encode())

try:
    while True:
        data = f"{str(datetime.datetime.now())} example data \r\n".encode()
        server_socket.sendall(data)
        for client, socket in clients:
            received_data = socket.recv(4096)
            print(f'{client } received "{received_data.decode().rstrip()}" from server for streampoint {streampoint}')
        time.sleep(1)
except KeyboardInterrupt:
    server_socket.close()
    for client, socket in clients:
        socket.close()
