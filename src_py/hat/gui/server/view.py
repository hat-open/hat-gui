"""View manager implementation"""

from collections.abc import Iterable
from pathlib import Path
import base64
import importlib.resources
import typing

from hat import aio
from hat import json


class View(typing.NamedTuple):
    """View data"""
    name: str
    conf: json.Data
    data: dict[str, json.Data]


class ViewManager(aio.Resource):
    """View manager"""

    def __init__(self, view_confs: Iterable[json.Data]):
        self._view_confs = {view_conf['name']: view_conf
                            for view_conf in view_confs}
        self._executor = aio.Executor(log_exceptions=False)

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._executor.async_group

    async def get(self,
                  name: str
                  ) -> View:
        """Get view"""
        if not self.is_open:
            raise Exception('view manager is not open')

        conf = self._view_confs[name]

        if 'view_path' in conf:
            view_data = await self._executor.spawn(_ext_get_view_data,
                                                   Path(conf['view_path']))

        elif 'builtin' in conf:
            view_data = await self._executor.spawn(_ext_get_builtin_view_data,
                                                   conf['builtin'])

        else:
            raise ValueError('unknown view data path')

        if 'conf_path' in conf:
            view_conf = await self._executor.spawn(json.decode_file,
                                                   Path(conf['conf_path']))

        elif 'conf' in conf:
            view_conf = conf['conf']

        else:
            raise ValueError('unknown view conf')

        schema = (view_data.get('schema.json') or
                  view_data.get('schema.yaml') or
                  view_data.get('schema.yml'))
        if schema is not None:
            repo = json.create_schema_repository(schema)
            validator = json.DefaultSchemaValidator(repo)
            validator.validate(schema['id'], view_conf)

        return View(name=name,
                    conf=view_conf,
                    data=view_data)


def _ext_get_builtin_view_data(builtin_name):
    with importlib.resources.as_file(importlib.resources.files(__package__) /
                                     'views') as _path:
        return _ext_get_view_data(_path / builtin_name)


def _ext_get_view_data(view_path):
    data = {}
    for i in view_path.rglob('*'):
        if i.is_dir():
            continue

        if i.suffix in {'.js', '.css', '.txt'}:
            with open(i, encoding='utf-8') as f:
                content = f.read()

        elif i.suffix in {'.json', '.yaml', '.yml', '.toml'}:
            content = json.decode_file(i)

        elif i.suffix in {'.xml', '.svg'}:
            with open(i, encoding='utf-8') as f:
                content = json.vt.parse(f)

        else:
            with open(i, 'rb') as f:
                content = f.read()
            content = base64.b64encode(content).decode('utf-8')

        file_name = i.relative_to(view_path).as_posix()
        data[file_name] = content

    return data
