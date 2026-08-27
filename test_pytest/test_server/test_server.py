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
        session = AdapterSession(user, state, notify_cb,
                                 self._request_cb)

        if self._session_cb:
            await aio.call(self._session_cb, session)

        return session


class UserManager:

    def __init__(self, create_local_session_cb=None):
        self._create_local_session_cb = create_local_session_cb
        self._sessions = {}

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    def get_oidc_url(self, name, state):
        raise NotImplementedError()

    async def create_local_session(self, name, password):
        if not self._create_local_session_cb:
            raise NotImplementedError()

        session = self._create_local_session_cb(name, password)
        self._sessions[session.session_id] = session
        return session

    async def create_oidc_session(self, name, code):
        raise NotImplementedError()


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
    user = user = common.User(name=username,
                              roles=['r1', 'r2'],
                              view='v_u1')

    def on_create_local_session(name, password):
        assert name == request_username
        assert password == request_passwd

        if success:
            return hat.gui.server.user.UserSession(user=user,
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
            assert resp.cookies.get('SESSION_ID').value == session_id
            # assert int(resp.cookies.get('SESSION_ID').get('max-age')) == (
            #     60 * 60 * 24 * 365)

        else:
            resp.status == 400

    await server.async_close()
    await eventer_client.async_close()


@pytest.mark.parametrize('logout_method', ['get', 'post'])
async def test_logout(port, client_http, logout_method):
    user_session_queue = aio.Queue()
    username = 'u1'
    session_id = 'abcxyz'
    user = user = common.User(name=username,
                              roles=['r1', 'r2'],
                              view='v_u1')

    def on_create_local_session(name, password):
        session = hat.gui.server.user.UserSession(user=user,
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
        assert resp.status == {'get': 302,
                               'post': 200}[logout_method]

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
    user = user = common.User(name=username,
                              roles=roles,
                              view='v_u1')

    def on_create_local_session(name, password):
        session = hat.gui.server.user.UserSession(user=user,
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
    user = user = common.User(name=username,
                              roles=roles,
                              view='v_u1')

    def on_create_local_session(name, password):
        session = hat.gui.server.user.UserSession(user=user,
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


async def test_get(port, client_http, tmp_path):
    view_path = tmp_path / 'v1'
    view_path.mkdir()
    file_path = view_path / 'view_file.html'
    file_content = b'some random bytes'
    file_path.write_bytes(file_content)
    view_conf = {'name': 'v1',
                 'roles': ['r1', 'r2'],
                 'view_path': str(view_path)}
    view_manager = ViewManager([view_conf])

    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = user = common.User(name=username,
                              roles=roles,
                              view=view_conf['name'])

    def on_create_local_session(name, password):
        session = hat.gui.server.user.UserSession(user=user,
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

    # get with wrong session_id (no initial view)
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
    view_file_content = b'some random bytes'
    (view_path / 'index.html').write_bytes(view_file_content)
    view_conf = {'name': 'v1',
                 'roles': ['r1', 'r2'],
                 'view_path': str(view_path)}

    init_view_path = tmp_path / 'v_init'
    init_view_path.mkdir()
    init_view_file_content = b'some random bytes'
    (init_view_path / 'index.html').write_bytes(
        init_view_file_content)
    init_view_conf = {'name': 'v_init',
                      'roles': [],
                      'view_path': str(init_view_path)}
    view_manager = ViewManager([view_conf, init_view_conf])

    username = 'u1'
    session_id = 'abcxyz'
    roles = ['r1', 'r2']
    user = user = common.User(name=username,
                              roles=roles,
                              view=view_conf['name'])

    def on_create_local_session(name, password):
        session = hat.gui.server.user.UserSession(user=user,
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

    # get with wrong session_id (no initial view)
    async with client_http.get('index.html') as resp:
        assert resp.status == 200
        resp_content = await resp.read()
        assert resp_content == init_view_file_content

    # get file that does not exist
    async with client_http.get('non_existing_file.html') as resp:
        assert resp.status == 404

    await server.async_close()
    await eventer_client.async_close()
