"""View manager implementation"""

from collections.abc import Iterable
from pathlib import Path
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

            if 'view_path' in view_conf:
                self._view_paths[view_conf['name']] = Path(
                    view_conf['view_path']).resolve()

            elif 'builtin' in view_conf:
                self._view_paths[view_conf['name']] = (
                    builtin_views_path / view_conf['builtin']).resolve()

            else:
                raise ValueError('unsupported view conf')

    @property
    def async_group(self) -> aio.Group:
        """Async group"""
        return self._async_group

    def get_view(self, roles: set[str]) -> str | None:
        for name, view_roles in self._view_roles.items():
            if not view_roles.isdisjoint(roles):
                return name

    def get_view_path(self, name: str) -> Path | None:
        return self._view_paths.get(name)
