"""GUI server main"""

from pathlib import Path
import argparse
import asyncio
import collections
import contextlib
import functools
import importlib
import itertools
import logging.config
import sys
import typing

import appdirs

from hat import aio
from hat import json
import hat.event.common
import hat.event.eventer_client
import hat.gui.engine
import hat.gui.server
import hat.gui.view
import hat.monitor.client


package_path: Path = Path(__file__).parent
"""Python package path"""

user_conf_dir: Path = Path(appdirs.user_config_dir('hat'))
"""User configuration directory path"""


def create_argument_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--conf', metavar='PATH', type=Path, default=None,
        help="configuration defined by hat-gui://main.yaml# "
             "(default $XDG_CONFIG_HOME/hat/gui.{yaml|yml|json})")
    return parser


def main():
    """GUI Server"""
    parser = create_argument_parser()
    args = parser.parse_args()

    conf_path = args.conf
    if not conf_path:
        for suffix in ('.yaml', '.yml', '.json'):
            conf_path = (user_conf_dir / 'gui').with_suffix(suffix)
            if conf_path.exists():
                break

    if conf_path == Path('-'):
        conf = json.decode_stream(sys.stdin)
    else:
        conf = json.decode_file(conf_path)

    sync_main(conf)


def sync_main(conf: json.Data):
    """Sync main entry point"""
    aio.init_asyncio()

    hat.gui.common.json_schema_repo.validate('hat-gui://main.yaml#', conf)

    for adapter_conf in conf['adapters']:
        module = importlib.import_module(adapter_conf['module'])
        if module.json_schema_repo and module.json_schema_id:
            module.json_schema_repo.validate(module.json_schema_id,
                                             adapter_conf)

    logging.config.dictConfig(conf['log'])

    with contextlib.suppress(asyncio.CancelledError):
        aio.run_asyncio(async_main(conf))


async def async_main(conf: json.Data):
    """Async main entry point"""
    async_group = aio.Group()

    try:
        subscription = await _create_subscription(conf)
        subscriptions = list(subscription.get_query_types())

        if 'monitor' in conf:
            monitor = await hat.monitor.client.connect(conf['monitor'])
            _bind_resource(async_group, monitor)

            component = hat.monitor.client.Component(
                monitor, run_with_monitor, conf, monitor, subscriptions)
            component.set_ready(True)
            _bind_resource(async_group, component)

            await async_group.wait_closing()

        else:
            client = await hat.event.eventer_client.connect(
                conf['event_server_address'], subscriptions)
            _bind_resource(async_group, client)

            await async_group.spawn(run_with_event, conf, client)

    finally:
        await aio.uncancellable(async_group.async_close())


async def run_with_monitor(component: hat.monitor.client.Component,
                           conf: json.Data,
                           monitor: hat.monitor.client.Client,
                           subscriptions: typing.List[hat.event.common.EventType]):  # NOQA
    """Run monitor component"""
    run_cb = functools.partial(run_with_event, conf)
    await hat.event.eventer_client.run_eventer_client(
        monitor, conf['event_server_group'], run_cb, subscriptions)


async def run_with_event(conf: json.Data,
                         client: hat.event.eventer_client.EventerClient):
    """Run event client"""
    async_group = aio.Group()

    try:
        engine = await hat.gui.engine.create_engine(conf, client)
        _bind_resource(async_group, engine)

        views = await hat.gui.view.create_view_manager(conf)
        _bind_resource(async_group, views)

        server = await hat.gui.server.create_server(conf, engine.adapters,
                                                    views)
        _bind_resource(async_group, server)

        await async_group.wait_closing()

    finally:
        await aio.uncancellable(async_group.async_close())


def _bind_resource(async_group, resource):
    async_group.spawn(aio.call_on_cancel, resource.async_close)
    async_group.spawn(aio.call_on_done, resource.wait_closing(),
                      async_group.close)


async def _create_subscription(conf):
    subscriptions = collections.deque()
    for adapter_conf in conf['adapters']:
        module = importlib.import_module(adapter_conf['module'])
        subscription = await aio.call(module.create_subscription, adapter_conf)
        subscriptions.append(subscription)

    query_types = itertools.chain.from_iterable(i.get_query_types()
                                                for i in subscriptions)
    return hat.event.common.Subscription(query_types)


if __name__ == '__main__':
    sys.argv[0] = 'hat-gui'
    sys.exit(main())
