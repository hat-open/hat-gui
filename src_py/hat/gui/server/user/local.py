from collections.abc import Callable, Iterable, Iterator
import hashlib
import time

from hat import aio
from hat import json

from hat.gui.server.user import common
from hat.gui.server.view import ViewManager


class LocalUserSession(common.UserSession):

    def __init__(self,
                 async_group: aio.Group,
                 user: common.User,
                 session_id: common.UserSessionId,
                 created: common.Timestamp,
                 updated: common.Timestamp,
                 update_cb: Callable[['LocalUserSession'], None]):
        self._async_group = async_group
        self._user = user
        self._session_id = session_id
        self._created = created
        self._updated = updated
        self._update_cb = update_cb

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    @property
    def user(self) -> common.User:
        return self._user

    @property
    def session_id(self) -> common.UserSessionId:
        return self._session_id

    @property
    def created(self) -> common.Timestamp:
        return self._created

    @property
    def updated(self) -> common.Timestamp:
        return self._updated

    def update(self):
        self._updated = time.time()
        self._update_cb(self)


class LocalUserManager(aio.Resource):

    def __init__(self,
                 async_group: aio.Group,
                 local_confs: Iterable[json.Data],
                 view_manager: ViewManager,
                 session_ids: Iterator[common.UserSessionId],
                 session_update_cb: Callable[[common.UserSession], None]):
        self._async_group = async_group
        self._view_manager = view_manager
        self._session_ids = session_ids
        self._session_update_cb = session_update_cb
        self._user_confs = {i['name']: i for i in local_confs}

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    def create_session(self,
                       name: str,
                       password: str
                       ) -> LocalUserSession:
        user = self._get_user(name, password)
        session_id = next(self._session_ids)
        created = time.time()

        return LocalUserSession(async_group=self.async_group.create_subgroup(),
                                user=user,
                                session_id=session_id,
                                created=created,
                                updated=created,
                                update_cb=self._session_update_cb)

    def encode_session(self, session: LocalUserSession) -> json.Data:
        return {'name': session.user.name,
                'session_id': session.session_id,
                'created': session.created,
                'updated': session.updated}

    def decode_session(self, data: json.Data) -> LocalUserSession:
        name = data['name']

        user_conf = self._user_confs.get(name)
        if not user_conf:
            raise Exception('user not available')

        roles = set(user_conf['roles'])
        views = self._view_manager.get_views(roles)

        user = common.User(name=name,
                           roles=roles,
                           views=views)

        return LocalUserSession(async_group=self.async_group.create_subgroup(),
                                user=user,
                                session_id=data['session_id'],
                                created=data['created'],
                                updated=data['updated'],
                                update_cb=self._session_update_cb)

    def _get_user(self, name, password):
        user_conf = self._user_confs.get(name)
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
        views = self._view_manager.get_views(roles)

        return common.User(name=name,
                           roles=roles,
                           views=views)
