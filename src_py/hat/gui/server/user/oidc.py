from collections.abc import Callable, Iterable, Iterator
import base64
import time
import urllib.parse

import aiohttp

from hat import aio
from hat import json

from hat.gui.server.user import common
from hat.gui.server.view import ViewManager


class OidcUserSession(common.UserSession):

    def __init__(self,
                 async_group: aio.Group,
                 user: common.User,
                 session_id: common.UserSessionId,
                 created: common.Timestamp,
                 updated: common.Timestamp,
                 oidc_conf: json.Data,
                 access_token: str,
                 refresh_token: str | None,
                 update_cb: Callable[['OidcUserSession'], None]):
        self._async_group = async_group
        self._user = user
        self._session_id = session_id
        self._created = created
        self._updated = updated
        self._oidc_conf = oidc_conf
        self._access_token = access_token
        self._refresh_token = refresh_token
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

    @property
    def name(self) -> str:
        return self._oidc_conf['name']

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    def update(self):
        self._updated = time.time()
        self._update_cb(self)


class OidcUserManager(aio.Resource):

    def __init__(self,
                 async_group: aio.Group,
                 oidc_confs: Iterable[json.Data],
                 view_manager: ViewManager,
                 session_ids: Iterator[common.UserSessionId],
                 session_update_cb: Callable[[common.UserSession], None]):
        self._async_group = async_group
        self._view_manager = view_manager
        self._session_ids = session_ids
        self._session_update_cb = session_update_cb
        self._oidc_confs = {i['name']: i for i in oidc_confs}

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    def get_url(self, name: str, state: str) -> str:
        oidc_conf = self._oidc_confs.get(name)
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

    async def create_session(self,
                             name: str,
                             code: str
                             ) -> OidcUserSession:
        oidc_conf = self._oidc_confs.get(name)
        if not oidc_conf:
            raise Exception("invalid name")

        auth = aiohttp.BasicAuth(oidc_conf['client_id'],
                                 oidc_conf['client_secret'])

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

        access_token = data['access_token']
        refresh_token = data.get('refresh_token')

        claims = json.decode(
            _base64url_decode(data['id_token'].split('.')[1]).decode('utf-8'))

        user_name = claims[oidc_conf['claims']['name']]
        if not isinstance(user_name, str):
            raise TypeError('invalid name type')

        roles = set()
        for i in claims[oidc_conf['claims']['roles']]:
            role = oidc_conf['roles'].get(i)
            if role:
                roles.add(role)

        views = self._view_manager.get_views(roles)

        user = common.User(name=user_name,
                           roles=roles,
                           views=views)
        session_id = next(self._session_ids)
        created = time.time()

        return OidcUserSession(async_group=self.async_group.create_subgroup(),
                               user=user,
                               session_id=session_id,
                               created=created,
                               updated=created,
                               oidc_conf=oidc_conf,
                               access_token=access_token,
                               refresh_token=refresh_token,
                               update_cb=self._session_update_cb)

    def encode_session(self, session: OidcUserSession) -> json.Data:
        return {'user': {'name': session.user.name,
                         'roles': list(session.user.roles)},
                'session_id': session.session_id,
                'created': session.created,
                'updated': session.updated,
                'name': session.name,
                'access_token': session.access_token,
                'refresh_token': session.refresh_token}

    def decode_session(self, data: json.Data) -> OidcUserSession:
        name = data['name']

        oidc_conf = self._oidc_confs.get(name)
        if not oidc_conf:
            raise Exception('oidc not available')

        roles = set(data['user']['roles'])
        views = self._view_manager.get_views(roles)

        user = common.User(name=data['user']['name'],
                           roles=roles,
                           views=views)

        return OidcUserSession(async_group=self.async_group.create_subgroup(),
                               user=user,
                               session_id=data['session_id'],
                               created=data['created'],
                               updated=data['updated'],
                               oidc_conf=oidc_conf,
                               access_token=data['access_token'],
                               refresh_token=data['refresh_token'],
                               update_cb=self._session_update_cb)


def _base64url_decode(data: str) -> bytes:
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_oidc_redirect_url(oidc_conf):
    return urllib.parse.urlsplit(
        oidc_conf['local_url'])._replace(
            path=f"/login/oidc/{oidc_conf['name']}/cb",
            query='',
            fragment='').geturl()
