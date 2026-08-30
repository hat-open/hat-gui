from collections.abc import Iterable
from pathlib import Path
import asyncio
import base64
import collections
import hashlib
import logging
import os
import secrets
import time
import typing
import urllib.parse

import aiohttp

from hat import aio
from hat import json

from hat.gui import common
from hat.gui.server.view import ViewManager


mlog: logging.Logger = logging.getLogger(__name__)


UserSessionId: typing.TypeAlias = str


class UserSession(aio.Resource):

    def __init__(self,
                 user: common.User,
                 session_id: UserSessionId,
                 timestamp: float):
        self.__user = user
        self.__session_id = session_id
        self.__timestamp = timestamp
        self.__active_counter = 0

    @property
    def user(self) -> common.User:
        return self.__user

    @property
    def session_id(self) -> UserSessionId:
        return self.__session_id

    @property
    def timestamp(self) -> float:
        return time.time() if self.active else self.__timestamp

    @property
    def active(self) -> bool:
        return self.__active_counter > 0

    def refresh(self):
        self.__timestamp = time.time()

    def acquire(self):
        self.__active_counter += 1

    def release(self):
        self.__active_counter -= 1


async def create_manager(users_conf: json.Data,
                         view_manager: ViewManager
                         ) -> 'UserManager':
    manager = UserManager()
    manager._users_conf = users_conf
    manager._view_manager = view_manager
    manager._local_user_confs = {
        i['name']: i for i in users_conf['local']['users']
    } if 'local' in users_conf else {}
    manager._oidc_user_confs = {
        i['name']: i for i in users_conf['oidc']
    } if 'oidc' in users_conf else {}
    manager._sessions = {}
    manager._snapshot_path = Path(users_conf['snapshot_path'])
    manager._executor = aio.Executor(log_exceptions=False)
    manager._async_group = aio.Group()

    try:
        initialized_event = asyncio.Event()
        manager.async_group.spawn(manager._run_loop, initialized_event)

        if manager._snapshot_path.exists():
            data = await manager._executor.spawn(json.decode_file,
                                                 manager._snapshot_path)

            for session in _decode_sessions(users_conf=users_conf,
                                            view_manager=view_manager,
                                            data=data):
                await manager._add_session(session)

        initialized_event.set()

    except BaseException:
        await aio.uncancellable(manager.async_close())
        raise

    return manager


class UserManager(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    def get_session(self,
                    session_id: UserSessionId
                    ) -> UserSession | None:
        session = self._sessions.get(session_id)
        if session and not session.is_open:
            return

        return session

    def get_oidc_url(self, name: str, state: str) -> str:
        oidc_conf = self._oidc_user_confs.get(name)
        if not oidc_conf:
            raise Exception("invalid name")

        url = urllib.parse.urlsplit(oidc_conf['authorize_url'])

        query = urllib.parse.parse_qs(url.query)
        query['response_type'] = 'code'
        query['client_id'] = oidc_conf['client_id']
        query['redirect_uri'] = _get_oidc_redirect_url(oidc_conf)
        query['scope'] = ' '.join(['openid', *oidc_conf['scope']])
        query['state'] = state

        return url._replace(query=urllib.parse.urlencode(query)).geturl()

    async def create_local_session(self,
                                   name: str,
                                   password: str
                                   ) -> UserSession:
        user_conf = self._local_user_confs.get(name)
        if not user_conf:
            raise Exception("invalid name")

        password_hash = hashlib.sha256(password.encode('utf-8')).digest()

        password_conf = user_conf['password']
        conf_salt = bytes.fromhex(password_conf['salt'])
        conf_hash = bytes.fromhex(password_conf['hash'])

        h = hashlib.sha256()
        h.update(conf_salt)
        h.update(password_hash)

        if h.digest() != conf_hash:
            raise Exception("invalid password")

        roles = set(user_conf['roles'])
        view = self._view_manager.get_view(roles)

        user = common.User(name=name,
                           roles=roles,
                           view=view)

        session = _LocalUserSession(user=user,
                                    session_id=self._generate_session_id(),
                                    timestamp=time.time())

        await self._add_session(session)

        return session

    async def create_oidc_session(self,
                                  name: str,
                                  code: str
                                  ) -> UserSession:
        oidc_conf = self._oidc_user_confs.get(name)
        if not oidc_conf:
            raise Exception("invalid name")

        auth = aiohttp.BasicAuth(oidc_conf['auth']['login'],
                                 oidc_conf['auth'].get('password', ''))

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}

        query = urllib.parse.urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': _get_oidc_redirect_url(oidc_conf)})

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.post(
                    oidc_conf['token_url'],
                    headers=headers,
                    data=query.encode('utf-8')) as res:
                if res.status != 200:
                    raise Exception('request token error')

                data = await res.json()

        claims = json.decode(
            _base64url_decode(data['id_token'].split('.')[1]).decode('utf-8'))

        name = claims[oidc_conf['claims']['name']]
        if not isinstance(name, str):
            raise TypeError('invalid name type')

        roles = set()
        for i in claims[oidc_conf['claims']['roles']]:
            role = oidc_conf['roles'].get(i)
            if role:
                roles.add(role)

        view = self._view_manager.get_view(roles)

        user = common.User(name=name,
                           roles=roles,
                           view=view)

        session = _OidcUserSession(user=user,
                                   session_id=self._generate_session_id(),
                                   timestamp=time.time())

        await self._add_session(session)

        return session

    async def _run_loop(self, initialized_event):
        tmp_snapshot_path = self._snapshot_path.with_suffix(
            self._snapshot_path.suffix + '.tmp')

        async def cleanup():
            self.close()

            if initialized_event.is_set():
                await create_snapshot()

            for session in self._sessions.values():
                session.close()

            await self._executor.async_close()

            for session in list(self._sessions.values()):
                await session.async_close()

        async def create_snapshot():
            try:
                data = _encode_sessions(session
                                        for session in self._sessions.values()
                                        if session.is_open)
                await self._executor.spawn(
                    json.encode_file, data, tmp_snapshot_path,
                    json.Format(self._snapshot_path.suffix.lstrip('.')))
                await self._executor.spawn(
                    os.replace, tmp_snapshot_path, self._snapshot_path)

            except Exception as e:
                mlog.error("error creating snapshot: %s", e, exc_info=e)

        try:
            await initialized_event.wait()

            while True:
                await asyncio.sleep(self._users_conf['snapshot_delay'])
                await create_snapshot()

        finally:
            await aio.uncancellable(cleanup())

    async def _add_session(self, session):
        try:
            while len(self._sessions) >= self._users_conf['max_sessions']:
                old_session = None

                for i in self._sessions.values():
                    if not i.is_open:
                        old_session = i
                        break

                    if i.active:
                        continue

                    if (old_session is None or
                            old_session.timestamp > i.timestamp):
                        old_session = i

                if old_session is None:
                    raise Exception('max sessions exceeded')

                await self._remove_session(old_session)

            if session.session_id in self._sessions:
                raise Exception('duplicate session id')

            self._sessions[session.session_id] = session

            self.async_group.spawn(aio.call_on_done, session.wait_closing(),
                                   self._remove_session, session)

        except BaseException:
            await aio.uncancellable(self._remove_session(session))
            raise

    async def _remove_session(self, session):
        await session.async_close()

        if self._sessions.get(session.session_id) is not session:
            return

        self._sessions.pop(session.session_id)

    def _generate_session_id(self):
        while True:
            session_id = secrets.token_urlsafe(32)
            if session_id in self._sessions:
                continue

            return session_id


class _LocalUserSession(UserSession):

    def __init__(self,
                 user: common.User,
                 session_id: UserSessionId,
                 timestamp: float):
        super().__init__(user=user,
                         session_id=session_id,
                         timestamp=timestamp)

        self._async_group = aio.Group()

    @property
    def async_group(self) -> aio.Group:
        return self._async_group


class _OidcUserSession(UserSession):

    def __init__(self,
                 user: common.User,
                 session_id: UserSessionId,
                 timestamp: float):
        super().__init__(user=user,
                         session_id=session_id,
                         timestamp=timestamp)

        self._async_group = aio.Group()

    @property
    def async_group(self) -> aio.Group:
        return self._async_group


def _encode_sessions(sessions: Iterable[UserSession]
                     ) -> json.Data:
    local_sessions = collections.deque()
    oidc_sessions = collections.deque()

    for session in sessions:
        if isinstance(session, _LocalUserSession):
            local_sessions.append(_encode_local_session(session))

        elif isinstance(session, _OidcUserSession):
            oidc_sessions.append(_encode_oidc_session(session))

        else:
            raise TypeError('invalid session type')

    return {'local': list(local_sessions),
            'oidc': list(oidc_sessions)}


def _decode_sessions(users_conf: json.Data,
                     view_manager: ViewManager,
                     data: json.Data
                     ) -> Iterable[UserSession]:
    local_user_confs = {
        local_user_conf['name']: local_user_conf
        for local_user_conf in users_conf['local']['users']
    } if 'local' in users_conf else {}
    for i in data['local']:
        try:
            yield _decode_local_session(local_user_confs=local_user_confs,
                                        view_manager=view_manager,
                                        data=i)

        except Exception as e:
            mlog.warning("error decoding local session: %s", e, exc_info=e)

    oidc_confs = {
        oidc_conf['name']: oidc_conf
        for oidc_conf in users_conf['oidc']
    } if 'oidc' in users_conf else {}
    for i in data['oidc']:
        try:
            yield _decode_oidc_session(oidc_confs=oidc_confs,
                                       view_manager=view_manager,
                                       data=i)

        except Exception as e:
            mlog.warning("error decoding oidc session: %s", e, exc_info=e)


def _encode_local_session(session: _LocalUserSession) -> json.Data:
    return {'name': session.user.name,
            'session_id': session.session_id,
            'timestamp': session.timestamp}


def _decode_local_session(local_user_confs: dict[str, json.Data],
                          view_manager: ViewManager,
                          data: json.Data
                          ) -> _LocalUserSession:
    name = data['name']

    local_user_conf = local_user_confs.get(name)
    if not local_user_conf:
        raise Exception('user not available')

    roles = set(local_user_conf['roles'])
    view = view_manager.get_view(roles)

    user = common.User(name=name,
                       roles=roles,
                       view=view)

    return _LocalUserSession(user=user,
                             session_id=data['session_id'],
                             timestamp=data['timestamp'])


def _encode_oidc_session(session: _OidcUserSession) -> json.Data:
    return {'user': {'name': session.user.name,
                     'roles': list(session.user.roles)},
            'session_id': session.session_id,
            'timestamp': session.timestamp}


def _decode_oidc_session(oidc_confs: dict[str, json.Data],
                         view_manager: ViewManager,
                         data: json.Data
                         ) -> _OidcUserSession:
    name = data['user']['name']
    roles = set(data['user']['roles'])
    view = view_manager.get_view(roles)

    user = common.User(name=name,
                       roles=roles,
                       view=view)

    return _OidcUserSession(user=user,
                            session_id=data['session_id'],
                            timestamp=data['timestamp'])


def _base64url_decode(data: str) -> bytes:
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_oidc_redirect_url(oidc_conf):
    return urllib.parse.urlsplit(
        oidc_conf['local_url'])._replace(
            path=f"/login/oidc/{oidc_conf['name']}/cb",
            query='',
            fragment='').geturl()
