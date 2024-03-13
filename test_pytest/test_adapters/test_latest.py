import base64
import itertools

from hat import aio
from hat import json
import hat.event.common

from hat.gui.adapters.latest import info


next_event_ids = (hat.event.common.EventId(1, 1, instance)
                  for instance in itertools.count(1))


class EventerClient(aio.Resource):

    def __init__(self, event_cb=None, query_cb=None):
        self._event_cb = event_cb
        self._query_cb = query_cb
        self._async_group = aio.Group()

    @property
    def async_group(self):
        return self._async_group

    @property
    def status(self):
        raise NotImplementedError()

    async def register(self, events, with_response=False):
        if self._event_cb:
            for event in events:
                await aio.call(self._event_cb, event)

        if not with_response:
            return

        timestamp = hat.event.common.now()
        return [hat.event.common.Event(id=next(next_event_ids),
                                       type=event.type,
                                       timestamp=timestamp,
                                       source_timestamp=event.source_timestamp,
                                       payload=event.payload)
                for event in events]

    async def query(self, params):
        if not self._query_cb:
            return hat.event.common.QueryResult([], False)

        return await aio.call(self._query_cb, params)


def create_event(event_type, payload):
    return hat.event.common.Event(id=next(next_event_ids),
                                  type=event_type,
                                  timestamp=hat.event.common.now(),
                                  source_timestamp=None,
                                  payload=payload)


def create_json_event(event_type, payload_data):
    payload = hat.event.common.EventPayloadJson(payload_data)
    return create_event(event_type, payload)


def create_binary_event(event_type, payload_type, payload_data):
    payload = hat.event.common.EventPayloadBinary(payload_type, payload_data)
    return create_event(event_type, payload)


async def test_create_subscription():
    conf = {'authorized_roles': [],
            'items': []}
    subscription = await aio.call(info.create_subscription, conf)
    assert list(subscription.get_query_types()) == []

    conf = {'authorized_roles': [],
            'items': [{'key': str(i),
                       'event_type': ('a', str(i))}
                      for i in range(10)]}
    subscription = await aio.call(info.create_subscription, conf)
    for i in range(10):
        assert subscription.matches(('a', str(i)))
        assert not subscription.matches(('b', str(i)))


async def test_create_adapter_empty():
    conf = {'authorized_roles': [],
            'items': []}

    eventer_client = EventerClient()
    adapter = await aio.call(info.create_adapter, conf, eventer_client)

    await adapter.process_events([])

    assert adapter.is_open

    await adapter.async_close()
    await eventer_client.async_close()


async def test_create_adapter_query():
    params_queue = aio.Queue()

    conf = {'authorized_roles': [],
            'items': [{'key': 'a',
                       'event_type': ['x']},
                      {'key': 'b',
                       'event_type': ['x']},
                      {'key': 'c',
                       'event_type': ['y']}]}

    def on_query(params):
        assert isinstance(params, hat.event.common.QueryLatestParams)

        params_queue.put_nowait(params)
        return hat.event.common.QueryResult([], False)

    eventer_client = EventerClient(query_cb=on_query)
    adapter = await aio.call(info.create_adapter, conf, eventer_client)

    params = await params_queue.get()
    query_event_types = set(params.event_types)
    conf_event_types = {tuple(i['event_type']) for i in conf['items']}
    assert query_event_types == conf_event_types

    await adapter.async_close()
    await eventer_client.async_close()


async def test_create_session():
    conf = {'authorized_roles': ['users'],
            'items': [{'key': 'a',
                       'event_type': ['x']},
                      {'key': 'b',
                       'event_type': ['x']},
                      {'key': 'c',
                       'event_type': ['y']}]}

    eventer_client = EventerClient()
    adapter = await aio.call(info.create_adapter, conf, eventer_client)

    def notify_cb(name, data):
        raise NotImplementedError()

    state1 = json.Storage()
    session1 = await adapter.create_session('user1', {'users'}, state1,
                                            notify_cb)

    state2 = json.Storage()
    session2 = await adapter.create_session('user2', {'not users'}, state2,
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
    await eventer_client.async_close()


async def test_event_payload():
    conf = {'authorized_roles': ['users'],
            'items': [{'key': 'a',
                       'event_type': ['a']}]}

    eventer_client = EventerClient()
    adapter = await aio.call(info.create_adapter, conf, eventer_client)

    def notify_cb(name, data):
        raise NotImplementedError()

    state = json.Storage()
    session = await adapter.create_session('user1', {'users'}, state,
                                           notify_cb)

    assert state.data == {}

    await adapter.process_events([create_json_event(('a',), 123)])
    assert state.data['a']['payload'] == {'type': 'JSON',
                                          'data': 123}

    base64_data = base64.b64encode(b'123').decode()

    await adapter.process_events([create_binary_event(('a',), 'abc', b'123')])
    assert state.data['a']['payload'] == {'type': 'BINARY',
                                          'name': 'abc',
                                          'data': base64_data}

    await session.async_close()
    await adapter.async_close()
    await eventer_client.async_close()
