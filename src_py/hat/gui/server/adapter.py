"""GUI engine"""

from collections.abc import Collection, Iterable
import collections
import itertools
import logging
import typing

from hat import aio
from hat import json
import hat.event.eventer

from hat.gui import common


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""


class ConfAdapterInfo(typing.NamedTuple):
    conf: common.AdapterConf
    subscription: hat.event.common.Subscription
    create_adapter: common.CreateAdapter


async def create_conf_adapter_info(adapter_conf: Iterable[json.Data]
                                   ) -> ConfAdapterInfo:
    info = common.import_adapter_info(adapter_conf['module'])
    subscription = await aio.call(info.create_subscription, adapter_conf)

    return ConfAdapterInfo(conf=adapter_conf,
                           subscription=subscription,
                           create_adapter=info.create_adapter)


def get_subscriptions(infos: Iterable[ConfAdapterInfo]
                      ) -> Iterable[hat.event.common.EventType]:
    query_types = itertools.chain.from_iterable(
        info.subscription.get_query_types()
        for info in infos)
    subscription = hat.event.common.create_subscription(query_types)

    return subscription.get_query_types()


async def create_manager(infos: Iterable[ConfAdapterInfo],
                         eventer_client: hat.event.eventer.Client
                         ) -> 'AdapterManager':
    manager = AdapterManager()
    manager._async_group = aio.Group()
    manager._infos = {}
    manager._adapters = {}

    try:
        for info in infos:
            name = info.conf['name']
            if name in manager._infos:
                raise Exception(f'adapter name {name} not unique')

            adapter = await aio.call(info.create_adapter, info.conf,
                                     eventer_client)
            await _bind_resource(manager.async_group, adapter)

            manager._infos[name] = info
            manager._adapters[name] = adapter

    except BaseException:
        await aio.uncancellable(manager.async_close())
        raise

    return manager


class AdapterManager(aio.Resource):
    """Adapter manager"""

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._async_group

    @property
    def adapters(self) -> dict[str, common.Adapter]:
        """Adapters"""
        return self._adapters

    async def process_events(self, events: Collection[hat.event.common.Event]):
        mlog.debug('received new events (count: %s)', len(events))

        adapter_events = collections.defaultdict(collections.deque)
        for event in events:
            for name, info in self._infos.items():
                if not info.subscription.matches(event.type):
                    continue

                adapter_events[name].append(event)

        for name, events in adapter_events.items():
            mlog.debug('processing events (adapter: %s; count: %s)',
                       name, len(events))
            await aio.call(self._adapters[name].process_events, events)


async def _bind_resource(async_group, resource):
    try:
        async_group.spawn(aio.call_on_cancel, resource.async_close)
        async_group.spawn(aio.call_on_done, resource.wait_closing(),
                          async_group.close)

    except Exception:
        await aio.uncancellable(resource.async_close())
        raise
