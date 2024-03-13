import asyncio
import collections
import itertools
import sys
import types

import pytest

from hat import aio
import hat.event.common

from hat.gui import common
import hat.gui.server.adapter


subscription = hat.event.common.Subscription([('a', '*')])

next_event_ids = (hat.event.common.EventId(1, 1, instance)
                  for instance in itertools.count(1))


@pytest.fixture
def create_adapter_module():
    module_names = collections.deque()

    def create_adapter_module(adapter_cb=None,
                              process_events_cb=None,
                              subscription=subscription):
        module_name = f'test_adapter_{len(module_names)}'
        module_names.append(module_name)

        class Adapter(common.Adapter):

            def __init__(self):
                self._async_group = aio.Group()

            @property
            def async_group(self):
                return self._async_group

            async def process_events(self, events):
                if process_events_cb:
                    await aio.call(process_events_cb, events)

            async def create_session(self, user, roles, state, notify_cb):
                raise NotImplementedError()

        def create_subscription(conf):
            return subscription

        async def create_adapter(conf, eventer_client):
            adapter = Adapter()
            if adapter_cb:
                await aio.call(adapter_cb, adapter)

            return adapter

        module = types.ModuleType(module_name)
        module.info = common.AdapterInfo(
            create_subscription=create_subscription,
            create_adapter=create_adapter)
        sys.modules[module_name] = module

        return module_name

    try:
        yield create_adapter_module

    finally:
        for module_name in module_names:
            del sys.modules[module_name]


def create_event(event_type):
    return hat.event.common.Event(id=next(next_event_ids),
                                  type=event_type,
                                  timestamp=hat.event.common.now(),
                                  source_timestamp=None,
                                  payload=None)


@pytest.mark.parametrize('adapter_count', [1, 2, 5])
async def test_get_subscriptions(adapter_count, create_adapter_module):
    modules = [
        create_adapter_module(
            subscription=hat.event.common.Subscription([('a', str(i))]))
        for i in range(adapter_count)]

    confs = [{'name': f'name {i}',
              'module': module}
             for i, module in enumerate(modules)]

    infos = collections.deque()
    for conf in confs:
        info = await hat.gui.server.adapter.create_conf_adapter_info(conf)
        infos.append(info)

    subscriptions = set(hat.gui.server.adapter.get_subscriptions(infos))

    for i in range(adapter_count):
        assert ('a', str(i)) in subscriptions


async def test_create_manager():
    manager = await hat.gui.server.adapter.create_manager([], None)

    assert manager.is_open
    assert manager.adapters == {}

    await manager.async_close()


@pytest.mark.parametrize("adapter_count", [1, 2, 5])
async def test_create_adapters(adapter_count, create_adapter_module):
    modules = [create_adapter_module()
               for i in range(adapter_count)]

    confs = [{'name': f'name {i}',
              'module': module}
             for i, module in enumerate(modules)]

    infos = collections.deque()
    for conf in confs:
        info = await hat.gui.server.adapter.create_conf_adapter_info(conf)
        infos.append(info)

    manager = await hat.gui.server.adapter.create_manager(infos, None)

    assert len(manager.adapters) == adapter_count

    for conf in confs:
        assert conf['name'] in manager.adapters
        assert manager.adapters[conf['name']].is_open

    await manager.async_close()

    for adapter in manager.adapters.values():
        assert adapter.is_closed


async def test_close_adapter(create_adapter_module):
    name = 'name'
    modules = create_adapter_module()

    conf = {'name': name,
            'module': modules}

    info = await hat.gui.server.adapter.create_conf_adapter_info(conf)
    manager = await hat.gui.server.adapter.create_manager([info], None)

    assert manager.is_open
    assert manager.adapters[name].is_open

    manager.adapters[name].close()

    await manager.wait_closed()


async def test_adapter_process_events(create_adapter_module):
    events_queue = aio.Queue()
    name = 'name'

    modules = create_adapter_module(process_events_cb=events_queue.put_nowait)

    conf = {'name': name,
            'module': modules}

    info = await hat.gui.server.adapter.create_conf_adapter_info(conf)
    manager = await hat.gui.server.adapter.create_manager([info], None)

    event = create_event(('a', 'b'))
    await manager.process_events([event])
    result = await events_queue.get()
    assert list(result) == [event]

    event = create_event(('b', 'a'))
    await manager.process_events([event])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(events_queue.get(), 0.001)

    event1 = create_event(('a',))
    event2 = create_event(('b',))
    await manager.process_events([event1, event2])
    result = await events_queue.get()
    assert list(result) == [event1]

    await manager.async_close()


async def test_duplicate_adapter_name(create_adapter_module):
    name = 'name'

    confs = [{'name': name,
              'module': create_adapter_module()},
             {'name': name,
              'module': create_adapter_module()}]

    infos = collections.deque()
    for conf in confs:
        info = await hat.gui.server.adapter.create_conf_adapter_info(conf)
        infos.append(info)

    with pytest.raises(Exception):
        await hat.gui.server.adapter.create_manager(infos, None)
