from collections.abc import Iterable
from pathlib import Path
import asyncio
import collections
import hashlib
import logging
import os
import secrets
import time
import typing

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
        self.__async_group = aio.Group()

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
    manager._local_user_confs = {i['name']: i
                                 for i in users_conf['local']['users']}
    manager._sessions = {}
    manager._snapshot_path = Path(users_conf['snapshot_path'])
    manager._executor = aio.Executor(log_exceptions=False)
    manager._async_group = aio.Group()

    try:
        initialized_event = asyncio.Event()
        manager.async_group.spawn(manager._run_loop, initialized_event)

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
                    ) -> common.UserSession | None:
        session = self._sessions.get(session_id)
        if session and not session.is_open:
            return

        return session

    def get_oidc_url(self, name: str, state: str) -> str:
        raise NotImplementedError()

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
        raise NotImplementedError()

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
                await self._executor(json.encode_file, data, tmp_snapshot_path)
                await self._executor(os.replace, tmp_snapshot_path,
                                     self._snapshot_path)

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
    local_user_confs = {local_user_conf['name']: local_user_conf
                        for local_user_conf in users_conf['local']['users']}
    for i in data['local']:
        try:
            yield _decode_local_session(local_user_confs=local_user_confs,
                                        view_manager=view_manager,
                                        data=i)

        except Exception as e:
            mlog.warning("error decoding local session: %s", e, exc_info=e)

    oidc_confs = {oidc_conf['name']: oidc_conf
                  for oidc_conf in users_conf['oidc']}
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

    roles = set(data['roles'])
    view = view_manager.get_view(roles)

    user = common.User(name=name,
                       roles=roles,
                       view=view)

    return _LocalUserSession(user=user,
                             session_id=data['session_id'],
                             timestamp=data['timestamp'])


def _encode_oidc_session(session: _OidcUserSession) -> json.Data:
    raise NotImplementedError()


def _decode_oidc_session(oidc_confs: dict[str, json.Data],
                         view_manager: ViewManager,
                         data: json.Data
                         ) -> _OidcUserSession:
    raise NotImplementedError()
