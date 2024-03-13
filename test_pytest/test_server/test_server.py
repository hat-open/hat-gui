import pytest

from hat import aio
from hat import juggler
from hat import util
import hat.event.common

from hat.gui import common
import hat.gui.server.server
import hat.gui.server.user


class AdapterSession(common.AdapterSession):

    def __init__(self, user, roles, state, notify_cb, request_cb=None):
        self._user = user
        self._roles = roles
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
    def roles(self):
        return self._roles

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

    async def create_session(self, user, roles, state, notify_cb):
        session = AdapterSession(user, roles, state, notify_cb,
                                 self._request_cb)

        if self._session_cb:
            await aio.call(self._session_cb, session)

        return session


class UserManager:

    def __init__(self, users={}):
        self._users = users

    def authenticate(self, name, password):
        user = self._users.get((name, password))
        if not user:
            raise hat.gui.server.user.AuthenticationError()

        return user


class ViewManager:

    def __init__(self, views={}):
        self._views = views

    async def get(self, name):
        return self._views[name]


class AdapterManager:

    def __init__(self, adapters={}):
        self._adapters = adapters

    @property
    def adapters(self):
        return self._adapters

    async def process_events(self, events):
        raise NotImplementedError()


@pytest.fixture
def port():
    return util.get_unused_tcp_port()


@pytest.fixture
def ws_addr(port):
    return f'ws://127.0.0.1:{port}/ws'


async def test_empty_server(port, ws_addr):
    user_manager = UserManager()
    view_manager = ViewManager()
    adapter_manager = AdapterManager()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
    client = await juggler.connect(ws_addr)

    assert client.is_open
    assert server.is_open

    await client.async_close()
    await server.async_close()


async def test_login(port, ws_addr):
    notify_queue = aio.Queue()

    users = {('user', 'pass'): hat.gui.server.user.User(name='user',
                                                        roles={'a'},
                                                        view=None)}

    user_manager = UserManager(users)
    view_manager = ViewManager()
    adapter_manager = AdapterManager()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
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
                    'roles': ['a'],
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


async def test_session(port, ws_addr):
    session_queue = aio.Queue()

    users = {('user', 'pass'): hat.gui.server.user.User(name='user',
                                                        roles={'a', 'b'},
                                                        view=None)}

    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    user_manager = UserManager(users)
    view_manager = ViewManager()
    adapter_manager = AdapterManager(adapters)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
    client = await juggler.connect(ws_addr)

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await session_queue.get()

    assert session.is_open
    assert session.user == 'user'
    assert session.roles == {'a', 'b'}

    await client.send('logout', None)

    assert not session.is_open

    await client.async_close()
    await server.async_close()


async def test_request_response(port, ws_addr):
    session_queue = aio.Queue()

    def on_request(name, data):
        assert name == 'abc3'
        assert data == 123
        return 321

    users = {('user', 'pass'): hat.gui.server.user.User(name='user',
                                                        roles={'a', 'b'},
                                                        view=None)}

    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait,
                              request_cb=on_request)}

    user_manager = UserManager(users)
    view_manager = ViewManager()
    adapter_manager = AdapterManager(adapters)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
    client = await juggler.connect(ws_addr)

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    await session_queue.get()

    with pytest.raises(Exception):
        await client.send('abc1', None)

    with pytest.raises(Exception):
        await client.send('xyz/abc2', None)

    result = await client.send('a1/abc3', 123)
    assert result == 321

    await client.async_close()
    await server.async_close()


async def test_state(port, ws_addr):
    session_queue = aio.Queue()
    state_queue = aio.Queue()

    users = {('user', 'pass'): hat.gui.server.user.User(name='user',
                                                        roles={'a', 'b'},
                                                        view=None)}

    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    user_manager = UserManager(users)
    view_manager = ViewManager()
    adapter_manager = AdapterManager(adapters)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
    client = await juggler.connect(ws_addr)

    client.state.register_change_cb(state_queue.put_nowait)
    if client.state.data is not None:
        state_queue.put_nowait(client.state.data)

    state = await state_queue.get()
    assert state == {}

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await session_queue.get()

    state = await state_queue.get()
    assert state == {'a1': None}

    session.state.set([], 123)

    state = await state_queue.get()
    assert state == {'a1': 123}

    await client.async_close()
    await server.async_close()


async def test_notify(port, ws_addr):
    session_queue = aio.Queue()
    notify_queue = aio.Queue()

    users = {('user', 'pass'): hat.gui.server.user.User(name='user',
                                                        roles={'a', 'b'},
                                                        view=None)}

    adapters = {'a1': Adapter(session_cb=session_queue.put_nowait)}

    user_manager = UserManager(users)
    view_manager = ViewManager()
    adapter_manager = AdapterManager(adapters)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        initial_view=None,
        client_conf=None,
        user_manager=user_manager,
        view_manager=view_manager,
        adapter_manager=adapter_manager,
        autoflush_delay=0)
    client = await juggler.connect(
        ws_addr,
        lambda client, name, data: notify_queue.put_nowait((name, data)))

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data['user'] is None

    await client.send('login', {'name': 'user',
                                'password': 'pass'})
    session = await session_queue.get()

    name, data = await notify_queue.get()
    assert name == 'init'
    assert data['user'] == 'user'

    session.notify_cb('abc', 123)

    name, data = await notify_queue.get()
    assert name == 'a1/abc'
    assert data == 123

    await client.async_close()
    await server.async_close()
