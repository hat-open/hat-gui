import asyncio
import itertools
import sys
import types

import pytest

from hat import aio
import hat.event.common

from hat.gui import common
import hat.gui.engine


subscription = hat.event.common.Subscription([('a', '*')])


class EventerClient(aio.Resource):

    def __init__(self):
        self._async_group = aio.Group()
        self._receive_queue = aio.Queue()

    @property
    def async_group(self):
        return self._async_group

    @property
    def receive_queue(self):
        return self._receive_queue

    async def receive(self):
        return await self._receive_queue.get()


class Adapter(common.Adapter):

    def __init__(self, conf, client):
        self._conf = conf
        self._client = client
        self._async_group = aio.Group()
        self._events_queue = aio.Queue()

    @property
    def async_group(self):
        return self._async_group

    @property
    def conf(self):
        return self._conf

    @property
    def client(self):
        return self._client

    @property
    def events_queue(self):
        return self._events_queue

    async def process_events(self, events):
        self._events_queue.put_nowait(events)

    async def create_session(self, user, roles, state, notify_cb):
        raise NotImplementedError()


@pytest.fixture
def adapter_module():
    for i in itertools.count(1):
        module_name = f'mock_adapter_{i}'
        if module_name not in sys.modules:
            break

    module = types.ModuleType(module_name)
    module.json_schema_id = None
    module.json_schema_repo = None
    module.create_subscription = lambda _: subscription
    module.create_adapter = Adapter
    sys.modules[module_name] = module

    try:
        yield module_name

    finally:
        del sys.modules[module_name]


@pytest.fixture
def create_event():
    counter = itertools.count(1)

    def create_event(event_type):
        event_id = hat.event.common.EventId(1, 1, next(counter))
        event = hat.event.common.Event(event_id=event_id,
                                       event_type=event_type,
                                       timestamp=hat.event.common.now(),
                                       source_timestamp=None,
                                       payload=None)
        return event

    return create_event


async def test_empty_engine():
    conf = {'adapters': []}
    client = EventerClient()
    engine = await hat.gui.engine.create_engine(conf, client)

    assert engine.is_open
    assert engine.adapters == {}

    await engine.async_close()
    await client.async_close()


@pytest.mark.parametrize("adapter_count", [1, 2, 5])
async def test_create_adapters(adapter_module, adapter_count):
    adapter_names = [f'adapter{i}' for i in range(adapter_count)]
    conf = {'adapters': [{'name': name,
                          'module': adapter_module}
                         for name in adapter_names]}
    client = EventerClient()
    engine = await hat.gui.engine.create_engine(conf, client)

    assert len(engine.adapters) == adapter_count

    for name, adapter in engine.adapters.items():
        assert name in adapter_names
        assert name == adapter.conf['name']
        assert adapter.conf in conf['adapters']
        assert adapter.client is client
        assert adapter.is_open

    await engine.async_close()

    for adapter in engine.adapters.values():
        assert adapter.is_closed

    await client.async_close()


async def test_close_adapter(adapter_module):
    name = 'name'
    conf = {'adapters': [{'name': name,
                          'module': adapter_module}]}
    client = EventerClient()
    engine = await hat.gui.engine.create_engine(conf, client)
    adapter = engine.adapters[name]

    assert engine.is_open
    assert adapter.is_open

    await adapter.async_close()
    await engine.wait_closed()
    await client.async_close()


async def test_adapter_process_events(adapter_module, create_event):
    name = 'name'
    conf = {'adapters': [{'name': name,
                          'module': adapter_module}]}
    client = EventerClient()
    engine = await hat.gui.engine.create_engine(conf, client)
    adapter = engine.adapters[name]

    event = create_event(('a', 'b'))
    client.receive_queue.put_nowait([event])
    result = await adapter.events_queue.get()
    assert result == [event]

    event = create_event(('b', 'a'))
    client.receive_queue.put_nowait([event])
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(adapter.events_queue.get(), 0.001)

    event1 = create_event(('a',))
    event2 = create_event(('b',))
    client.receive_queue.put_nowait([event1, event2])
    result = await adapter.events_queue.get()
    assert result == [event1]

    await engine.async_close()
    await client.async_close()


async def test_duplicate_adapter_name(adapter_module):
    name = 'name'
    conf = {'adapters': [{'name': name,
                          'module': adapter_module},
                         {'name': name,
                          'module': adapter_module}]}
    client = EventerClient()

    with pytest.raises(Exception):
        await hat.gui.engine.create_engine(conf, client)

    await client.async_close()
