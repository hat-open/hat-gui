"""GUI web server"""

import asyncio
import contextlib
import functools
import hashlib
import importlib.resources
import logging
import typing
import urllib

from hat import aio
from hat import json
from hat import juggler
from hat.gui import common
import hat.gui.view


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""

autoflush_delay: float = 0.2
"""Juggler autoflush delay"""


async def create_server(conf: json.Data,
                        adapters: typing.Dict[str, common.Adapter],
                        views: hat.gui.view.ViewManager
                        ) -> 'Server':
    """Create server"""
    server = Server()
    server._adapters = adapters
    server._views = views
    server._initial_view = conf['initial_view']
    server._users = {i['name']: i for i in conf['users']}
    server._clients = {}

    exit_stack = contextlib.ExitStack()
    try:
        ui_path = exit_stack.enter_context(
            importlib.resources.path(__package__, 'ui'))

        addr = urllib.parse.urlparse(conf['address'])
        server._srv = await juggler.listen(host=addr.hostname,
                                           port=addr.port,
                                           connection_cb=server._on_connection,
                                           request_cb=server._on_request,
                                           static_dir=ui_path,
                                           autoflush_delay=autoflush_delay,
                                           parallel_requests=True)

        try:
            server.async_group.spawn(aio.call_on_cancel, exit_stack.close)

        except Exception:
            await aio.uncancellable(server.async_close())
            raise

    except BaseException:
        exit_stack.close()
        raise

    mlog.debug("web server listening on %s", conf['address'])
    return server


class Server(aio.Resource):
    """Server"""

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._srv.async_group

    async def _on_connection(self, conn):
        try:
            client = _Client(conn=conn,
                             adapters=self._adapters,
                             views=self._views,
                             initial_view=self._initial_view,
                             users=self._users)
            self._clients[conn] = client

            await client.wait_closing()

        finally:
            conn.close()
            self._clients.pop(conn, None)

    async def _on_request(self, conn, name, data):
        client = self._clients.get(conn)
        if not client:
            raise Exception('invalid connection')

        return client.process_request(name, data)


class _Client(aio.Resource):

    def __init__(self,
                 conn: juggler.Connection,
                 adapters: typing.Dict[str, common.Adapter],
                 views: hat.gui.view.ViewManager,
                 initial_view: typing.Optional[str],
                 users: typing.Dict[str, json.Data]):
        self._conn = conn
        self._adapters = adapters
        self._views = views
        self._initial_view = initial_view
        self._users = users
        self._req_queue = aio.Queue()

        self.async_group.spawn(self._client_loop)

    @property
    def async_group(self):
        return self._conn.async_group

    async def process_request(self,
                              name: str,
                              data: json.Data
                              ) -> json.Data:
        future = asyncio.Future()
        try:
            self._req_queue.put_nowait((future, name, data))
            return await future

        except (aio.QueueClosedError, ConnectionError):
            raise Exception('connection closed')

    async def _client_loop(self):
        user = None
        try:
            while True:
                if not user:
                    self._init_state(None, self._initial_view, {})

                while not user:
                    user = await self._process_loop({})

                while user:
                    async with self.async_group.create_subgroup() as subgroup:
                        sessions = {}
                        states = {}
                        req_queues = {}

                        for name, adapter in self._adapters.items():
                            state = json.Storage()
                            notify_cb = functools.partial(self._notify, name)
                            states[name] = state

                            session = await adapter.create_session(
                                user['name'], user['roles'], state, notify_cb)
                            await common.bind_resource(subgroup, session)
                            sessions[name] = session

                            req_queue = aio.Queue()
                            subgroup.spawn(_session_loop, session, req_queue)
                            req_queues[name] = req_queue

                        with contextlib.ExitStack() as exit_stack:
                            for name, state in states.items():
                                set_state = functools.partial(
                                    self._set_adapter_state, name)
                                exit_stack.enter_context(
                                    state.register_change_cb(set_state))

                            self._init_state(user, user['view'], states)

                            user = await self._process_loop(req_queues)

        finally:
            self.close()
            self._req_queue.close()

            while not self._req_queue.empty():
                future, _, __ = self._req_queue.get_nowait()
                if future.done():
                    continue
                future.set_exception(ConnectionError())

    async def _process_loop(self, req_queues):
        while True:
            future, req_name, req_data = await self._req_queue.get()
            if future.done():
                continue

            try:
                req_adapter, req_name = _parse_req_name(req_name)

                if req_adapter:
                    queue = req_queues.get(req_adapter)
                    if queue is None:
                        raise Exception("unsupported adapter")

                    queue.put_nowait((future, req_name, req_data))
                    future = None

                elif req_adapter is None and req_name == 'logout':
                    return None

                elif req_adapter is None and req_name == 'login':
                    user = _authenticate(self._users,
                                         req_data['name'],
                                         req_data['password'])
                    if not user:
                        future.set_exception(Exception("authentication error"))
                    return None

                else:
                    raise Exception("unsupported request")

            except Exception as e:
                future.set_exception(e)

            finally:
                if future and not future.done():
                    future.set_result(None)

    def _init_state(self, user, view_name, adapter_states):
        view = self._views.get(view_name) if view_name else None
        self._conn.state.set([], {
            'user': (user['name'] if user else None),
            'roles': (user['roles'] if user else []),
            'view': (view.data if view else None),
            'conf': (view.conf if view else None),
            'adapters': {adapter: state.data
                         for adapter, state in adapter_states.items()}})

    def _set_adapter_state(self, adapter_name, data):
        self._conn.state.set(['adapters', adapter_name], data)

    def _notify(self, adapter_name, name, data):
        try:
            self.async_group.spawn(self._conn.notify, f'{adapter_name}/{name}',
                                   data)

        except Exception:
            pass


def _parse_req_name(name):
    segments = name.split('/', 1)

    if len(segments) == 1:
        return None, segments[0]

    if len(segments) == 2:
        return segments[0], segments[1]

    raise ValueError('invalid name')


def _authenticate(users, name, password):
    user = users.get(name)
    if not user:
        return

    password_hash = hashlib.sha256(password.encode('utf-8')).digest()

    user_salt = bytes.fromhex(user['password']['salt'])
    user_hash = bytes.fromhex(user['password']['hash'])

    h = hashlib.sha256()
    h.update(user_salt)
    h.update(password_hash)

    if h.digest() != user_hash:
        return

    return user


async def _session_loop(session, req_queue):
    try:
        while True:
            future, req_name, req_data = await req_queue.get()
            if future.done():
                continue

            try:
                result = await session.process_request(req_name, req_data)
                if not future.done():
                    future.set_result(result)

            except Exception as e:
                if not future.done():
                    future.set_exception(e)

            finally:
                if not future.done():
                    future.set_exception(ConnectionError())

    finally:
        session.close()
        req_queue.close()

        while not req_queue.empty():
            future, _, __ = req_queue.get_nowait()
            if future.done():
                continue
            future.set_exception(ConnectionError())
