"""GUI engine"""

import collections
import importlib
import logging
import typing

from hat import aio
from hat import json
from hat.gui import common
from hat.event.eventer_client import EventerClient


mlog: logging.Logger = logging.getLogger(__name__)
"""Module logger"""


async def create_engine(conf: json.Data,
                        eventer_client: EventerClient
                        ) -> 'Engine':
    """Create GUI engine"""
    engine = Engine()
    engine._eventer_client = eventer_client
    engine._async_group = aio.Group()
    engine._adapters = {}
    engine._adapter_subscriptions = {}

    try:
        for adapter_conf in conf['adapters']:
            name = adapter_conf['name']
            if name in engine._adapters:
                raise Exception(f'adapter name {name} not unique')

            module = importlib.import_module(adapter_conf['module'])
            adapter = await aio.call(module.create_adapter, adapter_conf,
                                     eventer_client)
            await common.bind_resource(engine.async_group, adapter)

            engine._adapters[name] = adapter
            engine._adapter_subscriptions[name] = await aio.call(
                module.create_subscription, adapter_conf)

        engine.async_group.spawn(engine._receive_loop)

    except BaseException:
        await aio.uncancellable(engine.async_close())
        raise

    return engine


class Engine(aio.Resource):
    """GUI engine"""

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._async_group

    @property
    def adapters(self) -> typing.Dict[str, common.Adapter]:
        """Adapters"""
        return self._adapters

    async def _receive_loop(self):
        try:
            while True:
                events = await self._eventer_client.receive()
                adapter_events = {}

                for event in events:
                    adapter_subscriptions = self._adapter_subscriptions.items()
                    for name, subscription in adapter_subscriptions:
                        if not subscription.matches(event.event_type):
                            continue

                        if name not in adapter_events:
                            adapter_events[name] = collections.deque()

                        adapter_events[name].append(event)

                for name, events in adapter_events.items():
                    await self._adapters[name].process_events(list(events))

        except (aio.QueueClosedError, ConnectionError):
            pass

        except Exception as e:
            mlog.error('read loop error: %s', e, exc_info=e)

        finally:
            self.close()
