from collections.abc import Iterable
from pathlib import Path
import asyncio
import logging
import os

from hat import aio
from hat import json

from hat.gui.server.user import common
from hat.gui.server.user.local import LocalUserSession, LocalUserManager
from hat.gui.server.user.oidc import OidcUserSession, OidcUserManager


mlog: logging.Logger = logging.getLogger(__name__)


async def create_store(async_group: aio.Group,
                       path: Path,
                       local_manager: LocalUserManager,
                       oidc_manager: OidcUserManager
                       ) -> 'UserSessionStore':
    store = UserSessionStore()
    store._async_group = async_group
    store._path = path
    store._local_manager = local_manager
    store._oidc_manager = oidc_manager
    store._tmp_path = store._path.with_suffix(store._path.suffix + '.tmp')
    store._change_event = aio.Event()
    store._executor = aio.Executor(log_exceptions=False)

    try:
        if path.exists():
            store._data = await store._executor.spawn(json.decode_file, path)

        else:
            store._data = {}

        store.async_group.spawn(store._write_loop)

    except BaseException:
        await aio.uncancellable(store._executor.async_close())
        raise

    return store


class UserSessionStore(aio.Resource):

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    def add_session(self, session: common.UserSession):
        self._data[session.session_id] = self._encode_session(session)
        self._change_event.set()

    def remove_session(self, session: common.UserSession):
        if self._data.pop(session.session_id, None):
            self._change_event.set()

    def create_sessions(self) -> Iterable[common.UserSession]:
        return (self._decode_session(i) for i in self._data.values())

    async def _write_loop(self):

        async def cleanup():
            self.close()
            await self._write()
            await self._executor.async_close()

        try:
            while True:
                await asyncio.sleep(5)
                await self._change_event.wait()

                self._change_event.clear()
                await self._write()

        except Exception as e:
            mlog.error("write loop error: %s", e, exc_info=e)

        finally:
            await aio.uncancellable(cleanup())

    async def _write(self):
        try:
            data = dict(self._data)

            await self._executor.spawn(json.encode_file, data, self._tmp_path,
                                       json.get_file_format(self._path))

            await self._executor.spawn(os.replace, self._tmp_path, self._path)

        except Exception as e:
            mlog.error("write error: %s", e, exc_info=e)

    def _encode_session(self, session: common.UserSession) -> json.Data:
        if isinstance(session, LocalUserSession):
            return {'type': 'local',
                    'data': self._local_manager.encode_session(session)}

        if isinstance(session, OidcUserSession):
            return {'type': 'oidc',
                    'data': self._oidc_manager.encode_session(session)}

        raise TypeError('unsupported session type')

    def _decode_session(self, data: json.Data) -> common.UserSession:
        if data['type'] == 'local':
            return self._local_manager.decode_session(data['data'])

        if data['type'] == 'oidc':
            return self._oidc_manager.decode_session(data['data'])

        raise ValueError('unsupported session type')
