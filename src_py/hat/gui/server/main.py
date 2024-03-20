"""GUI server main"""

from pathlib import Path
import argparse
import asyncio
import contextlib
import logging.config
import sys

import appdirs

from hat import aio
from hat import json

from hat.gui import common
from hat.gui.server.runner import MainRunner


mlog: logging.Logger = logging.getLogger('hat.gui.server.main')
"""Module logger"""

user_conf_dir: Path = Path(appdirs.user_config_dir('hat'))
"""User configuration directory path"""


def create_argument_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--conf', metavar='PATH', type=Path, default=None,
        help="configuration defined by hat-gui://server.yaml "
             "(default $XDG_CONFIG_HOME/hat/gui.{yaml|yml|toml|json})")
    return parser


def main():
    """GUI Server"""
    parser = create_argument_parser()
    args = parser.parse_args()
    conf = json.read_conf(args.conf, user_conf_dir / 'gui')
    sync_main(conf)


def sync_main(conf: json.Data):
    """Sync main entry point"""
    aio.init_asyncio()

    common.json_schema_repo.validate('hat-gui://server.yaml', conf)

    for adapter_conf in conf['adapters']:
        info = common.import_adapter_info(adapter_conf['module'])
        if info.json_schema_repo and info.json_schema_id:
            info.json_schema_repo.validate(info.json_schema_id, adapter_conf)

    log_conf = conf.get('log')
    if log_conf:
        logging.config.dictConfig(log_conf)

    with contextlib.suppress(asyncio.CancelledError):
        aio.run_asyncio(async_main(conf))


async def async_main(conf: json.Data):
    """Async main entry point"""
    main_runner = MainRunner(conf)

    async def cleanup():
        await main_runner.async_close()
        await asyncio.sleep(0.1)

    try:
        await main_runner.wait_closing()

    finally:
        await aio.uncancellable(cleanup())


if __name__ == '__main__':
    sys.argv[0] = 'hat-gui-server'
    sys.exit(main())
