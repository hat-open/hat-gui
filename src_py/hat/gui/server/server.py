"""GUI web server"""

import contextlib
import logging
import secrets

import aiohttp.web

from hat import aio
from hat import json
from hat import juggler
import hat.event.common

import hat.gui.server.adapter
import hat.gui.server.client
import hat.gui.server.user
import hat.gui.server.view


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""

_session_id_cookie_name = 'SESSION_ID'
_session_id_cookie_max_age = 60 * 60 * 24 * 365

_oidc_state_cookie_name = 'OIDC_STATE'


async def create_server(host: str,
                        port: int,
                        name: str,
                        initial_view: str | None,
                        view_manager: hat.gui.server.view.ViewManager,
                        user_manager: hat.gui.server.user.UserManager,
                        adapter_manager: hat.gui.server.adapter.AdapterManager,
                        eventer_client: hat.event.eventer.Client,
                        autoflush_delay: float = 0.2
                        ) -> 'Server':
    """Create server"""
    server = Server()
    server._name = name
    server._initial_view = initial_view
    server._view_manager = view_manager
    server._user_manager = user_manager
    server._adapter_manager = adapter_manager
    server._eventer_client = eventer_client
    server._clients = {}

    additional_routes = [
        aiohttp.web.post(
            '/login/local',
            server._process_post_login_local),
        aiohttp.web.get(
            '/login/oidc/{name}',
            server._process_get_oidc),
        aiohttp.web.get(
            '/login/oidc/{name}/cb',
            server._process_get_oidc_cb),
        aiohttp.web.post(
            '/logout',
            server._process_post_logout),
        aiohttp.web.get(
            '/logout',
            server._process_get_logout),
        aiohttp.web.get(
            '/user',
            server._process_get_user),
        aiohttp.web.get(
            '/ws',
            server._process_get_ws),
        aiohttp.web.get(
            '/{path:.*}',
            server._process_get)]

    server._srv = await juggler.listen(host=host,
                                       port=port,
                                       request_cb=server._on_request,
                                       ws_path=None,
                                       autoflush_delay=autoflush_delay,
                                       parallel_requests=True,
                                       additional_routes=additional_routes)

    mlog.debug("web server listening on %s:%s", host, port)
    return server


class Server(aio.Resource):
    """Server"""

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._srv.async_group

    async def _on_request(self, conn, name, data):
        mlog.debug("new juggler request: %s", name)

        client = self._clients.get(conn)
        if not client:
            raise Exception('invalid connection')

        return await client.process_request(name, data)

    async def _process_post_login_local(self, req):
        mlog.debug("processing POST /login/local")

        session = self._get_user_session(req)
        if session:
            mlog.debug("previous user session detected - closing session")
            session.close()

        try:
            body = await req.json()

            name = body['name']
            if not isinstance(name, str):
                raise Exception('invalid name type')

            password = body['password']
            if not isinstance(name, str):
                raise Exception('invalid password type')

            session = await self._user_manager.create_local_session(
                name=name,
                password=password)

        except Exception as e:
            mlog.error("error processing POST /login/local: %s", e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        res = aiohttp.web.Response()
        res.set_cookie(_session_id_cookie_name,
                       session.session_id,
                       max_age=_session_id_cookie_max_age,
                       httponly=True)

        return res

    async def _process_get_oidc(self, req):
        name = req.match_info['name']

        mlog.debug("processing GET /oidc/%s", name)

        session = self._get_user_session(req)
        if session:
            mlog.debug("previous user session detected - closing session")
            session.close()

        state = secrets.token_urlsafe(32)

        try:
            oidc_url = self._user_manager.get_oidc_url(name=name,
                                                       state=state)

        except Exception as e:
            mlog.error("error processing GET /oidc/%s", name, e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        res_exc = aiohttp.web.HTTPFound(oidc_url)
        res_exc.set_cookie(_oidc_state_cookie_name,
                           state,
                           httponly=True)

        raise res_exc

    async def _process_get_oidc_cb(self, req):
        name = req.match_info['name']

        mlog.debug("processing GET /oidc/%s/cb", name)

        session = self._get_user_session(req)
        if session:
            mlog.debug("previous user session detected - closing session")
            session.close()

        try:
            state_cookie = req.cookies.get(_oidc_state_cookie_name)
            if not state_cookie:
                raise Exception('state cookie not set')

            state = req.query.get('state')
            if state != state_cookie:
                raise Exception('invalid state')

            code = req.query.get('code')
            if not code:
                raise Exception('invalid oidc code')

            session = await self._user_manager.create_oidc_session(
                name=name,
                code=code)

        except Exception as e:
            mlog.error("error processing GET /oidc/%s", name, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        res_exc = aiohttp.web.HTTPFound('/index.html')
        res_exc.set_cookie(_session_id_cookie_name,
                           session.session_id,
                           max_age=_session_id_cookie_max_age,
                           httponly=True)

        raise res_exc

    async def _process_post_logout(self, req):
        mlog.debug("processing POST /logout")

        try:
            session = self._get_user_session(req)
            if not session:
                raise Exception("user session not found")

        except Exception as e:
            mlog.error("error processing POST /logout: %s", e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        session.close()

        return aiohttp.web.Response()

    async def _process_get_logout(self, req):
        mlog.debug("processing GET /logout")

        try:
            session = self._get_user_session(req)
            if not session:
                raise Exception("user session not found")

        except Exception as e:
            mlog.error("error processing GET /logout: %s", e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        session.close()

        raise aiohttp.web.HTTPFound('/index.html')

    async def _process_get_user(self, req):
        mlog.debug("processing GET /user")

        try:
            session = self._get_user_session(req)
            if not session:
                raise Exception("user session not found")

        except Exception as e:
            mlog.error("error processing GET /user: %s", e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        return aiohttp.web.Response(
            content_type='application/json',
            text=json.encode({'name': session.user.name,
                              'roles': list(session.user.roles)}))

    async def _process_get_ws(self, req):
        mlog.debug("processing GET /ws")

        try:
            session = self._get_user_session(req)
            if not session:
                raise Exception("user session not found")

        except Exception as e:
            mlog.error("error processing GET /ws: %s", e, exc_info=e)

            raise aiohttp.web.HTTPBadRequest(text=str(e))

        try:
            mlog.debug("creating juggler connection")
            conn = await self._srv.create_connection(req)

            try:
                mlog.debug("acquiring session")
                session.acquire()

                try:
                    mlog.debug("creating client")
                    client = hat.gui.server.client.Client(
                        conn=conn,
                        user=session.user,
                        adapter_manager=self._adapter_manager)

                    client.async_group.spawn(
                        aio.call_on_done, session.wait_closing(), client.close)

                    self._clients[conn] = client

                    try:
                        await self._register_clients_event()

                        await client.wait_closing()

                    finally:
                        self._clients.pop(conn, None)
                        await aio.uncancellable(self._register_clients_event())

                finally:
                    mlog.debug("releasing session")
                    session.release()

            finally:
                await aio.uncancellable(conn.async_close())

        except Exception as e:
            mlog.error("error creating client: %s", e, exc_info=e)

            raise aiohttp.web.HTTPInternalServerError(text=str(e))

        return conn.ws

    async def _process_get(self, req):
        path = req.match_info['path']

        mlog.debug("processing GET %s", path)

        session = self._get_user_session(req)
        if session:
            mlog.debug("user session found")
            view = session.user.view

        else:
            mlog.debug("user session not found")
            view = self._initial_view

        try:
            if not view:
                raise Exception('view not available')

            for view_path in self._view_manager.get_view_paths(view):
                file_path = (view_path / path).resolve()

                if file_path.is_relative_to(view_path) and file_path.exists():
                    mlog.debug("returning file %s", file_path)
                    return aiohttp.web.FileResponse(path=file_path)

        except Exception as e:
            mlog.error("error processing GET %s: %s", path, e, exc_info=e)

            raise aiohttp.web.HTTPInternalServerError(text=str(e))

        raise aiohttp.web.HTTPNotFound()

    def _get_user_session(self, req):
        session_id = req.cookies.get(_session_id_cookie_name)
        if not session_id:
            return

        session = self._user_manager.get_session(session_id)
        if session:
            mlog.debug("refreshing session")
            session.refresh()

        return session

    async def _register_clients_event(self):
        event = hat.event.common.RegisterEvent(
            type=('gui', self._name, 'clients'),
            source_timestamp=None,
            payload=hat.event.common.EventPayloadJson(
                [{'remote': conn.remote,
                  'user': client.user.name}
                 for conn, client in self._clients.items()]))

        mlog.debug("registering clients event")
        with contextlib.suppress(Exception):
            await self._eventer_client.register([event])
