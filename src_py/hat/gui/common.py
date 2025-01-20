"""Common GUI interfaces"""

from collections.abc import Collection
import abc
import importlib.resources
import typing

from hat import aio
from hat import json
import hat.event.common
import hat.event.eventer


with importlib.resources.as_file(importlib.resources.files(__package__) /
                                 'json_schema_repo.json') as _path:
    json_schema_repo: json.SchemaRepository = json.merge_schema_repositories(
        json.json_schema_repo,
        json.decode_file(_path))
    """JSON schema repository"""


NotifyCb: typing.TypeAlias = typing.Callable[[str, json.Data], None]
"""Juggler notification callback

Args:
    name: notification name
    data: notification data

"""


class AdapterSession(aio.Resource):
    """Adapter's single client session"""

    @abc.abstractmethod
    async def process_request(self,
                              name: str,
                              data: json.Data
                              ) -> json.Data:
        """Process juggler request

        This method can be coroutine or regular function.

        """


class Adapter(aio.Resource):
    """Adapter interface"""

    @abc.abstractmethod
    async def process_events(self,
                             events: Collection[hat.event.common.Event]):
        """Process received events

        This method can be coroutine or regular function.

        """

    @abc.abstractmethod
    async def create_session(self,
                             user: str,
                             roles: set[str],
                             state: json.Storage,
                             notify_cb: NotifyCb,
                             ) -> AdapterSession:
        """Create new adapter session

        This method can be coroutine or regular function.

        """


AdapterConf: typing.TypeAlias = json.Data
"""Adapter configuration"""

CreateSubscription: typing.TypeAlias = aio.AsyncCallable[
    [AdapterConf],
    hat.event.common.Subscription]
"""Create subscription callable"""

CreateAdapter: typing.TypeAlias = aio.AsyncCallable[
    [AdapterConf, hat.event.eventer.Client],
    Adapter]
"""Create adapter callable"""


class AdapterInfo(typing.NamedTuple):
    """Adapter info

    Adapter is implemented as python modules which is dynamically imported.
    It is expected that this module contains `info` which is instance of
    `AdapterInfo`.

    Each adapter instance has configuration which must include `module` -
    python module identifier. It is expected that this module implements:

    If adapter defines JSON schema repository and JSON schema id, JSON schema
    repository will be used for additional validation of adapter configuration
    with JSON schema id.

    Subscription obtained by calling `create_subscription` is used for
    filtering events which are notified to adapter by `Adapter.process_events`.

    """
    create_subscription: CreateSubscription
    create_adapter: CreateAdapter
    json_schema_id: str | None = None
    json_schema_repo: json.SchemaRepository | None = None


def import_adapter_info(py_module_str: str) -> AdapterInfo:
    """Import module info"""
    py_module = importlib.import_module(py_module_str)
    info = py_module.info

    if not isinstance(info, AdapterInfo):
        raise Exception('invalid adapter implementation')

    return info
