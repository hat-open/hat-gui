"""GUI web server"""

import asyncio
import contextlib
import functools
import hashlib
import importlib.resources
import logging
import urllib

import aiohttp.web

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
                        adapters: dict[str, common.Adapter],
                        views: hat.gui.view.ViewManager
                        ) -> 'Server':
    """Create server"""
    server = Server()
    server._adapters = adapters
    server._views = views
    server._initial_view = conf['initial_view']
    server._users = {i['name']: i for i in conf['users']}
    server._client_conf = conf.get('client')
    server._clients = {}

    exit_stack = contextlib.ExitStack()
    try:
        ui_path = exit_stack.enter_context(
            importlib.resources.as_file(
                importlib.resources.files(__package__) / 'ui'))

        addr = urllib.parse.urlparse(conf['address'])
        additional_routes = [aiohttp.web.get('/client_conf',
                                             server._get_client_conf)]
        server._srv = await juggler.listen(host=addr.hostname,
                                           port=addr.port,
                                           connection_cb=server._on_connection,
                                           request_cb=server._on_request,
                                           static_dir=ui_path,
                                           autoflush_delay=autoflush_delay,
                                           parallel_requests=True,
                                           additional_routes=additional_routes)

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

    async def _get_client_conf(self, req):
        return aiohttp.web.json_response(self._client_conf)

    async def _on_connection(self, conn):
        try:
            mlog.debug("creating new client (new juggler connection)")
            client = _Client(conn=conn,
                             adapters=self._adapters,
                             views=self._views,
                             initial_view=self._initial_view,
                             users=self._users)
            self._clients[conn] = client

            await client.wait_closing()

        except Exception as e:
            mlog.error("on connection error: %s", e, exc_info=e)

        finally:
            mlog.debug("closing juggler connection")
            conn.close()
            self._clients.pop(conn, None)

    async def _on_request(self, conn, name, data):
        mlog.debug("new juggler request: %s", name)

        client = self._clients.get(conn)
        if not client:
            raise Exception('invalid connection')

        return await client.process_request(name, data)


class _Client(aio.Resource):

    def __init__(self,
                 conn: juggler.Connection,
                 adapters: dict[str, common.Adapter],
                 views: hat.gui.view.ViewManager,
                 initial_view: str | None,
                 users: dict[str, json.Data]):
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
            mlog.debug("starting client loop")
            while True:
                mlog.debug("setting initial state")
                await self._init_state(None, self._initial_view, {})

                mlog.debug("waiting for authentication")
                while not user:
                    user = await self._process_loop({})

                mlog.debug("authenticated user: %s", user['name'])
                while user:
                    user = await self._sessions_loop(user)

        except Exception as e:
            mlog.debug("client loop error: %s", e, exc_info=e)

        finally:
            mlog.debug("stopping client loop")
            self.close()
            self._req_queue.close()

            while not self._req_queue.empty():
                future, _, __ = self._req_queue.get_nowait()
                if future.done():
                    continue
                future.set_exception(ConnectionError())

    async def _sessions_loop(self, user):
        mlog.debug("starting sessions loop (user %s)", user['name'])
        async with self.async_group.create_subgroup() as subgroup:
            sessions = {}

            for name, adapter in self._adapters.items():
                mlog.debug("creating adapter sessions (user %s; adapter %s)",
                           user['name'], name)
                notify_cb = functools.partial(self._notify, name)
                session = await _create_adapter_session_proxy(user, adapter,
                                                              notify_cb)
                await common.bind_resource(subgroup, session)
                sessions[name] = session

            with contextlib.ExitStack() as exit_stack:
                for name, session in sessions.items():
                    exit_stack.enter_context(
                        session.state.register_change_cb(
                            functools.partial(self._conn.state.set, name)))

                mlog.debug("setting initial state (user %s)",
                           user['name'])
                await self._init_state(user, user['view'], sessions)

                return await self._process_loop(sessions)

    async def _process_loop(self, sessions):
        while True:
            mlog.debug("waiting for request")
            future, req_name, req_data = await self._req_queue.get()
            if future.done():
                continue

            mlog.debug("processing request %s", req_name)

            try:
                req_adapter, req_name = _parse_req_name(req_name)

                if req_adapter:
                    session = sessions.get(req_adapter)
                    if session is None:
                        mlog.debug("invalid adapter %s", req_adapter)
                        raise Exception("unsupported adapter")

                    mlog.debug("queuing adapter request "
                               "(adapter: %s; name: %s)",
                               req_adapter, req_name)
                    session.process_request(future, req_name, req_data)
                    future = None

                elif req_adapter is None and req_name == 'logout':
                    mlog.debug("user logout")
                    return None

                elif req_adapter is None and req_name == 'login':
                    user = _authenticate(self._users,
                                         req_data['name'],
                                         req_data['password'])

                    if not user:
                        mlog.debug("authentication error")
                        future.set_exception(Exception("authentication error"))
                        return None

                    mlog.debug("authentication success (user %s)",
                               user['name'])
                    return user

                else:
                    mlog.debug("unsupported request")
                    raise Exception("unsupported request")

            except Exception as e:
                future.set_exception(e)

            finally:
                if future and not future.done():
                    future.set_result(None)

    async def _init_state(self, user, view_name, sessions):
        if view_name:
            view = await self._views.get(view_name)

        else:
            view = None

        self._conn.state.set([], {name: session.state.data
                                  for name, session in sessions.items()})
        await self._conn.flush()

        await self._conn.notify('init', {
            'user': (user['name'] if user else None),
            'roles': (user['roles'] if user else []),
            'view': (view.data if view else None),
            'conf': (view.conf if view else None)})

    def _notify(self, adapter_name, name, data):
        try:
            mlog.debug("sending notification (adapter: %s; name: %s)",
                       adapter_name, name)
            self.async_group.spawn(self._conn.notify, f'{adapter_name}/{name}',
                                   data)

        except Exception:
            mlog.debug("unsupported request")


async def _create_adapter_session_proxy(user, adapter, notify_cb):
    proxy = _AdapterSessionProxy()
    proxy._state = json.Storage()
    proxy._req_queue = aio.Queue()

    proxy._session = await adapter.create_session(user['name'], user['roles'],
                                                  proxy._state, notify_cb)

    proxy.async_group.spawn(proxy._session_loop)

    return proxy


class _AdapterSessionProxy(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._session.async_group

    @property
    def state(self) -> json.Storage:
        return self._state

    def process_request(self,
                        future: asyncio.Future,
                        name: str,
                        data: json.Data):
        self._req_queue.put_nowait((future, name, data))

    async def _session_loop(self):
        try:
            mlog.debug("starting adapter session loop")
            while True:
                mlog.debug("waiting for request")
                future, req_name, req_data = await self._req_queue.get()
                if future.done():
                    continue

                try:
                    mlog.debug("processing request (name: %s)", req_name)
                    result = await self._session.process_request(req_name,
                                                                 req_data)
                    if not future.done():
                        future.set_result(result)

                except Exception as e:
                    if not future.done():
                        future.set_exception(e)

                finally:
                    if not future.done():
                        future.set_exception(ConnectionError())

        except Exception as e:
            mlog.error("adapter session loop error: %s", e, exc_info=e)

        finally:
            mlog.debug("stopping adapter session loop")
            self.close()
            self._req_queue.close()

            while not self._req_queue.empty():
                future, _, __ = self._req_queue.get_nowait()
                if future.done():
                    continue
                future.set_exception(ConnectionError())


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
        mlog.debug("authentication failed - invalid name")
        return

    password_hash = hashlib.sha256(password.encode('utf-8')).digest()

    user_salt = bytes.fromhex(user['password']['salt'])
    user_hash = bytes.fromhex(user['password']['hash'])

    h = hashlib.sha256()
    h.update(user_salt)
    h.update(password_hash)

    if h.digest() != user_hash:
        mlog.debug("authentication failed - invalid password")
        return

    return user
