"""Common GUI interfaces"""

import abc
import importlib.resources
import typing

from hat import aio
from hat import json
from hat.event.common import Event, Subscription
import hat.event.eventer
import hat.monitor.common


with importlib.resources.as_file(importlib.resources.files(__package__) /
                                 'json_schema_repo.json') as _path:
    json_schema_repo: json.SchemaRepository = json.SchemaRepository(
        json.json_schema_repo,
        hat.monitor.common.json_schema_repo,
        json.SchemaRepository.from_json(_path))
    """JSON schema repository"""

AdapterConf: typing.TypeAlias = json.Data
"""Adapter configuration"""

CreateSubscription: typing.TypeAlias = aio.AsyncCallable[[AdapterConf],
                                                         Subscription]
"""Create subscription callable"""

CreateAdapter: typing.TypeAlias = aio.AsyncCallable[[AdapterConf,
                                                     hat.event.eventer.Client],
                                                    'Adapter']
"""Create adapter callable"""

NotifyCb: typing.TypeAlias = typing.Callable[[str, json.Data], None]
"""Juggler notification callback

Args:
    name: notification name
    data: notification data

"""


class Adapter(aio.Resource):
    """Adapter interface

    Adapters are implemented as python modules which are dynamically imported.
    Each adapter instance has configuration which must include `module` -
    python module identifier. It is expected that this module implements:

        * json_schema_id (Optional[str]): JSON schema id
        * json_schema_repo (Optional[json.SchemaRepository]): JSON schema repo
        * create_subscription (CreateSubscription): create subscription
        * create_adapter (CreateAdapter): create new adapter instance

    If module defines JSON schema repositoy and JSON schema id, JSON schema
    repository will be used for additional validation of adapter configuration
    with JSON schema id.

    Subscription is used for filtering events which are notified to adapter
    by `Adapter.process_events` coroutine.

    `create_adapter` is called with adapter instance configuration and adapter
    event client.

    """

    @abc.abstractmethod
    async def process_events(self,
                             events: list[Event]):
        """Process received events"""

    @abc.abstractmethod
    async def create_session(self,
                             user: str,
                             roles: list[str],
                             state: json.Storage,
                             notify_cb: NotifyCb,
                             ) -> 'AdapterSession':
        """Create new adapter session"""


class AdapterSession(aio.Resource):
    """Adapter's single client session"""

    @abc.abstractmethod
    async def process_request(self,
                              name: str,
                              data: json.Data
                              ) -> json.Data:
        """Process juggler request"""


async def bind_resource(async_group: aio.Group,
                        resource: aio.Resource):
    """Bind resource to async group"""
    try:
        async_group.spawn(aio.call_on_cancel, resource.async_close)
        async_group.spawn(aio.call_on_done, resource.wait_closing(),
                          async_group.close)

    except Exception:
        await aio.uncancellable(resource.async_close())
        raise
