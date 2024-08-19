"""GUI web server"""

import asyncio
import contextlib
import functools
import importlib.resources
import logging

import aiohttp.web

from hat import aio
from hat import json
from hat import juggler
import hat.event.common

import hat.gui.server.user
import hat.gui.server.view
import hat.gui.server.adapter


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""


async def create_server(host: str,
                        port: int,
                        name: str,
                        initial_view: str | None,
                        client_conf: json.Data | None,
                        user_manager: hat.gui.server.user.UserManager,
                        view_manager: hat.gui.server.view.ViewManager,
                        adapter_manager: hat.gui.server.adapter.AdapterManager,
                        eventer_client: hat.event.eventer.Client,
                        autoflush_delay: float = 0.2
                        ) -> 'Server':
    """Create server"""
    server = Server()
    server._name = name
    server._initial_view = initial_view
    server._client_conf = client_conf
    server._user_manager = user_manager
    server._view_manager = view_manager
    server._adapter_manager = adapter_manager
    server._eventer_client = eventer_client
    server._clients = {}

    exit_stack = contextlib.ExitStack()
    try:
        ui_path = exit_stack.enter_context(
            importlib.resources.as_file(
                importlib.resources.files(__package__) / 'ui'))

        additional_routes = [aiohttp.web.get('/client_conf',
                                             server._get_client_conf)]

        server._srv = await juggler.listen(host=host,
                                           port=port,
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

    mlog.debug("web server listening on %s:%s", host, port)
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
            client = Client(conn=conn,
                            initial_view=self._initial_view,
                            user_manager=self._user_manager,
                            view_manager=self._view_manager,
                            adapter_manager=self._adapter_manager,
                            user_change_cb=self._on_user_change)
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

    async def _on_user_change(self):
        event = hat.event.common.RegisterEvent(
            type=('gui', self._name, 'clients'),
            source_timestamp=None,
            payload=hat.event.common.EventPayloadJson(
                [{'remote': conn.remote,
                  'user': client.user.name}
                 for conn, client in self._clients.items()
                 if client.user]))

        mlog.debug("registering clients event")
        with contextlib.suppress(Exception):
            await self._eventer_client.register([event])


class Client(aio.Resource):

    def __init__(self,
                 conn: juggler.Connection,
                 initial_view: str | None,
                 user_manager: hat.gui.server.user.UserManager,
                 view_manager: hat.gui.server.view.ViewManager,
                 adapter_manager: hat.gui.server.adapter.AdapterManager,
                 user_change_cb: aio.AsyncCallable[[], None],
                 req_queue_size: int = 0):
        self._conn = conn
        self._initial_view = initial_view
        self._user_manager = user_manager
        self._view_manager = view_manager
        self._adapter_manager = adapter_manager
        self._user_change_cb = user_change_cb
        self._loop = asyncio.get_running_loop()
        self._req_queue = aio.Queue(req_queue_size)
        self._user = None

        self.async_group.spawn(self._client_loop)

    @property
    def async_group(self) -> aio.Group:
        return self._conn.async_group

    @property
    def user(self) -> hat.gui.server.user.User | None:
        return self._user

    async def process_request(self,
                              name: str,
                              data: json.Data
                              ) -> json.Data:
        future = self._loop.create_future()
        try:
            await self._req_queue.put((future, name, data))
            return await future

        except (aio.QueueClosedError, ConnectionError):
            raise Exception('connection closed')

    async def _client_loop(self):
        try:
            mlog.debug("starting client loop")
            while True:
                mlog.debug("setting initial state")
                await self._init_state({})

                mlog.debug("waiting for authentication")
                while not self._user:
                    await self._process_loop({})

                while self._user:
                    mlog.debug("starting session (user %s)",
                               self._user.name)
                    async with self.async_group.create_subgroup() as subgroup:
                        sessions = {}

                        adapters = self._adapter_manager.adapters
                        for name, adapter in adapters.items():
                            mlog.debug("creating adapter sessions "
                                       "(user %s; adapter %s)",
                                       self._user.name, name)
                            notify_cb = functools.partial(self._notify, name)
                            session = await _create_adapter_session_proxy(
                                user=self._user,
                                adapter=adapter,
                                notify_cb=notify_cb)
                            await _bind_resource(subgroup, session)
                            sessions[name] = session

                        with contextlib.ExitStack() as exit_stack:
                            for name, session in sessions.items():
                                exit_stack.enter_context(
                                    session.state.register_change_cb(
                                        functools.partial(self._conn.state.set,
                                                          name)))

                            mlog.debug("setting initial state (user %s)",
                                       self._user.name)
                            await self._init_state(sessions)

                            await self._process_loop(sessions)

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

            await aio.uncancellable(self._set_user(None))

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
                    await session.process_request(future, req_name, req_data)
                    future = None

                elif req_adapter is None and req_name == 'logout':
                    mlog.debug("user logout")
                    await self._set_user(None)
                    return

                elif req_adapter is None and req_name == 'login':
                    try:
                        user = self._user_manager.authenticate(
                            name=req_data['name'],
                            password=req_data['password'])

                    except hat.gui.server.user.AuthenticationError as e:
                        mlog.debug("authentication error: %s", e)
                        raise Exception("authentication error")

                    mlog.debug("authentication success (user %s)", user.name)
                    await self._set_user(user)
                    return

                else:
                    mlog.debug("unsupported request")
                    raise Exception("unsupported request")

            except Exception as e:
                future.set_exception(e)

            finally:
                if future and not future.done():
                    future.set_result(None)

    async def _init_state(self, sessions):
        view_name = self._user.view if self._user else self._initial_view

        if view_name:
            view = await self._view_manager.get(view_name)

        else:
            view = None

        self._conn.state.set([], {name: session.state.data
                                  for name, session in sessions.items()})
        await self._conn.flush()

        await self._conn.notify('init', {
            'user': (self._user.name if self._user else None),
            'roles': (list(self._user.roles) if self._user else []),
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

    async def _set_user(self, user):
        if self._user == user:
            return

        mlog.debug("changing user %s -> %s", (self._user and self._user.name),
                   (user and user.name))
        self._user = user

        await aio.call(self._user_change_cb)


async def _create_adapter_session_proxy(user, adapter, notify_cb,
                                        req_queue_size=0):
    proxy = _AdapterSessionProxy()
    proxy._state = json.Storage()
    proxy._req_queue = aio.Queue(req_queue_size)

    proxy._session = await aio.call(adapter.create_session,
                                    user.name, user.roles,
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

    async def process_request(self,
                              future: asyncio.Future,
                              name: str,
                              data: json.Data):
        await self._req_queue.put((future, name, data))

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


async def _bind_resource(async_group, resource):
    try:
        async_group.spawn(aio.call_on_cancel, resource.async_close)
        async_group.spawn(aio.call_on_done, resource.wait_closing(),
                          async_group.close)

    except Exception:
        await aio.uncancellable(resource.async_close())
        raise
