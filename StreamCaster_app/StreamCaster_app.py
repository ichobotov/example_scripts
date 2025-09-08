import uvicorn
import asyncio
import base64
import datetime
import logging
import secrets
import sys
import time
import json
from collections import defaultdict
from typing import (
    Dict,
    List,
    Optional,
)

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
)

from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
)
from pydantic import BaseModel
from starlette import status
from starlette.responses import JSONResponse


logging.basicConfig(level=logging.INFO, filename='report.log')
logger = logging.getLogger(__name__)

SERVER_PASSWORD = "server_password"
RECONNECT_DELAY = 300  # seconds
SERVER_TIMEOUT = 120  # seconds
CONFIG_FILE = "app_settings.json"


class StreamCaster:
    def __init__(
            self
    ):
        self.stream_points: list = []  # [streampoint]
        self.stream_users: Dict[str, Dict] = defaultdict(dict)  # {user: {password: str, allowed_streampoints: list}}
        self.server_connections: Dict[str, Dict] = defaultdict(dict)  # {streampoint: {last_activity:float}}
        self.client_queues: Dict[str, Dict[str, asyncio.StreamWriter]] = defaultdict(dict)  # {streampoint: {client_id:writer}}
        self.rate_limit = 0.1
        self.lock = asyncio.Lock()
        self.broadcast_queue: asyncio.Queue = asyncio.Queue()

        # Default values from app_settings.json
        config = self._read_config_json()
        self.stream_points = config['streampoints']
        self.stream_users = config['users']

    async def _cleanup(
            self,
            del_streampoints: bool = False,
            del_stream_users: bool = False,
            del_server_connections: bool = False,
            del_client_queues: bool = False,
            writer: asyncio.StreamWriter = None,
            streampoint: str = None,
            client_id: str = None,
            username: str = None
    ) -> None:
        """
        Cleaning disconnected resourses
        """
        logger.debug(f"{str(datetime.datetime.now())} Start cleaning")
        async with self.lock:
            try:
                if del_streampoints:
                    if streampoint not in self.stream_points:
                        raise KeyError(f"streampoint {streampoint} not found")
                    else:
                        self.stream_points.remove(streampoint)

                if del_stream_users:
                    if username not in self.stream_users:
                        raise KeyError(f"User {username} not found")
                    del self.stream_users[username]
                    for mp in self.client_queues:
                        for client_id in self.client_queues[mp]:
                            if username in client_id:
                                del self.client_queues[mp][client_id]


                if del_server_connections:
                    if streampoint in self.server_connections and self.server_connections[streampoint] != {}:
                        try:
                            writer.close()
                            await writer.wait_closed()
                            logger.debug(
                                f"{str(datetime.datetime.now())} Before deletion, server_connections: {self.server_connections}"
                                )
                            del self.server_connections[streampoint]
                            logger.debug(f"{str(datetime.datetime.now())} After deletion, server_connections: {self.server_connections}")
                        except Exception:
                            logger.debug(f"{str(datetime.datetime.now())} Cleaning server_connections error: {self.server_connections}")
                            del self.server_connections[streampoint]

                if del_client_queues:
                    if streampoint in self.client_queues:
                        logger.debug(
                            f"{str(datetime.datetime.now())} Before deletion client_queues: {self.client_queues[streampoint]}"
                            )
                        if client_id and client_id in self.client_queues[streampoint]:
                            writer = self.client_queues[streampoint][client_id]
                            try:
                                writer.close()
                                await writer.wait_closed()
                            except (ConnectionAbortedError, ConnectionResetError, ConnectionError, OSError):
                                pass
                            del self.client_queues[streampoint][client_id]
                        elif not client_id:
                            del self.client_queues[streampoint]
                    logger.debug(f"{str(datetime.datetime.now())} After deletion client_queues: {self.client_queues[streampoint]}")
            except KeyError:
                pass
        logger.debug(f"{str(datetime.datetime.now())} Stop cleaning")


    def _read_config_json(
            self,
            file=CONFIG_FILE
            ) -> dict:
        try:
            with open(file, 'r') as file:
                config = json.load(file)
                return config
        except Exception:
            sys.exit("Failed to read config file")

    def _write_config_json(
            self,
            file=CONFIG_FILE,
            ) -> None:
        config = self._read_config_json()
        config["streampoints"] = self.stream_points
        config["users"] = self.stream_users
        try:
            with open(file, 'w') as config_file:
                json.dump(config, config_file, indent=4)
        except Exception:
            sys.exit("Failed to write config file")

    async def add_streampoint(
            self,
            streampoint: str,
    ) -> None:
        """Add new stream point for streaming"""
        async with self.lock:
            if streampoint in self.stream_points:
                raise ValueError(f"streampoint {streampoint} already exists")
            self.stream_points.append(streampoint)
            self._write_config_json()
            logger.debug(f"{str(datetime.datetime.now())} Added new streampoint: {streampoint}")


    async def remove_streampoint(
            self,
            streampoint: str
    ) -> None:
        """Remove stream point and all connected resourses"""
        await self._cleanup(del_streampoints=True, streampoint=streampoint)
        await self._cleanup(del_server_connections=True, streampoint=streampoint)
        await self._cleanup(del_client_queues=True, streampoint=streampoint)
        self._write_config_json()
        logger.debug(f"{str(datetime.datetime.now())} Removed streampoint: {streampoint}")

    async def add_stream_user(
            self,
            username: str,
            password: str,
            allowed_streampoints: list = list()
            ) -> None:
        """Add new user"""
        async with self.lock:
            if username in self.stream_users:
                raise ValueError(f"User {username} already exists")
            self.stream_users[username] = {
                'password': password,
                'allowed_streampoints': allowed_streampoints
            }
            self._write_config_json()
            logger.debug(f"{str(datetime.datetime.now())} Added new user: {username}")

    async def remove_stream_user(
            self,
            username
            ) -> None:
        """Remove user"""
        await self._cleanup(del_stream_users=True, username=username)
        self._write_config_json()
        logger.debug(f"{str(datetime.datetime.now())} User {username} successfully removed")

    async def handle_connection(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter
    ) -> None:
        """ Handler for each new connection inside asyncio.start_server"""
        try:
            data = await reader.read(4096)
            info_line = data.split(b'\n')[0].decode().strip()
            logger.debug(f"{str(datetime.datetime.now())} Handle connection received data: {data}")

            if "SOURCE" in info_line:
                await self.handle_server(reader=reader, writer=writer, info_line=info_line)
            elif "GET /" in info_line:
                await self.handle_client(writer=writer, info_line=info_line, data=data)
            else:
                writer.write(b"ERROR - Invalid protocol\r\n")
                await writer.drain()
        except ConnectionAbortedError:
            logger.debug(f"{str(datetime.datetime.now())} ConnectionAbortedError happened")
        except Exception as e:
            logger.debug(f"{str(datetime.datetime.now())} Connection error: {e}")

    async def handle_server(
            self,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
            info_line: str,
    ) -> None:
        """Handler for servers"""
        _, password, streampoint = info_line.split()
        streampoint = streampoint.lstrip('/')
        logger.debug(f"{str(datetime.datetime.now())} Start server handle task for {streampoint} \r\n")
        try:
            if streampoint not in self.stream_points or password != SERVER_PASSWORD:
                writer.write(b"ERROR - Invalid streampoint or password\r\n")
                logger.debug(f"{str(datetime.datetime.now())} ERROR - Invalid streampoint or password\r\n")
                await writer.drain()
                return
            if streampoint in self.server_connections and self.server_connections[streampoint] != {}:
                writer.write(b"ERROR - streampoint is already in use\r\n")
                logger.debug(f"{str(datetime.datetime.now())} ERROR - streampoint is already in use")
                await writer.drain()
                return
            async with self.lock:
                self.server_connections[streampoint]['last_activity'] = time.time()
            writer.write(b"ICY 200 OK\r\n\r\n")
            await writer.drain()
        except Exception as e:
            logger.debug(f"{str(datetime.datetime.now())} ERROR - Server task exception: {e}\r\n")
            return

        try:
            while True:
                # Read data from server and check its activity
                try:
                    server_activity_sec = time.time() - self.server_connections[streampoint]['last_activity']
                    logger.debug(
                        f"{str(datetime.datetime.now())} {streampoint} clients {len(self.client_queues[streampoint])} clients")
                    if server_activity_sec > SERVER_TIMEOUT:
                        logger.debug(
                            f"{str(datetime.datetime.now())} Wait for server data for streampoint {streampoint}..."
                        )
                        if server_activity_sec > RECONNECT_DELAY:
                            raise TimeoutError
                    data = await asyncio.wait_for(reader.read(4096), timeout=1)
                    if data:
                        self.server_connections[streampoint]['last_activity'] = time.time()
                except Exception as e:
                    logger.debug(
                        f"{str(datetime.datetime.now())} Error reading data from {streampoint} server:{e}"
                        )
                    data = b' '  # Empty data to maintain client connection
                    if isinstance(e, (ConnectionError, OSError)):
                        logger.debug(
                            f"{str(datetime.datetime.now())} Connection with server for {streampoint} lost: {e}"
                            )
                        raise TimeoutError
                # Put data to broadcast queue
                try:
                    await self.broadcast_queue.put((streampoint, data))
                    logger.debug(
                        f"{str(datetime.datetime.now())} Broadcast data to {streampoint} (server): {data}"
                        )
                    await asyncio.sleep(self.rate_limit)
                except Exception as e:
                    logger.debug(
                        f"{str(datetime.datetime.now())} Error broadcasting data for {streampoint}:{e}"
                        )
        except TimeoutError:
            logger.debug(f"{str(datetime.datetime.now())} Error - Server timeout for streampoint {streampoint}")
        except Exception as e:
            logger.debug(f"{str(datetime.datetime.now())} Error - Server exception {e}")
        finally:
            logger.debug(f"{str(datetime.datetime.now())} Removing server task...")
            await self._cleanup(
                del_server_connections=True,
                del_client_queues=True,
                streampoint=streampoint,
                writer=writer
            )
            if self.server_connections[streampoint] == {}:
                logger.debug(f"{str(datetime.datetime.now())} Server task is cancelled for streampoint {streampoint}")
            else:
                logger.debug(
                    f"{str(datetime.datetime.now())} Server task cancel for streampoint {streampoint} error"
                    f" {self.server_connections}\n"
                )
            return

    async def handle_broadcast(self) -> None:
        """Handler for broadcast task"""
        while True:
            try:
                streampoint, data = await asyncio.wait_for(self.broadcast_queue.get(), timeout=10)
                asyncio.create_task(self.start_broadcast_task(streampoint=streampoint, data=data))
            except Exception:
                logger.debug(f"{str(datetime.datetime.now())} No data in queue from server")
            await asyncio.sleep(self.rate_limit)

    async def start_broadcast_task(
            self,
            streampoint: str,
            data: bytes
            ) -> None:
        """ Broadcasting data to clients"""
        logger.debug(f"{str(datetime.datetime.now())} Start broadcast for {streampoint}")
        try:
            disconnected = []
            async with self.lock:
                clients = list(self.client_queues[streampoint].items())
            clients_id = [i[0] for i in clients]
            logger.debug(f"{str(datetime.datetime.now())} Broadcast {streampoint} for {len(clients_id)} clients")
            for client_id, writer in clients:
                try:
                    writer.write(data)
                    await writer.drain()
                except (ConnectionError, ConnectionResetError, ConnectionAbortedError, OSError):
                    disconnected.append(client_id)
                    logger.debug(
                        f"{str(datetime.datetime.now())} Client {streampoint}:{client_id} write error"
                    )
                except Exception as e:
                    logger.debug(
                        f"{str(datetime.datetime.now())} Error - writing data to {streampoint}:{client_id} exception: {e}"
                    )
                    disconnected.append(client_id)

            logger.debug(f"{str(datetime.datetime.now())} Disconnected list for {streampoint}: {disconnected}")
            if disconnected:
                logger.debug(
                    f"{str(datetime.datetime.now())} Removing {len(disconnected)} inactive clients"
                    )
                for client_id in disconnected:
                    await self._cleanup(del_client_queues=True, streampoint=streampoint, client_id=client_id)
        except Exception as e:
            logger.debug(f"{str(datetime.datetime.now())} Broadcast error: {e}")
        finally:
            return

    async def handle_client(
            self,
            writer: asyncio.StreamWriter,
            info_line: str,
            data: bytes
    ) -> None:
        """Handler for clients"""
        streampoint = info_line.split()[1].lstrip('/')
        header_data = data.split(b'\n')
        logger.debug(f"{str(datetime.datetime.now())} Start client handle task for {streampoint}\r\n")
        try:
            for header in header_data:
                header = header.decode()
                if 'Authorization:' in header and 'Basic' in header:
                    auth_data = header.split(':')[1].split(' ')[-1]  # Get authorization data
                    login, password = base64.b64decode(auth_data).decode().split(':')
                    async with self.lock:
                        if login not in self.stream_users:
                            writer.write(b"Error - User not found\r\n")
                            logger.debug(f"{str(datetime.datetime.now())} Error - User {login} not found\r\n")
                            await writer.drain()
                            return

                        if password != self.stream_users[login]['password']:
                            writer.write(b"Error - User authorization failed\r\n")
                            logger.debug(f"{str(datetime.datetime.now())} Error - User {login} authorization failed\r\n")
                            await writer.drain()
                            return

                        if self.stream_users[login]['allowed_streampoints']:
                            if streampoint not in self.stream_users[login]['allowed_streampoints']:
                                writer.write(b"Error - streampoint not allowed for user\r\n")
                                logger.debug(f"{str(datetime.datetime.now())} Error - streampoint {streampoint} not allowed for {login}\r\n")
                                await writer.drain()
                                return

            if streampoint not in self.stream_points:
                writer.write(b"Error - streampoint not found\r\n")
                logger.debug(
                    f"{str(datetime.datetime.now())} Error - streampoint {streampoint} not found\r\n"
                    )
                await writer.drain()
                return

            if streampoint not in self.server_connections or\
                    self.server_connections[streampoint] == {}:
                writer.write(b"Error - streampoint is not active\r\n")
                logger.debug(
                    f"{str(datetime.datetime.now())} Error - streampoint {streampoint} is not active\r\n"
                    )
                await writer.drain()
                return

            writer.write(b"ICY 200 OK\r\n")
            await writer.drain()

            client_id = id(writer)
            new_client = {client_id: writer}
            self.client_queues[streampoint] = {**new_client, **self.client_queues[streampoint]}  # Add new client to start
            logger.debug(
                f"{str(datetime.datetime.now())} Client {streampoint}:{client_id} added\r\n"
            )
            logger.debug(
                f"{str(datetime.datetime.now())} Clients_count for {streampoint} {len(self.client_queues[streampoint])}\r\n"
            )
        except Exception as e:
            logger.debug(f"{str(datetime.datetime.now())} Error adding new client: {e}\r\n")
        finally:
            return

proxy = StreamCaster()


# FastAPI part
app = FastAPI()
security = HTTPBasic()

def verify_password(
        credentials: HTTPBasicCredentials,
        correct_password: str
) -> bool:
    return secrets.compare_digest(credentials.password.encode('utf-8'), correct_password.encode('utf-8'))

# Models
class StreamPointCreate(BaseModel):
    stream_point: str


class StreamPointInfo(BaseModel):
    stream_point: str
    client_count: int
    server_connected: bool


class StreamUsers(BaseModel):
    login: str
    password: str
    allowed_streampoints: Optional[list] = []


class StreamUsersInfo(BaseModel):
    login: str
    password: str
    allowed_streampoints: list


@app.post("/streampoints/", status_code=status.HTTP_201_CREATED)
async def create_stream_point(
        stream_data: StreamPointCreate,
        credentials: HTTPBasicCredentials = Depends(security)
) -> JSONResponse:
    """Create a new stream point (only authorized servers can do this)"""
    if not verify_password(credentials, SERVER_PASSWORD):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid server credentials")

    try:
        await proxy.add_streampoint(stream_data.stream_point)
        content = {
            "message": f"streampoint {stream_data.stream_point} created successfully"
        }
        return JSONResponse(content=content)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.delete("/streampoints/{streampoint}", status_code=status.HTTP_200_OK)
async def delete_streampoint(
        streampoint: str,
        credentials: HTTPBasicCredentials = Depends(security)
        ) -> JSONResponse:
    if not verify_password(credentials, SERVER_PASSWORD):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid server credentials")

    try:
        content = {
            "delete": "success",
            "streampoint": streampoint
        }
        await proxy.remove_streampoint(streampoint)
        return JSONResponse(content=content)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="streampoint not found")


@app.get("/streampoints/", response_model=List[StreamPointInfo], status_code=status.HTTP_200_OK)
async def list_stream_points() -> list:
    """List all available stream points with connection status"""
    mp_list = []
    for sp in proxy.stream_points:
        client_count = 0
        if sp in proxy.client_queues:
            client_count = len(proxy.client_queues[sp])
        server_connected = False
        if sp in proxy.server_connections and proxy.server_connections[sp] != {}:
            server_connected = True
        mp_list.append(
            StreamPointInfo(
                stream_point=sp,
                client_count=client_count,
                server_connected=server_connected
            )
        )
    return mp_list


@app.post("/users/", status_code=status.HTTP_201_CREATED)
async def create_stream_user(
        user_data: StreamUsers,
        credentials: HTTPBasicCredentials = Depends(security)
        ) -> JSONResponse:
    """Create a new user (only authorized servers can do this)"""
    if not verify_password(credentials, SERVER_PASSWORD):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid server credentials")

    try:
        await proxy.add_stream_user(
            username=user_data.login,
            password=user_data.password,
            allowed_streampoints=user_data.allowed_streampoints
        )
        content = {
            "message": f"User {user_data.login} created successfully"
        }
        return JSONResponse(content=content)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/users/", response_model=List[StreamUsersInfo], status_code=status.HTTP_200_OK)
async def list_stream_points() -> list:
    """List all users"""
    return [
        StreamUsersInfo(
            login=user,
            password=data['password'],
            allowed_streampoints=data['allowed_streampoints']
        )
        for user, data in proxy.stream_users.items()
    ]


@app.delete("/users/{username}", status_code=status.HTTP_200_OK)
async def delete_streampoint(
        username: str,
        credentials: HTTPBasicCredentials = Depends(security)
        ) -> JSONResponse:
    """Delete user"""
    if not verify_password(credentials, SERVER_PASSWORD):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid server credentials")

    try:
        await proxy.remove_stream_user(username)
        content = {
            "delete": "success",
            "user": username
        }
        return JSONResponse(content=content)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


async def run_proxy():
    asyncio.create_task(proxy.handle_broadcast())
    server = await asyncio.start_server(
        proxy.handle_connection,
        '0.0.0.0',
        2101
    )
    async with server:
        await server.serve_forever()


@app.on_event("startup")
async def startup():
    asyncio.create_task(run_proxy())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)



