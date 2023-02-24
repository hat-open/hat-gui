"""Latest adapter

This adapter provides latest event for each configured event type.

"""

import base64
import collections
import functools

from hat import aio
from hat import json
import hat.event.common

from hat.gui import common


json_schema_id = 'hat-gui://adapters/latest.yaml#'
json_schema_repo = common.json_schema_repo


def create_subscription(conf):
    return hat.event.common.Subscription([tuple(i['event_type'])
                                          for i in conf['items']])


async def create_adapter(conf, eventer_client):
    adapter = LatestAdapter()
    adapter._authorized_roles = set(conf['authorized_roles'])
    adapter._async_group = aio.Group()

    adapter._event_type_keys = {}
    for item in conf['items']:
        event_type = tuple(item['event_type'])
        if event_type not in adapter._event_type_keys:
            adapter._event_type_keys[event_type] = collections.deque()
        adapter._event_type_keys[event_type].append(item['key'])

    if adapter._event_type_keys:
        events = await eventer_client.query(hat.event.common.QueryData(
            event_types=[i for i in adapter._event_type_keys],
            unique_type=True))

    else:
        events = []

    adapter._state = json.Storage(dict(adapter._events_to_data(events)))

    return adapter


class LatestAdapter(common.Adapter):

    @property
    def async_group(self):
        return self._async_group

    async def process_events(self, events):
        data = dict(self._events_to_data(events))
        if not data:
            return

        self._state.set([], {**self._state.data, **data})

    async def create_session(self, user, roles, state, notify_cb):
        session = LatestSession()
        session._async_group = self.async_group.create_subgroup()

        roles = set(roles)
        is_authorized = not roles.isdisjoint(self._authorized_roles)

        if is_authorized:
            change_cb = functools.partial(state.set, [])
            handle = self._state.register_change_cb(change_cb)
            session.async_group.spawn(aio.call_on_cancel, handle.cancel)
            change_cb(self._state.data)

        else:
            state.set([], {})

        return session

    def _events_to_data(self, events):
        for event in events:
            for key in self._event_type_keys.get(event.event_type, []):
                yield key, _event_to_data(event)


class LatestSession(common.AdapterSession):

    @property
    def async_group(self):
        return self._async_group

    async def process_request(self, name, data):
        raise Exception('not supported')


def _event_to_data(event):
    timestamp = hat.event.common.timestamp_to_float(event.timestamp)
    source_timestamp = (
        hat.event.common.timestamp_to_float(event.source_timestamp)
        if event.source_timestamp is not None else None)
    return dict(timestamp=timestamp,
                source_timestamp=source_timestamp,
                payload=_event_payload_to_json(event.payload))


def _event_payload_to_json(payload):
    if payload is None:
        return

    if payload.type == hat.event.common.EventPayloadType.JSON:
        return {'type': 'JSON',
                'data': payload.data}

    if payload.type == hat.event.common.EventPayloadType.BINARY:
        return {'type': 'BINARY',
                'data': base64.b64encode(payload.data).decode()}

    if payload.type == hat.event.common.EventPayloadType.SBS:
        return {'type': 'SBS',
                'data': {'module': payload.data.module,
                         'type': payload.data.type,
                         'data': base64.b64encode(payload.data.data).decode()}}

    raise ValueError('unsupported payload type')
