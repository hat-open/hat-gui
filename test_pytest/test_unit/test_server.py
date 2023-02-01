import asyncio

import pytest

from hat import aio
from hat import juggler
from hat import util
import hat.event.common

from hat.gui import common
import hat.gui.passwd
import hat.gui.server


@pytest.fixture
def ui_port():
    return util.get_unused_tcp_port()


@pytest.fixture
def ui_addr(ui_port):
    return f'http://127.0.0.1:{ui_port}'


@pytest.fixture
def ws_addr(ui_addr):
    return f'{ui_addr}/ws'


@pytest.fixture
def patch_autoflush_delay(monkeypatch):
    monkeypatch.setattr(hat.gui.server, 'autoflush_delay', 0)


class Adapter(common.Adapter):

    def __init__(self):
        self._session_queue = aio.Queue()
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    @property
    def session_queue(self):
        return self._session_queue

    async def create_session(self, user, roles, state, notify_cb):
        session = Session(user, roles, state, notify_cb)
        self._session_queue.put_nowait(session)
        return session

    async def process_events(self, events):
        raise NotImplementedError()


class Session(aio.Resource):

    def __init__(self, user, roles, state, notify_cb):
        self._user = user
        self._roles = roles
        self._state = state
        self._notify_cb = notify_cb
        self._async_group = aio.Group()
        self._request_queue = aio.Queue()

    @property
    def async_group(self):
        return self._async_group

    @property
    def user(self):
        return self._user

    @property
    def roles(self):
        return self._roles

    @property
    def state(self):
        return self._state

    @property
    def request_queue(self):
        return self._request_queue

    def notify(self, name, data):
        self._notify_cb(name, data)

    async def process_request(self, name, data):
        future = asyncio.Future()
        self._request_queue.put_nowait((name, data, future))
        return await future


class ViewManager(aio.Resource):

    def __init__(self, views):
        self._views = views
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    async def get(self, name):
        return self._views[name]


def create_user_conf(name, password, roles=[], view=None):
    return {'name': name,
            'password': hat.gui.passwd.generate(password),
            'roles': roles,
            'view': view}


async def test_empty_server(ui_addr, ws_addr):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': []}
    adapters = {}
    views = ViewManager({})
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(ws_addr)

    assert client.is_open
    assert server.is_open

    await client.async_close()
    await server.async_close()
    await views.async_close()


async def test_login(ui_addr, ws_addr):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': [create_user_conf(name='user',
                                       password='pass',
                                       roles=['a', 'b'])]}
    adapters = {}
    views = ViewManager({})
    notify_queue = aio.Queue()
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(
        ws_addr,
        lambda client, name, data: notify_queue.put_nowait((name, data)))

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data == {'user': None,
                    'roles': [],
                    'view': None,
                    'conf': None}

    with pytest.raises(Exception):
        await client.send('login', {'name': 'abc',
                                    'password': 'bca'})

    with pytest.raises(Exception):
        await client.send('login', {'name': 'user',
                                    'password': 'abc'})

    assert notify_queue.empty()

    await client.send('login', {'name': 'user',
                                'password': 'pass'})

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data == {'user': 'user',
                    'roles': ['a', 'b'],
                    'view': None,
                    'conf': None}

    await client.send('logout', None)

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data == {'user': None,
                    'roles': [],
                    'view': None,
                    'conf': None}

    await client.async_close()
    await server.async_close()
    await views.async_close()


async def test_session(ui_addr, ws_addr):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': [create_user_conf(name='user',
                                       password='pass',
                                       roles=['a', 'b'])]}
    adapter = Adapter()
    adapters = {'adapter': adapter}
    views = ViewManager({})
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(ws_addr)

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await adapter.session_queue.get()

    assert session.is_open
    assert session.user == 'user'
    assert session.roles == ['a', 'b']

    await client.send('logout', None)

    assert not session.is_open

    await client.async_close()
    await server.async_close()
    await views.async_close()


async def test_request_response(ui_addr, ws_addr):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': [create_user_conf(name='user',
                                       password='pass')]}
    adapter = Adapter()
    adapters = {'adapter': adapter}
    views = ViewManager({})
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(ws_addr)

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await adapter.session_queue.get()

    with pytest.raises(Exception):
        await client.send('abc1', None)

    with pytest.raises(Exception):
        await client.send('xyz/abc2', None)

    task = asyncio.ensure_future(client.send('adapter/abc3', 123))

    name, data, future = await session.request_queue.get()
    assert name == 'abc3'
    assert data == 123
    future.set_result(321)

    result = await task
    assert result == 321

    await client.async_close()
    await server.async_close()
    await views.async_close()


async def test_state(ui_addr, ws_addr, patch_autoflush_delay):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': [create_user_conf(name='user',
                                       password='pass')]}
    adapter = Adapter()
    adapters = {'adapter': adapter}
    views = ViewManager({})
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(ws_addr)

    state_queue = aio.Queue()
    client.state.register_change_cb(state_queue.put_nowait)
    if client.state.data is not None:
        state_queue.put_nowait(client.state.data)

    state = await state_queue.get()
    assert state == {}

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await adapter.session_queue.get()

    state = await state_queue.get()
    assert state == {'adapter': None}

    session.state.set([], 123)

    state = await state_queue.get()
    assert state == {'adapter': 123}

    await client.async_close()
    await server.async_close()
    await views.async_close()


async def test_notify(ui_addr, ws_addr):
    conf = {'address': ui_addr,
            'initial_view': None,
            'users': [create_user_conf(name='user',
                                       password='pass')]}
    adapter = Adapter()
    adapters = {'adapter': adapter}
    views = ViewManager({})
    notify_queue = aio.Queue()
    server = await hat.gui.server.create_server(conf, adapters, views)
    client = await juggler.connect(
        ws_addr,
        lambda client, name, data: notify_queue.put_nowait((name, data)))

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data['user'] is None

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await adapter.session_queue.get()

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data['user'] == 'user'

    session.notify('abc', 123)

    name, data = await notify_queue.get()
    assert name == 'adapter/abc'
    assert data == 123

    await client.async_close()
    await server.async_close()
    await views.async_close()
