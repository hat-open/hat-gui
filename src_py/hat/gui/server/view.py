"""View manager implementation"""

from collections.abc import Collection, Iterable
from pathlib import Path
import collections
import contextlib
import importlib.resources

from hat import aio
from hat import json


class ViewManager(aio.Resource):
    """View manager"""

    def __init__(self, view_confs: Iterable[json.Data]):
        self._view_roles = {}
        self._view_paths = {}
        self._async_group = aio.Group()

        exit_stack = contextlib.ExitStack()
        self.async_group.spawn(aio.call_on_cancel, exit_stack.close)

        builtin_views_path = exit_stack.enter_context(
            importlib.resources.as_file(
                importlib.resources.files(__package__) / 'views'))

        for view_conf in view_confs:
            self._view_roles[view_conf['name']] = set(view_conf['roles'])

            view_paths = collections.deque()
            for path_conf in view_conf['paths']:
                if 'path' in path_conf:
                    view_paths.append(Path(path_conf['path']).resolve())

                elif 'builtin' in path_conf:
                    view_paths.append((builtin_views_path /
                                       path_conf['builtin']).resolve())

                else:
                    raise ValueError('unsupported view conf')

            self._view_paths[view_conf['name']] = view_paths

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._async_group

    def get_view(self, roles: set[str]) -> str | None:
        for name, view_roles in self._view_roles.items():
            if not view_roles.isdisjoint(roles):
                return name

    def get_view_paths(self, name: str) -> Collection[Path]:
        try:
            return self._view_paths[name]

        except KeyError:
            raise Exception('invalid view name')
