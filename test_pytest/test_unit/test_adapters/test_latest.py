import asyncio
import base64
import itertools

import pytest

from hat import aio
from hat import json

import hat.gui.adapters.latest


@pytest.fixture
def create_event():
    counter = itertools.count(1)

    def create_event(event_type, payload):
        event_id = hat.event.common.EventId(1, 1, next(counter))
        event = hat.event.common.Event(event_id=event_id,
                                       event_type=event_type,
                                       timestamp=hat.event.common.now(),
                                       source_timestamp=None,
                                       payload=payload)
        return event

    return create_event


@pytest.fixture
def create_json_event(create_event):

    def create_json_event(event_type, data):
        payload = hat.event.common.EventPayload(
            hat.event.common.EventPayloadType.JSON, data)
        return create_event(event_type, payload)

    return create_json_event


@pytest.fixture
def create_binary_event(create_event):

    def create_binary_event(event_type, data):
        payload = hat.event.common.EventPayload(
            hat.event.common.EventPayloadType.BINARY, data)
        return create_event(event_type, payload)

    return create_binary_event


@pytest.fixture
def create_sbs_event(create_event):

    def create_sbs_event(event_type, sbs_module, sbs_type, sbs_data):
        payload = hat.event.common.EventPayload(
            hat.event.common.EventPayloadType.SBS,
            hat.event.common.SbsData(sbs_module, sbs_type, sbs_data))
        return create_event(event_type, payload)

    return create_sbs_event


class EventerClient(aio.Resource):

    def __init__(self, query_response=[]):
        self._query_response = query_response
        self._async_group = aio.Group()
        self._query_queue = aio.Queue()

    @property
    def async_group(self):
        return self._async_group

    @property
    def query_queue(self):
        return self._query_queue

    async def query(self, data):
        self._query_queue.put_nowait(data)
        return self._query_response


async def test_create_subscription():
    conf = {'authorized_roles': [],
            'items': []}
    subscription = await aio.call(hat.gui.adapters.latest.create_subscription,
                                  conf)
    assert list(subscription.get_query_types()) == []

    conf = {'authorized_roles': [],
            'items': [{'key': str(i),
                       'event_type': ('a', str(i))}
                      for i in range(10)]}
    subscription = await aio.call(hat.gui.adapters.latest.create_subscription,
                                  conf)
    for i in range(10):
        assert subscription.matches(('a', str(i)))
        assert not subscription.matches(('b', str(i)))


async def test_create_adapter_empty(create_event):
    conf = {'authorized_roles': [],
            'items': []}
    eventer_client = EventerClient()
    adapter = await aio.call(hat.gui.adapters.latest.create_adapter,
                             conf, eventer_client)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(eventer_client.query_queue.get(), 0.001)

    await adapter.process_events([])

    await adapter.async_close()
    await eventer_client.async_close()


async def test_create_adapter_query():
    conf = {'authorized_roles': [],
            'items': [{'key': 'a',
                       'event_type': ['x']},
                      {'key': 'b',
                       'event_type': ['x']},
                      {'key': 'c',
                       'event_type': ['y']}]}
    event_client = EventerClient()
    adapter = await aio.call(hat.gui.adapters.latest.create_adapter,
                             conf, event_client)

    query_data = await event_client.query_queue.get()
    query_event_types = set(query_data.event_types)
    conf_event_types = {tuple(i['event_type']) for i in conf['items']}
    assert query_event_types == conf_event_types

    await adapter.async_close()
    await event_client.async_close()


async def test_create_session(create_event):
    conf = {'authorized_roles': ['users'],
            'items': [{'key': 'a',
                       'event_type': ['x']},
                      {'key': 'b',
                       'event_type': ['x']},
                      {'key': 'c',
                       'event_type': ['y']}]}
    event_client = EventerClient()
    adapter = await aio.call(hat.gui.adapters.latest.create_adapter,
                             conf, event_client)

    def notify_cb(name, data):
        raise NotImplementedError()

    state1 = json.Storage()
    session1 = await adapter.create_session('user1', ['users'], state1,
                                            notify_cb)

    state2 = json.Storage()
    session2 = await adapter.create_session('user2', ['not users'], state2,
                                            notify_cb)

    assert session1.is_open
    assert session2.is_open

    assert state1.data == {}
    assert state2.data == {}

    await adapter.process_events([create_event(('x',), None),
                                  create_event(('y',), None),
                                  create_event(('z',), None)])

    assert set(state1.data.keys()) == {'a', 'b', 'c'}
    assert state2.data == {}

    await session1.async_close()
    await session2.async_close()

    assert adapter.is_open

    await adapter.async_close()
    await event_client.async_close()


async def test_event_payload(create_json_event, create_binary_event,
                             create_sbs_event):

    conf = {'authorized_roles': ['users'],
            'items': [{'key': 'a',
                       'event_type': ['a']}]}
    event_client = EventerClient()
    adapter = await aio.call(hat.gui.adapters.latest.create_adapter,
                             conf, event_client)

    def notify_cb(name, data):
        raise NotImplementedError()

    state = json.Storage()
    session = await adapter.create_session('user1', ['users'], state,
                                           notify_cb)

    assert state.data == {}

    await adapter.process_events([create_json_event(('a',), 123)])
    assert state.data['a']['payload'] == {'type': 'JSON',
                                          'data': 123}

    base64_data = base64.b64encode(b'123').decode()

    await adapter.process_events([create_binary_event(('a',), b'123')])
    assert state.data['a']['payload'] == {'type': 'BINARY',
                                          'data': base64_data}

    await adapter.process_events([create_sbs_event(('a',), 'x', 'y', b'123')])
    assert state.data['a']['payload'] == {'type': 'SBS',
                                          'data': {'module': 'x',
                                                   'type': 'y',
                                                   'data': base64_data}}

    await session.async_close()
    await adapter.async_close()
    await event_client.async_close()
