import pytest

from hat import aio
from hat import json

from hat.gui import common
import hat.gui.server.client


class AdapterSession(common.AdapterSession):

    def __init__(self, user, state, notify_cb, request_cb=None):
        self._user = user
        self._state = state
        self._notify_cb = notify_cb
        self._request_cb = request_cb
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    @property
    def user(self):
        return self._user

    @property
    def state(self):
        return self._state

    @property
    def notify_cb(self):
        return self._notify_cb

    async def process_request(self, name, data):
        if not self._request_cb:
            return

        return await aio.call(self._request_cb, name, data)


class Adapter(common.Adapter):

    def __init__(self, session_cb=None, request_cb=None):
        self._session_cb = session_cb
        self._request_cb = request_cb
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    async def process_events(self, events):
        raise NotImplementedError()

    async def create_session(self, user, state, notify_cb):
        session = AdapterSession(user, state, notify_cb, self._request_cb)

        if self._session_cb:
            await aio.call(self._session_cb, session)

        return session


class AdapterManager:

    def __init__(self, adapters={}):
        self._adapters = adapters

    @property
    def adapters(self):
        return self._adapters

    async def process_events(self, events):
        raise NotImplementedError()


class Connection(aio.Resource):

    def __init__(self, notify_cb=None):
        self._notify_cb = notify_cb
        self._state = json.Storage()
        self._async_group = aio.Group()

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    @property
    def remote(self) -> str:
        raise NotImplementedError()

    @property
    def state(self) -> json.Storage:
        return self._state

    @property
    def ws(self):
        raise NotImplementedError()

    async def flush(self):
        raise NotImplementedError()

    async def notify(self,
                     name: str,
                     data: json.Data):
        if self._notify_cb:
            self._notify_cb(name, data)


async def test_create_close():
    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=AdapterManager())

    assert client.is_open

    client.close()

    await client.wait_closed()

    assert client.is_closed
    assert conn.is_closed


async def test_conn_close():
    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=AdapterManager())

    conn.close()

    await conn.wait_closed()

    assert client.is_closed
    assert conn.is_closed


async def test_user():
    conn = Connection()
    user = common.User(name='user1',
                       roles=['r1', 'r2'],
                       view='v1')

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=AdapterManager())

    assert client.user == user

    await client.async_close()


async def test_adapter_session():
    session_queue = aio.Queue()
    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    adapter_session = await session_queue.get()

    assert adapter_session.is_open
    assert adapter_session.user == user

    await client.async_close()

    assert adapter_session.is_closed


async def test_adapter_session_close():
    session_queue = aio.Queue()
    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    adapter_session = await session_queue.get()

    assert adapter_session.is_open

    adapter_session.close()

    await client.wait_closed()
    assert adapter_session.is_closed


async def test_adapter_session_state():
    session_queue = aio.Queue()
    conn_state_queue = aio.Queue()

    conn = Connection()
    conn.state.register_change_cb(conn_state_queue.put_nowait)
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    adapter_session = await session_queue.get()

    assert adapter_session.state
    assert adapter_session.state.data is None

    adapter_session.state.set([], {'abc': '123'})

    conn_state = await conn_state_queue.get()
    assert conn_state == {'a1': adapter_session.state.data}

    await client.async_close()


async def test_multi_adapter_sessions_state():
    session_queue = aio.Queue()
    conn_state_queue = aio.Queue()

    conn = Connection()
    conn.state.register_change_cb(conn_state_queue.put_nowait)
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {f'a{i}': Adapter(session_cb=session_queue.put_nowait)
                for i in range(10)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    adapter_sessions = {}
    for adater_name in adapters.keys():
        adapter_session = await session_queue.get()
        adapter_session.state.set([], f'adapter {adater_name} state')
        adapter_sessions[adater_name] = adapter_session

        conn_state = await conn_state_queue.get()

        assert conn_state == {
            set_adptr_name: set_adptr_session.state.data
            for set_adptr_name, set_adptr_session in adapter_sessions.items()}

    # closing one adapter session closes client and all other sessions
    adapter_sessions.pop(adater_name).close()

    await client.wait_closed()
    for adapter_session in adapter_sessions.values():
        assert adapter_session.is_closed


async def test_process_request():
    request_data = {'some': "request data"}
    request_result = 'request result'

    def on_request(name, data):
        assert name == 'abc'
        assert data == request_data
        return request_result

    session_queue = aio.Queue()

    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait,
        request_cb=on_request)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    await session_queue.get()

    ret = await client.process_request('a1/abc', request_data)
    assert ret == request_result

    await client.async_close()


async def test_process_request_unsupported_adapter():
    session_queue = aio.Queue()

    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    await session_queue.get()

    with pytest.raises(Exception):
        await client.process_request('a2/abc', 123)

    await client.async_close()


async def test_process_request_invalid_request_name():
    session_queue = aio.Queue()

    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    await session_queue.get()

    with pytest.raises(Exception):
        await client.process_request('blabla', 123)

    await client.async_close()


async def test_process_request_conn_closed():
    session_queue = aio.Queue()

    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    await session_queue.get()

    conn.close()

    with pytest.raises(Exception):
        await client.process_request('a1/abc', 123)

    await client.async_close()


async def test_process_request_session_exc():

    class SessionProccessTestExc(Exception):
        pass

    def on_request(name, data):
        raise SessionProccessTestExc()

    session_queue = aio.Queue()

    conn = Connection()
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait,
        request_cb=on_request)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    await session_queue.get()

    with pytest.raises(SessionProccessTestExc):
        await client.process_request('a1/abc', 123)

    await client.async_close()


async def test_notify():
    session_queue = aio.Queue()
    conn_notify_queue = aio.Queue()

    def on_conn_notify(name, data):
        conn_notify_queue.put_nowait((name, data))

    conn = Connection(notify_cb=on_conn_notify)
    user = common.User(name='user1',
                       roles=[],
                       view='v1')
    adapters = {'a1': Adapter(
        session_cb=session_queue.put_nowait)}

    adapter_manager = AdapterManager(adapters)

    client = hat.gui.server.client.Client(
        conn=conn,
        user=user,
        adapter_manager=adapter_manager)

    adapter_session = await session_queue.get()

    adapter_session.notify_cb('abc', {'xyz': 123})

    name, data = await conn_notify_queue.get()
    assert name == 'a1/abc'
    assert data == {'xyz': 123}

    await client.async_close()
