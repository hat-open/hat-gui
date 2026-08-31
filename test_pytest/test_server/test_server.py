import aiohttp
import pytest

from hat import aio
from hat import json
from hat import util
import hat.event.common

from hat.gui import common
from hat.gui.server.view import ViewManager
import hat.gui.server.server
import hat.gui.server.user


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


class UserSession(hat.gui.server.user.UserSession):

    def __init__(self, user, session_id, timestamp):
        super().__init__(user=user,
                         session_id=session_id,
                         timestamp=timestamp)

        self._async_group = aio.Group()

    @property
    def async_group(self) -> aio.Group:
        return self._async_group


class UserManager:

    def __init__(self, create_local_session_cb=None, get_oidc_url_cb=None,
                 create_oidc_session_cb=None):
        self._create_local_session_cb = create_local_session_cb
        self._get_oidc_url_cb = get_oidc_url_cb
        self._create_oidc_session_cb = create_oidc_session_cb
        self._sessions = {}

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    def get_oidc_url(self, name, state):
        if not self._get_oidc_url_cb:
            raise NotImplementedError()

        return self._get_oidc_url_cb(name, state)

    async def create_local_session(self, name, password):
        if not self._create_local_session_cb:
            raise NotImplementedError()

        session = self._create_local_session_cb(name, password)
        self._sessions[session.session_id] = session
        return session

    async def create_oidc_session(self, name, code):
        if not self._create_oidc_session_cb:
            raise NotImplementedError()

        return self._create_oidc_session_cb(name, code)


class AdapterManager:

    def __init__(self, adapters={}):
        self._adapters = adapters

    @property
    def adapters(self):
        return self._adapters

    async def process_events(self, events):
        raise NotImplementedError()


class EventerClient(aio.Resource):

    def __init__(self, event_cb=None):
        self._event_cb = event_cb
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    @property
    def status(self):
        raise NotImplementedError()

    async def register(self, events, with_response=False):
        if self._event_cb:
            for event in events:
                await aio.call(self._event_cb, event)

    async def query(self, params):
        raise NotImplementedError()


@pytest.fixture
def port():
    return util.get_unused_tcp_port()


@pytest.fixture
def ws_addr(port):
    return f'ws://127.0.0.1:{port}/ws'


@pytest.fixture
def http_addr(port):
    return f'http://127.0.0.1:{port}'


@pytest.fixture
async def client_http(http_addr):
    async with aiohttp.ClientSession(base_url=http_addr) as client:
        yield client


async def test_empty_server(port, ws_addr):
    user_manager = UserManager()
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    assert server.is_open

    server.close()
    await server.wait_closed()

    await eventer_client.async_close()


@pytest.mark.parametrize('success', [True, False])
async def test_login_local(port, client_http, success):
    username = 'u1'
    request_username = 'abc_u1'
    request_passwd = '123xyz'
    session_id = 'abcxyz'
    timestamp = 12345
    user = common.User(name=username,
                       roles=['r1', 'r2'],
                       view='v_u1')

    def on_create_local_session(name, password):
        assert name == request_username
        assert password == request_passwd

        if success:
            return UserSession(user=user,
                               session_id=session_id,
                               timestamp=timestamp)

        raise Exception()

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    user_login = {'name': request_username,
                  'password': request_passwd}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        if success:
            assert resp.status == 200
            session_cookie = resp.cookies.get('SESSION_ID')
            assert session_cookie.value == session_id
            assert session_cookie['httponly']
            assert int(session_cookie.get('max-age')) == (60 * 60 * 24 * 365)

        else:
            resp.status == 400

    await server.async_close()
    await eventer_client.async_close()


@pytest.mark.parametrize('logout_method', ['get', 'post'])
async def test_logout(port, client_http, logout_method):
    user_session_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    user = common.User(name=username,
                       roles=['r1', 'r2'],
                       view='v_u1')

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        user_session_queue.put_nowait(session)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    # logout session before created
    async with getattr(client_http, logout_method)(
            '/logout',
            cookies={'SESSION_ID': 'abcxyz'},
            allow_redirects=False) as resp:
        assert resp.status == 400

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    user_session = await user_session_queue.get()
    assert user_session.is_open

    async with getattr(client_http, logout_method)(
            '/logout',
            cookies={'SESSION_ID': session_id},
            allow_redirects=False) as resp:
        assert resp.status == {'get': 302,
                               'post': 200}[logout_method]

    assert user_session.is_closing
    await user_session.wait_closed()

    await server.async_close()
    await eventer_client.async_close()


async def test_get_user(port, client_http):
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    # get user before login
    async with client_http.get('/user',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 400

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    async with client_http.get('/user',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 200
        data = await resp.json()
        assert data == {'name': username,
                        'roles': roles}

    await server.async_close()
    await eventer_client.async_close()


async def test_get_ws(port, client_http, ws_addr):
    event_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient(event_cb=event_queue.put_nowait)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    # get ws before login
    client_http.cookie_jar.update_cookies({'SESSION_ID': session_id})
    with pytest.raises(Exception):
        await client_http.ws_connect(ws_addr)

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    client_http.cookie_jar.update_cookies({'SESSION_ID': session_id})
    async with client_http.ws_connect(ws_addr) as ws:
        assert not ws.closed

        event = await event_queue.get()
        assert event.type == ('gui', 'name', 'clients')
        assert len(event.payload.data) == 1
        assert event.payload.data[0]['remote'] == '127.0.0.1'
        assert event.payload.data[0]['user'] == username

    event = await event_queue.get()
    assert event.type == ('gui', 'name', 'clients')
    assert len(event.payload.data) == 0

    await server.async_close()
    await eventer_client.async_close()


async def test_juggler_connect(port, client_http, ws_addr):
    event_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient(event_cb=event_queue.put_nowait)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    with pytest.raises(Exception):
        await hat.juggler.connect(ws_addr,
                                  cookies={'SESSION_ID': session_id})

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    client_juggler = await hat.juggler.connect(
        ws_addr,
        cookies={'SESSION_ID': session_id})

    event = await event_queue.get()
    assert event.type == ('gui', 'name', 'clients')
    assert len(event.payload.data) == 1
    assert event.payload.data[0]['remote'] == '127.0.0.1'
    assert event.payload.data[0]['user'] == username

    client_juggler.close()

    event = await event_queue.get()
    assert event.type == ('gui', 'name', 'clients')
    assert len(event.payload.data) == 0

    await client_juggler.wait_closed()
    await server.async_close()
    await eventer_client.async_close()


async def test_juggler_request_response(port, client_http, ws_addr):
    event_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')
    adapter_session_queue = aio.Queue()

    def on_request(name, data):
        assert name == 'abc3'
        assert data == 123
        return 321

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    adapters = {'a1': Adapter(session_cb=adapter_session_queue.put_nowait,
                              request_cb=on_request)}

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager(adapters)
    eventer_client = EventerClient(event_cb=event_queue.put_nowait)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    client_juggler = await hat.juggler.connect(
        ws_addr,
        cookies={'SESSION_ID': session_id})

    await adapter_session_queue.get()

    with pytest.raises(Exception):
        await client_juggler.send('abc1', None)

    with pytest.raises(Exception):
        await client_juggler.send('xyz/abc2', None)

    result = await client_juggler.send('a1/abc3', 123)
    assert result == 321

    await server.async_close()
    await eventer_client.async_close()


async def test_juggler_state(port, client_http, ws_addr):
    event_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')
    adapter_session_queue = aio.Queue()

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    adapters = {'a1': Adapter(session_cb=adapter_session_queue.put_nowait)}

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager(adapters)
    eventer_client = EventerClient(event_cb=event_queue.put_nowait)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    client_juggler = await hat.juggler.connect(
        ws_addr,
        cookies={'SESSION_ID': session_id})

    adapter_session = await adapter_session_queue.get()

    state_queue = aio.Queue()
    client_juggler.state.register_change_cb(state_queue.put_nowait)

    adapter_session.state.set([], {'abc': 123})

    state_data = await state_queue.get()
    assert state_data == {'a1': {'abc': 123}}

    await client_juggler.async_close()
    await server.async_close()
    await eventer_client.async_close()


async def test_juggler_notify(port, client_http, ws_addr):
    event_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view='v_u1')
    adapter_session_queue = aio.Queue()

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    adapters = {'a1': Adapter(session_cb=adapter_session_queue.put_nowait)}

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager(adapters)
    eventer_client = EventerClient(event_cb=event_queue.put_nowait)

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    notify_queue = aio.Queue()

    def on_notify(client, adapter_name, data):
        notify_queue.put_nowait((client, adapter_name, data))

    client_juggler = await hat.juggler.connect(
        ws_addr,
        notify_cb=on_notify,
        cookies={'SESSION_ID': session_id})

    adapter_session = await adapter_session_queue.get()

    adapter_session.notify_cb('xyz', {'abc': 123})

    client_notified, name, data = await notify_queue.get()
    assert name == 'a1/xyz'
    assert data == {'abc': 123}
    assert client_notified is client_juggler

    await client_juggler.async_close()
    await server.async_close()
    await eventer_client.async_close()


async def test_get(port, client_http, tmp_path):
    view_path = tmp_path / 'v1'
    view_path.mkdir()
    file_path = view_path / 'view_file.html'
    file_content = b'abc xyz bla'
    file_path.write_bytes(file_content)
    view_conf = {'name': 'v1',
                 'roles': ['r1', 'r2'],
                 'paths': [{'path': str(view_path)}]}
    view_manager = ViewManager([view_conf])

    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view=view_conf['name'])

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    # before login (no initial view)
    async with client_http.get('view_file.html',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 500

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    async with client_http.get('view_file.html',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == file_content

    # get with invalid session_id (no initial view)
    async with client_http.get('view_file.html',
                               cookies={'SESSION_ID': 'invalid_id'}) as resp:
        assert resp.status == 500

    # get with emtpy session_id (no initial view)
    async with client_http.get('view_file.html') as resp:
        assert resp.status == 500

    # get file that does not exist
    async with client_http.get('non_existing_file.html',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 404

    await server.async_close()
    await eventer_client.async_close()


async def test_initial_view(port, client_http, tmp_path):
    view_path = tmp_path / 'v1'
    view_path.mkdir()
    view_file_content = b'abc xyz bla'
    (view_path / 'index.html').write_bytes(view_file_content)
    view_conf = {'name': 'v1',
                 'roles': ['r1', 'r2'],
                 'paths': [{'path': str(view_path)}]}

    init_view_path = tmp_path / 'v_init'
    init_view_path.mkdir()
    init_view_file_content = b'init file abc'
    (init_view_path / 'index.html').write_bytes(
        init_view_file_content)
    init_view_conf = {'name': 'v_init',
                      'roles': [],
                      'paths': [{'path': str(init_view_path)}]}
    view_manager = ViewManager([view_conf, init_view_conf])

    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = common.User(name=username,
                       roles=roles,
                       view=view_conf['name'])

    def on_create_local_session(name, password):
        session = UserSession(user=user,
                              session_id=session_id,
                              timestamp=12345)
        return session

    user_manager = UserManager(create_local_session_cb=on_create_local_session)
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view='v_init',
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    # before user login
    async with client_http.get('index.html') as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == init_view_file_content

    user_login = {'name': username,
                  'password': 'abcxyz'}
    async with client_http.post('/login/local',
                                data=json.encode(user_login)) as resp:
        assert resp.status == 200

    async with client_http.get('index.html',
                               cookies={'SESSION_ID': session_id}) as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == view_file_content

    # initial view on invalid session_id
    async with client_http.get('index.html',
                               cookies={'SESSION_ID': 'invalid_id'}) as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == init_view_file_content

    # initial view on empty session_id
    async with client_http.get('index.html') as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == init_view_file_content

    # get file that does not exist
    async with client_http.get('non_existing_file.html') as resp:
        assert resp.status == 404

    await server.async_close()
    await eventer_client.async_close()


@pytest.mark.parametrize('success', [True, False])
async def test_login_oidc(port, client_http, success):
    oidc_url = 'oidc_url'
    oidc_name = 'oidc_xyz'
    oidc_queue = aio.Queue()

    def on_get_oidc_url(name, state):
        oidc_queue.put_nowait((name, state))

        if success:
            return oidc_url

        raise Exception()

    user_manager = UserManager(get_oidc_url_cb=on_get_oidc_url)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    async with client_http.get(f'/login/oidc/{oidc_name}',
                               allow_redirects=False) as resp:
        if success:
            assert resp.status == 302
            assert oidc_url == resp.headers.get('Location')
            oidc_state_cookie = resp.cookies.get('OIDC_STATE')
            assert oidc_state_cookie.value
            assert oidc_state_cookie['httponly']

        else:
            resp.status == 400

    name, state = await oidc_queue.get()
    assert name == oidc_name
    if success:
        assert oidc_state_cookie.value == state

    await server.async_close()
    await eventer_client.async_close()


@pytest.mark.parametrize('success', [True, False])
async def test_login_oidc_cb(port, client_http, success):
    code_req = 'code xyz'
    state_cookie = 'state xyz'
    oidc_name = 'oidc_xyz'
    username = 'u1'
    session_id = 'abcxyz'
    timestamp = 12345
    user = common.User(name=username,
                       roles=['r1', 'r2'],
                       view='v_u1')
    oidc_queue = aio.Queue()

    def on_create_oidc_session(name, code):
        oidc_queue.put_nowait((name, code))

        if success:
            return UserSession(user=user,
                               session_id=session_id,
                               timestamp=timestamp)

        raise Exception()

    user_manager = UserManager(create_oidc_session_cb=on_create_oidc_session)
    view_manager = ViewManager([])
    adapter_manager = AdapterManager()
    eventer_client = EventerClient()

    server = await hat.gui.server.server.create_server(
        host='127.0.0.1',
        port=port,
        name='name',
        initial_view=None,
        view_manager=view_manager,
        user_manager=user_manager,
        adapter_manager=adapter_manager,
        eventer_client=eventer_client,
        autoflush_delay=0)

    async with client_http.get(f'/login/oidc/{oidc_name}/cb',
                               params={"code": code_req,
                                       "state": state_cookie},
                               cookies={'OIDC_STATE': state_cookie},
                               allow_redirects=False) as resp:
        if success:
            assert resp.status == 302
            assert '/index.html' == resp.headers.get('Location')
            session_cookie = resp.cookies.get('SESSION_ID')
            assert session_id == session_cookie.value
            assert session_cookie['httponly']
            assert int(session_cookie.get('max-age')) == (60 * 60 * 24 * 365)

        else:
            resp.status == 400

    name, code_res = await oidc_queue.get()
    assert name == oidc_name
    assert code_res == code_req

    # invalid request - state param invalid
    async with client_http.get(f'/login/oidc/{oidc_name}/cb',
                               params={"code": code_req,
                                       "state": 'invalid_state'},
                               cookies={'OIDC_STATE': state_cookie},
                               allow_redirects=False) as resp:
        assert resp.status == 400

    # invalid request - state param missing
    async with client_http.get(f'/login/oidc/{oidc_name}/cb',
                               params={"code": code_req},
                               cookies={'OIDC_STATE': state_cookie},
                               allow_redirects=False) as resp:
        assert resp.status == 400

    # invalid request - code param missing
    async with client_http.get(f'/login/oidc/{oidc_name}/cb',
                               params={"state": 'invalid_state'},
                               cookies={'OIDC_STATE': state_cookie},
                               allow_redirects=False) as resp:
        assert resp.status == 400

    await server.async_close()
    await eventer_client.async_close()
