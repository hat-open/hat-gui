from collections.abc import Iterable
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

    def get_view(self, roles: set[str]) -> str | None:
        for name, view_roles in self._view_roles.items():
            if not view_roles.isdisjoint(roles):
                return name

    def get_view_path(self, name: str) -> Path | None:
        raise NotImplementedError()


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
            yield f'http://localhost:{port}'

        finally:
            await site.stop()
            await runner.cleanup()

    return aiohttp_server


async def test_empty_user_manager(tmp_path):
    view_manager = ViewManager(view_confs=[])

    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    assert user_manager.is_open

    await user_manager.async_close()

    assert user_manager.is_closed

    await view_manager.async_close()


async def test_create_local_session(tmp_path):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None
    assert session.session_id
    assert session.timestamp
    assert not session.active

    user = session.user
    assert user
    assert user.name == name
    assert user.roles == {'admin'}
    assert user.view == 'view'

    await user_manager.async_close()
    await view_manager.async_close()


async def test_create_local_session_no_view(tmp_path):
    view_manager = ViewManager(view_confs=[])

    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None
    assert session.session_id
    assert session.timestamp
    assert not session.active

    user = session.user
    assert user
    assert user.name == name
    assert user.roles == {'admin'}
    assert user.view is None

    await user_manager.async_close()
    await view_manager.async_close()


async def test_create_local_session_invalid_name(tmp_path):
    view_confs = []
    view_manager = ViewManager(view_confs)

    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    with pytest.raises(Exception):
        await user_manager.create_local_session(name='nonexistent',
                                                password=password)

    await user_manager.async_close()
    await view_manager.async_close()


async def test_create_local_session_invalid_password(tmp_path):
    view_confs = []
    view_manager = ViewManager(view_confs)

    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    with pytest.raises(Exception):
        await user_manager.create_local_session(name=name,
                                                password='invalid')

    await user_manager.async_close()
    await view_manager.async_close()


async def test_session_activity(tmp_path):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None

    session.acquire()
    assert session.active

    session.release()
    assert not session.active

    await user_manager.async_close()
    await view_manager.async_close()


async def test_get_oidc_url(tmp_path, port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'oidc': [{
            'name': 'test',
            'local_url': f'http://localhost:{port}',
            'authorize_url': 'https://oidc.example/authorize',
            'token_url': 'https://oidc.example/token',
            'client_id': 'hat-gui',
            'auth': {
                'login': 'hat-gui',
                'password': 'secret'},
            'scope': [
                'profile',
                'email'
            ],
            'claims': {
                'name': 'name',
                'roles': 'groups'},
            'roles': {
                'administrator': 'admin'}}]}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    url = user_manager.get_oidc_url(name='test',
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


async def test_create_oidc_session(tmp_path, aiohttp_server_factory, port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'oidc': [{
            'name': 'test',
            'local_url': f'http://localhost:{port}',
            'authorize_url': 'https://oidc.example/authorize',
            'token_url': f'http://localhost:{port}/token',
            'client_id': 'hat-gui',
            'auth': {
                'login': 'hat-gui',
                'password': 'secret'},
            'scope': [
                'profile',
                'email'
            ],
            'claims': {
                'name': 'name',
                'roles': 'groups'},
            'roles': {
                'administrator': 'admin'}}]}

    token = id_token({'name': 'name',
                      'groups': ['administrator']})

    received = {}

    async def token_handler(request):
        received['authorization'] = request.headers['Authorization']

        received['content_type'] = request.headers['Content-Type']

        received['data'] = await request.text()

        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        user_manager = await hat.gui.server.user.create_manager(
            users_conf=users_conf, view_manager=view_manager)

        session = await user_manager.create_oidc_session(
            name='test', code='authorization-code')

        assert session.user.name == 'name'
        assert session.user.roles == {'admin'}

        assert session.session_id
        assert session.timestamp

        assert user_manager.get_session(session.session_id) is session

        assert received['content_type'] == 'application/x-www-form-urlencoded'

        assert received['authorization'] == (
            'Basic ' + base64.b64encode(b'hat-gui:secret').decode('ascii'))

        data = urllib.parse.parse_qs(received['data'])

        assert data['grant_type'] == ['authorization_code']
        assert data['code'] == ['authorization-code']
        assert data['redirect_uri'] == [
            f'http://localhost:{port}/login/oidc/test/cb']

        await user_manager.async_close()
        await view_manager.async_close()


async def test_create_oidc_session_token_error(
        tmp_path, aiohttp_server_factory, port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'oidc': [{
            'name': 'test',
            'local_url': f'http://localhost:{port}',
            'authorize_url': 'https://oidc.example/authorize',
            'token_url': f'http://localhost:{port}/token',
            'client_id': 'hat-gui',
            'auth': {
                'login': 'hat-gui',
                'password': 'secret'},
            'scope': [
                'profile',
                'email'
            ],
            'claims': {
                'name': 'name',
                'roles': 'groups'},
            'roles': {
                'administrator': 'admin'}}]}

    async def token_handler(request):
        return aiohttp.web.Response(status=400)

    async with aiohttp_server_factory(port=port, handler=token_handler):

        user_manager = await hat.gui.server.user.create_manager(
           users_conf=users_conf, view_manager=view_manager)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name='test', code='authorization-code')

    await user_manager.async_close()
    await view_manager.async_close()


async def test_create_oidc_session_invalid_name(
        tmp_path, aiohttp_server_factory, port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'oidc': [{
            'name': 'test',
            'local_url': f'http://localhost:{port}',
            'authorize_url': 'https://oidc.example/authorize',
            'token_url': f'http://localhost:{port}/token',
            'client_id': 'hat-gui',
            'auth': {
                'login': 'hat-gui',
                'password': 'secret'},
            'scope': [
                'profile',
                'email'
            ],
            'claims': {
                'name': 'name',
                'roles': 'groups'},
            'roles': {
                'administrator': 'admin'}}]}

    token = id_token({'name': 'name',
                      'groups': ['administrator']})

    received = {}

    async def token_handler(request):
        received['authorization'] = request.headers['Authorization']

        received['content_type'] = request.headers['Content-Type']

        received['data'] = await request.text()

        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        user_manager = await hat.gui.server.user.create_manager(
            users_conf=users_conf, view_manager=view_manager)

        with pytest.raises(Exception):
            await user_manager.create_oidc_session(
                name='nonexistent', code='authorization-code')

        await user_manager.async_close()
        await view_manager.async_close()


async def test_create_snapshot(tmp_path):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    snapshot_path = tmp_path / 'snapshot.json'
    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(snapshot_path),
        'snapshot_delay': 0.1,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    await asyncio.sleep(0.2)

    assert snapshot_path.exists()

    await user_manager.async_close()
    await view_manager.async_close()


async def test_get_session(tmp_path):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    snapshot_path = tmp_path / 'snapshot.json'
    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(snapshot_path),
        'snapshot_delay': 0.1,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    session = await user_manager.create_local_session(name=name,
                                                      password=password)
    assert session is not None

    retrieved_session = user_manager.get_session(session.session_id)

    assert retrieved_session == session

    await user_manager.async_close()
    await view_manager.async_close()


async def test_max_sessions(tmp_path):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    max_sessions = 5
    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': max_sessions,
        'snapshot_path': str(tmp_path / 'snapshot.json'),
        'snapshot_delay': 10,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]}}

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    session_ids = []
    for i in range(max_sessions + 1):
        session = await user_manager.create_local_session(name=name,
                                                          password=password)
        session_ids.append(session.session_id)

    for i in session_ids[1:]:
        assert user_manager.get_session(i)

    # first one dropped
    assert user_manager.get_session(session_ids[0]) is None

    await user_manager.async_close()
    await view_manager.async_close()


async def test_get_session_snapshot(tmp_path, aiohttp_server_factory, port):
    view_confs = [{'name': 'view',
                   'roles': ['operator', 'admin']}]
    view_manager = ViewManager(view_confs)

    snapshot_path = tmp_path / 'snapshot.json'
    name = 'name'
    password = 'pass'
    users_conf = {
        'max_sessions': 10,
        'snapshot_path': str(snapshot_path),
        'snapshot_delay': 0.1,
        'local': {
            'users': [{'name': name,
                       'password': password_hashed(password),
                       'roles': ['admin']}]},
        'oidc': [{
            'name': 'test',
            'local_url': f'http://localhost:{port}',
            'authorize_url': 'https://oidc.example/authorize',
            'token_url': f'http://localhost:{port}/token',
            'client_id': 'hat-gui',
            'auth': {
                'login': 'hat-gui',
                'password': 'secret'},
            'scope': [
                'profile',
                'email'
            ],
            'claims': {
                'name': 'name',
                'roles': 'groups'},
            'roles': {
                'administrator': 'admin'}}]}

    token = id_token({'name': 'name',
                      'groups': ['administrator']})

    received = {}

    async def token_handler(request):
        received['authorization'] = request.headers['Authorization']

        received['content_type'] = request.headers['Content-Type']

        received['data'] = await request.text()

        return aiohttp.web.json_response({
            'access_token': 'test-access-token',
            'id_token': token})

    async with aiohttp_server_factory(port=port, handler=token_handler):

        user_manager = await hat.gui.server.user.create_manager(
            users_conf=users_conf, view_manager=view_manager)

        session_local = await user_manager.create_local_session(
            name=name, password=password)

        session_oidc = await user_manager.create_oidc_session(
            name='test', code='authorization-code')

    await user_manager.async_close()

    user_manager = await hat.gui.server.user.create_manager(
        users_conf=users_conf,
        view_manager=view_manager)

    retrieved_session = user_manager.get_session(session_local.session_id)
    assert retrieved_session is not None
    assert retrieved_session.session_id == session_local.session_id
    assert retrieved_session.timestamp == session_local.timestamp
    assert retrieved_session.active == session_local.active

    assert retrieved_session.user
    assert retrieved_session.user.name == session_local.user.name
    assert retrieved_session.user.roles == session_local.user.roles
    assert retrieved_session.user.view == session_local.user.view

    retrieved_session = user_manager.get_session(session_oidc.session_id)
    assert retrieved_session is not None
    assert retrieved_session.session_id == session_oidc.session_id
    assert retrieved_session.timestamp == session_oidc.timestamp
    assert retrieved_session.active == session_oidc.active

    assert retrieved_session.user
    assert retrieved_session.user.name == session_oidc.user.name
    assert retrieved_session.user.roles == session_oidc.user.roles
    assert retrieved_session.user.view == session_oidc.user.view

    await user_manager.async_close()
    await view_manager.async_close()
