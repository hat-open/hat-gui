import asyncio
import contextlib
import functools
import logging

from hat import aio
from hat import json
from hat import juggler

from hat.gui import common
import hat.gui.server.adapter


mlog: logging.Logger = logging.getLogger(__name__)


class Client(aio.Resource):

    def __init__(self,
                 conn: juggler.Connection,
                 user: common.User,
                 adapter_manager: hat.gui.server.adapter.AdapterManager,
                 req_queue_size: int = 0):
        self._conn = conn
        self._user = user
        self._adapter_manager = adapter_manager
        self._loop = asyncio.get_running_loop()
        self._req_queue = aio.Queue(req_queue_size)

        self.async_group.spawn(self._client_loop)

    @property
    def async_group(self) -> aio.Group:
        return self._conn.async_group

    @property
    def user(self) -> common.User:
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
            mlog.debug("starting client loop (user %s)", self._user.name)
            sessions = {}

            for name, adapter in self._adapter_manager.adapters.items():
                mlog.debug("creating adapter sessions (user %s; adapter %s)",
                           self._user.name, name)
                session = await _create_adapter_session_proxy(
                    user=self._user,
                    adapter=adapter,
                    notify_cb=functools.partial(self._notify, name))
                await _bind_resource(self.async_group, session)

                sessions[name] = session

            with contextlib.ExitStack() as exit_stack:
                for name, session in sessions.items():
                    exit_stack.enter_context(
                        session.state.register_change_cb(
                            functools.partial(self._conn.state.set,
                                              name)))

                await self._process_loop(sessions)

        except Exception as e:
            mlog.error("client loop error: %s", e, exc_info=e)

        finally:
            mlog.debug("stopping client loop")
            self.close()
            self._req_queue.close()

            while not self._req_queue.empty():
                future, _, __ = self._req_queue.get_nowait()
                if future.done():
                    continue
                future.set_exception(ConnectionError())

    async def _process_loop(self, sessions):
        while True:
            mlog.debug("waiting for request")
            future, req_name, req_data = await self._req_queue.get()
            if future.done():
                continue

            mlog.debug("processing request %s", req_name)

            try:
                try:
                    req_adapter, req_name = req_name.split('/', 1)

                except Exception:
                    mlog.debug("invalid request name")
                    raise Exception("invalid request name")

                session = sessions.get(req_adapter)
                if session is None:
                    mlog.debug("invalid adapter %s", req_adapter)
                    raise Exception("unsupported adapter")

                mlog.debug("queuing adapter request (adapter: %s; name: %s)",
                           req_adapter, req_name)
                await session.process_request(future, req_name, req_data)
                future = None

            except Exception as e:
                future.set_exception(e)

            finally:
                if future and not future.done():
                    future.set_result(None)

    def _notify(self, adapter_name, name, data):
        mlog.debug("sending notification (adapter: %s; name: %s)",
                   adapter_name, name)
        self.async_group.spawn(self._conn.notify, f'{adapter_name}/{name}',
                               data)


async def _create_adapter_session_proxy(user, adapter, notify_cb,
                                        req_queue_size=0):
    proxy = _AdapterSessionProxy()
    proxy._state = json.Storage()
    proxy._req_queue = aio.Queue(req_queue_size)

    proxy._session = await aio.call(adapter.create_session,
                                    user, proxy._state, notify_cb)

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


async def _bind_resource(async_group, resource):
    try:
        async_group.spawn(aio.call_on_cancel, resource.async_close)
        async_group.spawn(aio.call_on_done, resource.wait_closing(),
                          async_group.close)

    except Exception:
        await aio.uncancellable(resource.async_close())
        raise
