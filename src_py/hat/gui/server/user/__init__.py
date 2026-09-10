from pathlib import Path
import asyncio
import collections
import logging
import secrets
import time

from hat import aio
from hat import json

from hat.gui.server.view import ViewManager

from hat.gui.server.user.common import UserSessionId, UserSession
from hat.gui.server.user.local import LocalUserManager
from hat.gui.server.user.oidc import OidcUserManager
from hat.gui.server.user.store import create_store


__all__ = ['UserSessionId',
           'UserSession',
           'create_manager',
           'UserManager']


mlog: logging.Logger = logging.getLogger(__name__)


async def create_manager(users_conf: json.Data,
                         view_manager: ViewManager
                         ) -> 'UserManager':
    manager = UserManager()
    manager._users_conf = users_conf
    manager._view_manager = view_manager
    manager._sessions = {}
    manager._async_group = aio.Group()

    try:
        session_ids = manager._generate_session_ids()

        manager._local_manager = LocalUserManager(
            async_group=manager.async_group.create_subgroup(),
            local_confs=users_conf.get('local', []),
            view_manager=view_manager,
            session_ids=session_ids,
            session_update_cb=manager._on_session_update)

        manager._oidc_manager = OidcUserManager(
            async_group=manager.async_group.create_subgroup(),
            oidc_confs=users_conf.get('oidc', []),
            view_manager=view_manager,
            session_ids=session_ids,
            session_update_cb=manager._on_session_update)

        snapshot_path = users_conf.get('snapshot_path')
        if snapshot_path:
            manager._store = await create_store(
                async_group=manager.async_group.create_subgroup(),
                path=Path(snapshot_path),
                local_manager=manager._local_manager,
                oidc_manager=manager._oidc_manager)

            for session in collections.deque(manager._store.create_sessions()):
                manager._add_session(session)

        else:
            manager._store = None

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
        return self._oidc_manager.get_url(name=name,
                                          state=state)

    async def create_local_session(self,
                                   name: str,
                                   password: str
                                   ) -> UserSession:
        session = self._local_manager.create_session(name=name,
                                                     password=password)
        self._add_session(session)

        return session

    async def create_oidc_session(self,
                                  name: str,
                                  code: str
                                  ) -> UserSession:
        session = await self._oidc_manager.create_session(name=name,
                                                          code=code)
        self._add_session(session)

        return session

    def _on_session_update(self, session):
        if self._store and session.is_open:
            self._store.add_session(session)

    def _add_session(self, session):
        try:
            while len(self._sessions) >= self._users_conf['max_sessions']:
                old_session = None

                for i in self._sessions.values():
                    if not i.is_open:
                        old_session = i
                        break

                    if (old_session is None or
                            old_session.updated > i.updated):
                        old_session = i

                if old_session is None:
                    raise Exception('max sessions exceeded')

                self._remove_session(old_session)

            if session.session_id in self._sessions:
                raise Exception('duplicate session id')

            self._sessions[session.session_id] = session

            self.async_group.spawn(aio.call_on_done, session.wait_closing(),
                                   self._remove_session, session)

            if self._store:
                self._store.add_session(session)

            session_duration = self._users_conf.get('session_duration')
            if session_duration:
                delay = session_duration - (time.time() - session.created)

                if delay > 0:
                    session.async_group.spawn(self._delayed_remove_session,
                                              session, delay)

                else:
                    self._remove_session(session)

        except Exception:
            session.close()
            raise

    def _remove_session(self, session):
        session.close()

        if self._store and self.is_open:
            self._store.remove_session(session)

        if self._sessions.get(session.session_id) is not session:
            return

        self._sessions.pop(session.session_id)

    async def _delayed_remove_session(self, session, delay):
        await asyncio.sleep(delay)
        self._remove_session(session)

    def _generate_session_ids(self):
        while True:
            session_id = secrets.token_urlsafe(32)
            if session_id in self._sessions:
                continue

            yield session_id
