from collections.abc import Collection
import asyncio
import collections
import logging

from hat import aio
from hat import json
from hat.drivers import tcp
import hat.event.eventer
import hat.event.component

import hat.gui.server.adapter
import hat.gui.server.server
import hat.gui.server.user
import hat.gui.server.view


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""


class MainRunner(aio.Resource):

    def __init__(self, conf: json.Data):
        self._conf = conf
        self._loop = asyncio.get_running_loop()
        self._async_group = aio.Group()
        self._user_manager = hat.gui.server.user.UserManager(conf['users'])
        self._view_manager = hat.gui.server.view.ViewManager(conf['views'])
        self._adapter_infos = collections.deque()
        self._eventer_component = None
        self._eventer_client = None
        self._eventer_runner = None

        self.async_group.spawn(self._run)

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    async def _run(self):
        try:
            await self._start()
            await self._loop.create_future()

        except Exception as e:
            mlog.error("main runner loop error: %s", e, exc_info=e)

        finally:
            self.close()
            await aio.uncancellable(self._stop())

    async def _start(self):
        event_server_conf = self._conf['event_server']

        for adapter_conf in self._conf['adapters']:
            adapter_info = await hat.gui.server.adapter.create_conf_adapter_info(  # NOQA
                adapter_conf)
            self._adapter_infos.append(adapter_info)

        subscriptions = list(
            hat.gui.server.adapter.get_subscriptions(self._adapter_infos))

        if 'monitor_component' in event_server_conf:
            monitor_component_conf = event_server_conf['monitor_component']

            self._eventer_component = await hat.event.component.connect(
                addr=tcp.Address(monitor_component_conf['host'],
                                 monitor_component_conf['port']),
                name=self._conf['gui_name'],
                group=monitor_component_conf['gui_group'],
                server_group=monitor_component_conf['event_server_group'],
                runner_cb=self._create_eventer_runner,
                events_cb=self._on_component_events,
                eventer_kwargs={'subscriptions': subscriptions})
            _bind_resource(self.async_group, self._eventer_component)

            await self._eventer_component.set_ready(True)

        elif 'eventer_server' in event_server_conf:
            eventer_server_conf = event_server_conf['eventer_server']

            self._eventer_client = await hat.event.eventer.connect(
                addr=tcp.Address(eventer_server_conf['host'],
                                 eventer_server_conf['port']),
                client_name=self._conf['gui_name'],
                subscriptions=subscriptions,
                events_cb=self._on_client_events)
            _bind_resource(self.async_group, self._eventer_client)

            self._eventer_runner = EventerRunner(
                conf=self._conf,
                user_manager=self._user_manager,
                view_manager=self._view_manager,
                adapter_infos=self._adapter_infos,
                eventer_client=self._eventer_client)
            _bind_resource(self.async_group, self._eventer_runner)

        else:
            raise Exception('invalid configuration')

    async def _stop(self):
        if self._eventer_runner and not self._eventer_component:
            await self._eventer_runner.async_close()

        if self._eventer_client:
            await self._eventer_client.async_close()

        if self._eventer_component:
            await self._eventer_component.async_close()

        await self._view_manager.async_close()

    async def _create_eventer_runner(self, monitor_component, server_data,
                                     eventer_client):
        self._eventer_runner = EventerRunner(
            conf=self._conf,
            user_manager=self._user_manager,
            view_manager=self._view_manager,
            adapter_infos=self._adapter_infos,
            eventer_client=eventer_client)

        return self._eventer_runner

    async def _process_events(self, events):
        if not self._eventer_runner:
            return

        await self._eventer_runner.process_events(events)

    async def _on_component_events(self, monitor_component, eventer_client,
                                   events):
        await self._process_events(events)

    async def _on_client_events(self, eventer_client, events):
        await self._process_events(events)


class EventerRunner(aio.Resource):

    def __init__(self,
                 conf: json.Data,
                 user_manager: hat.gui.server.user.UserManager,
                 view_manager: hat.gui.server.view.ViewManager,
                 adapter_infos: Collection[hat.gui.server.adapter.ConfAdapterInfo],  # NOQA
                 eventer_client: hat.event.eventer.Client):
        self._conf = conf
        self._user_manager = user_manager
        self._view_manager = view_manager
        self._adapter_infos = adapter_infos
        self._eventer_client = eventer_client
        self._loop = asyncio.get_running_loop()
        self._async_group = aio.Group()
        self._events_queue = collections.deque()
        self._adapter_manager = None
        self._server = None

        self.async_group.spawn(self._run)

    @property
    def async_group(self) -> aio.Group:
        return self._async_group

    async def process_events(self, events: Collection[hat.event.common.Event]):
        if self._events_queue is not None:
            self._events_queue.append(events)
            return

        await self._adapter_manager.process_events(events)

    async def _run(self):
        try:
            await self._start()
            await self._loop.create_future()

        except Exception as e:
            mlog.error("main runner loop error: %s", e, exc_info=e)

        finally:
            self.close()
            await aio.uncancellable(self._stop())

    async def _start(self):
        self._adapter_manager = await hat.gui.server.adapter.create_manager(
            infos=self._adapter_infos,
            eventer_client=self._eventer_client)
        _bind_resource(self.async_group, self._adapter_manager)

        while self._events_queue:
            events = self._events_queue.popleft()
            await self._adapter_manager.process_events(events)

        self._events_queue = None

        server = await hat.gui.server.server.create_server(
            host=self._conf['address']['host'],
            port=self._conf['address']['port'],
            initial_view=self._conf.get('initial_view'),
            client_conf=self._conf.get('client'),
            user_manager=self._user_manager,
            view_manager=self._view_manager,
            adapter_manager=self._adapter_manager)
        _bind_resource(self.async_group, server)

    async def _stop(self):
        if self._server:
            await self._server.async_close()

        if self._adapter_manager:
            await self._adapter_manager.async_close()


def _bind_resource(async_group, resource):
    async_group.spawn(aio.call_on_done, resource.wait_closing(),
                      async_group.close)
