from collections.abc import Collection, Iterable
from pathlib import Path
import asyncio
import base64
import contextlib
import hashlib
import secrets
import urllib.parse

import aiohttp.web
import pytest

from hat import aio
from hat import json
from hat import util
import hat.event.common

import hat.gui.server.user


class ViewManager(aio.Resource):

    def __init__(self,  view_confs: Iterable[json.Data]):
        self._view_roles = {}
        self._async_group = aio.Group()

        for view_conf in view_confs:
            self._view_roles[view_conf['name']] = set(view_conf['roles'])

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    def get_views(self, roles: set[str]) -> set[str]:
        return {name
                for name, view_roles in self._view_roles.items()
                if not view_roles.isdisjoint(roles)}

    def get_view_paths(self, name: str) -> Path:
        raise NotImplementedError()


class EventerClient(aio.Resource):

    def __init__(self, query_cb=None, register_cb=None):
        self._async_group = aio.Group()
        self._query_cb = query_cb
        self._register_cb = register_cb

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    @property
    def status(self) -> hat.event.common.Status:
        return hat.event.common.Status.OPERATIONAL

    async def register(self,
                       events: Collection[hat.event.common.RegisterEvent],
                       with_response: bool = False
                       ) -> Collection[hat.event.common.Event] | None:
        if with_response:
            raise NotImplementedError()
        if not self._register_cb:
            return
        self._register_cb(events)

    async def query(self,
                    params: hat.event.common.common.QueryParams
                    ) -> hat.event.common.QueryResult:
        if not self._query_cb:
            return hat.event.common.QueryResult(events=[], more_follows=False)
        return self._query_cb(params)


def password_hashed(password):
    password_hashed = hashlib.sha256(password.encode('utf-8')).digest()
    salt = secrets.token_bytes(32)
    m = hashlib.sha256(salt)
    m.update(password_hashed)
    return {'hash': m.hexdigest(),
            'salt': salt.hex()}


def id_token(claims):
    payload = base64.urlsafe_b64encode(
        json.encode(claims).encode('utf-8')).rstrip(b'=').decode('utf-8')

    return f'header.{payload}.signature'


@pytest.fixture
def local_users_conf():

    def create(name, password, max_sessions=10, session_duration=None):
        conf = {
            'max_sessions': max_sessions,
            'local': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}

        if session_duration:
            conf['session_duration'] = session_duration

        return conf

    return create


@pytest.fixture
def oidc_users_conf(port):

    def create(name='name'):
        return {
            'max_sessions': 10,
            'oidc': [{
                'name': name,
                'local_url': f'http://localhost:{port}',
                'authorize_url': 'https://oidc.example/authorize',
                'token_url': f'http://127.0.0.1:{port}/token',
                'client_id': 'hat-gui',
                'client_secret': 'secret',
                'scope': [
                    'profile',
                    'email'
                ],
                'claims': {
                    'name': 'name',
                    'roles': 'groups'},
                'roles': {
                    'administrator': 'admin'}}]}

    return create


@pytest.fixture
def port():
    return util.get_unused_tcp_port()


@pytest.fixture
async def aiohttp_server_factory():

    @contextlib.asynccontextmanager
    async def aiohttp_server(port, handler):

        app = aiohttp.web.Application()
        app.router.add_post('/token', handler)

        runner = aiohttp.web.AppRunner(app)
        await runner.setup()

        site = aiohttp.web.TCPSite(runner, host='localhost', port=port)

        await site.start()

        try:
            yield

        finally:
            await site.stop()
            await runner.cleanup()

    return aiohttp_server


async def test_empty_user_manager():
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    users_conf = {'max_sessions': 10}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager,
        eventer_client=eventer_client)

    assert user_manager.is_open

    await user_manager.async_close()

    assert user_manager.is_closed

    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_local_session(local_users_conf):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None
    assert session.session_id
    assert session.created
    assert session.updated

    user = session.user
    assert user
    assert user.name == name
    assert user.roles == {'admin'}
    assert user.views == {'view'}

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_local_session_no_view(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None
    assert session.session_id
    assert session.created
    assert session.updated

    user = session.user
    assert user
    assert user.name == name
    assert user.roles == {'admin'}
    assert user.views == set()

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_local_session_invalid_name(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    with pytest.raises(Exception):
        await user_manager.create_local_session(name='nonexistent',
                                                password=password)

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_local_session_invalid_password(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    with pytest.raises(Exception):
        await user_manager.create_local_session(name=name,
                                                password='invalid')

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_oidc_url(oidc_users_conf, port):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    oidc_name = 'test'
    user_manager = await hat.gui.server.user.create_manager(
        users_conf=oidc_users_conf(name=oidc_name),
        view_manager=view_manager,
        eventer_client=eventer_client)

    url = user_manager.get_oidc_url(name=oidc_name,
                                    state='test-state')

    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == 'https'
    assert parsed.netloc == 'oidc.example'
    assert parsed.path == '/authorize'

    assert query['response_type'] == ['code']
    assert query['client_id'] == ['hat-gui']
    assert query['redirect_uri'] == [
        f'http://localhost:{port}/login/oidc/test/cb']
    assert query['scope'] == ['openid profile email']
    assert query['state'] == ['test-state']

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_oidc_url_invalid_name(oidc_users_conf, port):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=oidc_users_conf(),
        view_manager=view_manager,
        eventer_client=eventer_client)

    with pytest.raises(Exception):
        user_manager.get_oidc_url(name='nonexistent',
                                  state='test-state')

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_oidc_session(oidc_users_conf, aiohttp_server_factory,
                                   port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)
    eventer_client = EventerClient()

    username = 'name'
    token = id_token({'name': username,
                      'groups': ['administrator']})
    access_token = 'test-access-token'
    refresh_token = 'test-refresh-token'

    received = {}

    async def token_handler(request):
        received['authorization'] = request.headers['Authorization']
        received['content_type'] = request.headers['Content-Type']
        received['data'] = await request.text()

        return aiohttp.web.json_response({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        oidc_name = 'test'
        user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(name=oidc_name),
            view_manager=view_manager,
            eventer_client=eventer_client)

        session = await user_manager.create_oidc_session(
            name=oidc_name, code='authorization-code')

        assert session.user.name == username
        assert session.user.roles == {'admin'}
        assert session.user.views == {'view'}

        assert session.session_id
        assert session.created
        assert session.updated
        assert session.name == oidc_name
        assert session.access_token == access_token
        assert session.refresh_token == refresh_token

        assert user_manager.get_session(session.session_id) is session

        assert received['content_type'] == 'application/x-www-form-urlencoded'
        assert received['authorization'] == (
            'Basic ' + base64.b64encode(b'hat-gui:secret').decode('utf-8'))

        data = urllib.parse.parse_qs(received['data'])

        assert data['grant_type'] == ['authorization_code']
        assert data['code'] == ['authorization-code']
        assert data['redirect_uri'] == [
            f'http://localhost:{port}/login/oidc/test/cb']

        await user_manager.async_close()
        await view_manager.async_close()
        await eventer_client.async_close()


async def test_create_oidc_session_token_error(oidc_users_conf,
                                               aiohttp_server_factory,
                                               port):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    async def token_handler(request):
        return aiohttp.web.Response(status=400)

    async with aiohttp_server_factory(port=port, handler=token_handler):

        oidc_name = 'test'
        user_manager = await hat.gui.server.user.create_manager(
           users_conf=oidc_users_conf(name=oidc_name),
           view_manager=view_manager,
           eventer_client=eventer_client)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name=oidc_name, code='authorization-code')

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_oidc_session_invalid_oidc_name(oidc_users_conf,
                                                     aiohttp_server_factory,
                                                     port):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    token = id_token({'name': 'name',
                      'groups': ['administrator']})

    async def token_handler(request):
        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(),
            view_manager=view_manager,
            eventer_client=eventer_client)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name='nonexistent', code='authorization-code')

        await user_manager.async_close()
        await view_manager.async_close()
        await eventer_client.async_close()


async def test_create_oidc_session_invalid_claims_name(oidc_users_conf,
                                                       aiohttp_server_factory,
                                                       port):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    invalid_name = 1234
    token = id_token({'name': invalid_name,
                      'groups': ['administrator']})

    async def token_handler(request):
        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        oidc_name = 'test'
        user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(name=oidc_name),
            view_manager=view_manager,
            eventer_client=eventer_client)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name=oidc_name, code='authorization-code')

        await user_manager.async_close()
        await view_manager.async_close()
        await eventer_client.async_close()


async def test_create_oidc_session_invalid_claims_roles(oidc_users_conf,
                                                        aiohttp_server_factory,
                                                        port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)
    eventer_client = EventerClient()

    token = id_token({'name': 'name',
                      'grs': ['administrator']})

    async def token_handler(request):
        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        oidc_name = 'test'
        user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(name=oidc_name),
            view_manager=view_manager,
            eventer_client=eventer_client)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name=oidc_name, code='authorization-code')

        await user_manager.async_close()
        await view_manager.async_close()
        await eventer_client.async_close()


async def test_get_session(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None

    retrieved_session = user_manager.get_session(session.session_id)

    assert retrieved_session == session

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_session_invalid(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    retrieved_session = user_manager.get_session('nonexistent')

    assert not retrieved_session

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_session_closed(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None
    await session.async_close()

    retrieved_session = user_manager.get_session(session.session_id)

    assert not retrieved_session

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_max_sessions(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    max_sessions = 5
    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password,
                                    max_sessions=max_sessions),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session_ids = []
    for i in range(max_sessions + 1):
        session = await user_manager.create_local_session(name=name,
                                                          password=password)
        session_ids.append(session.session_id)

    for i in session_ids[1:]:
        assert user_manager.get_session(i)

    # oldest one dropped
    assert user_manager.get_session(session_ids[0]) is None

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_max_sessions_closed(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    max_sessions = 2
    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password,
                                    max_sessions=max_sessions),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    session_id_open = session.session_id

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    session_id_closed = session.session_id

    await session.async_close()

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    session_id_new = session.session_id

    # closed one dropped
    assert user_manager.get_session(session_id_open)
    assert not user_manager.get_session(session_id_closed)
    assert user_manager.get_session(session_id_new)

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_session_duration(local_users_conf):
    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient()

    session_duration = 0.1
    name = 'name'
    password = 'pass'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name=name, password=password,
                                    session_duration=session_duration),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)

    assert user_manager.get_session(session.session_id)

    await asyncio.sleep(0.2)

    assert not user_manager.get_session(session.session_id)

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_initial_query():

    def on_query(params):
        assert isinstance(params, hat.event.common.QueryLatestParams)
        assert len(params.event_types) == 1
        assert params.event_types[0] == ('gui', 'sessions')
        return hat.event.common.QueryResult(events=[], more_follows=False)

    view_manager = ViewManager(view_confs=[])
    eventer_client = EventerClient(query_cb=on_query)

    users_conf = {'max_sessions': 10}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager,
        eventer_client=eventer_client)

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_session_event_local(local_users_conf, monkeypatch):
    register_queue = aio.Queue()

    view_manager = ViewManager([])
    eventer_client = EventerClient(register_cb=register_queue.put_nowait)

    name = 'name'
    password = 'password'

    asyncio_sleep = asyncio.sleep

    async def sleep_less(delay):
        await asyncio_sleep(0.01)

    monkeypatch.setattr(asyncio, 'sleep', sleep_less)

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)

    events = await register_queue.get()
    assert len(events) == 1
    sessions_event = events[0]
    assert sessions_event.type == ('gui', 'sessions')
    assert sessions_event.source_timestamp is None
    assert len(sessions_event.payload.data) == 1
    assert sessions_event.payload.data.get(session.session_id)
    session_data = sessions_event.payload.data[session.session_id]
    assert session_data == {
        'type': 'local',
        'data': {
            'name': name,
            'session_id': session.session_id,
            'created': session.created,
            'updated': session.updated}}

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_create_session_event_oidc(oidc_users_conf,
                                         aiohttp_server_factory, port,
                                         monkeypatch):
    register_queue = aio.Queue()

    view_manager = ViewManager([])
    eventer_client = EventerClient(register_cb=register_queue.put_nowait)

    asyncio_sleep = asyncio.sleep

    async def sleep_less(delay):
        await asyncio_sleep(0.01)

    monkeypatch.setattr(asyncio, 'sleep', sleep_less)

    username = 'name'
    token = id_token({'name': username,
                      'groups': ['administrator']})

    access_token = 'test-access-token'

    async def token_handler(request):
        return aiohttp.web.json_response({
            'access_token': access_token,
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        oidc_name = 'test'
        user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(name=oidc_name),
            view_manager=view_manager,
            eventer_client=eventer_client)

        session = await user_manager.create_oidc_session(
            name=oidc_name, code='authorization-code')

    events = await register_queue.get()
    assert len(events) == 1
    sessions_event = events[0]
    assert sessions_event.type == ('gui', 'sessions')
    assert sessions_event.source_timestamp is None
    assert len(sessions_event.payload.data) == 1
    assert sessions_event.payload.data.get(session.session_id)
    session_data = sessions_event.payload.data[session.session_id]
    assert session_data == {
        'type': 'oidc',
        'data': {
            'name': oidc_name,
            'session_id': session.session_id,
            'user': {
                'name': session.user.name,
                'roles': list(session.user.roles)},
            'created': session.created,
            'updated': session.updated,
            'access_token': session.access_token,
            'refresh_token': session.refresh_token}}

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_session_from_event_local(local_users_conf):
    name = 'name'
    session_id = 'xyz123'
    created = 12345
    updated = 54321

    def on_query(params):
        return hat.event.common.QueryResult(
            events=[hat.event.common.Event(
                        id=hat.event.common.EventId(1, 1, 1),
                        type=('gui', 'sessions'),
                        timestamp=hat.event.common.now(),
                        source_timestamp=None,
                        payload=hat.event.common.EventPayloadJson({
                            'xyz123': {
                                'type': 'local',
                                'data': {
                                    'name': name,
                                    'session_id': session_id,
                                    'created': created,
                                    'updated': updated}}}))],
            more_follows=False)

    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)
    eventer_client = EventerClient(query_cb=on_query)

    name = 'name'
    password = 'password'

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=local_users_conf(name, password),
        view_manager=view_manager,
        eventer_client=eventer_client)

    session = user_manager.get_session(session_id)
    assert session
    assert session.user
    assert session.user.name == name
    assert session.user.roles == {'admin'}
    assert session.user.views == {'view'}

    assert session.session_id == session_id
    assert session.created == created
    assert session.updated == updated

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()


async def test_get_session_from_event_oidc(oidc_users_conf):
    oidc_name = 'test'
    username = 'name'
    session_id = 'xyz123'
    created = 12345
    updated = 54321
    access_token = 'abc123'
    refresh_token = 'cba123'

    def on_query(params):
        return hat.event.common.QueryResult(
            events=[hat.event.common.Event(
                        id=hat.event.common.EventId(1, 1, 1),
                        type=('gui', 'sessions'),
                        timestamp=hat.event.common.now(),
                        source_timestamp=None,
                        payload=hat.event.common.EventPayloadJson({
                            'xyz123': {
                                'type': 'oidc',
                                'data': {
                                    'name': oidc_name,
                                    'session_id': session_id,
                                    'user': {
                                        'name': username,
                                        'roles': ['admin']},
                                    'created': created,
                                    'updated': updated,
                                    'access_token': access_token,
                                    'refresh_token': refresh_token}}}))],
            more_follows=False)

    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)
    eventer_client = EventerClient(query_cb=on_query)

    user_manager = await hat.gui.server.user.create_manager(
            users_conf=oidc_users_conf(name=oidc_name),
            view_manager=view_manager,
            eventer_client=eventer_client)

    session = user_manager.get_session(session_id)
    assert session
    assert session.user
    assert session.user.name == username
    assert session.user.roles == {'admin'}
    assert session.user.views == {'view'}

    assert session.session_id == session_id
    assert session.created == created
    assert session.updated == updated
    assert session.access_token == access_token
    assert session.refresh_token == refresh_token

    await user_manager.async_close()
    await view_manager.async_close()
    await eventer_client.async_close()
