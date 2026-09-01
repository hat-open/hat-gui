from pathlib import Path
import subprocess

from hat.doit import common


__all__ = ['task_views',
           'task_views_login',
           'task_views_login_ts',
           'task_views_login_static']


src_py_dir = Path('src_py')
src_js_dir = Path('src_js')
src_static_dir = Path('src_static')
node_modules_dir = Path('node_modules')

views_dir = src_py_dir / 'hat/gui/server/views'


def task_views():
    """Build views"""
    return {'actions': None,
            'task_dep': ['views_login']}


def task_views_login():
    """Build login view"""
    return {'actions': None,
            'task_dep': ['views_login_ts',
                         'views_login_static']}


def task_views_login_ts():
    """Build login view TypeScript"""

    def build(args):
        args = args or []
        subprocess.run(['npx', 'tsc', '-p', 'tsconfig.login.json', *args],
                       check=True)

    return {'actions': [build],
            'pos_arg': 'args',
            'task_dep': ['node_modules']}


def task_views_login_static():
    """Copy login view static files"""
    view_dir = views_dir / 'login'
    return common.get_task_copy([(src_static_dir / 'login',
                                  view_dir),
                                 (node_modules_dir / '@hat-open/juggler',
                                  view_dir / 'script/@hat-open/juggler'),
                                 (node_modules_dir / '@hat-open/renderer',
                                  view_dir / 'script/@hat-open/renderer'),
                                 (node_modules_dir / '@hat-open/util',
                                  view_dir / 'script/@hat-open/util'),
                                 (node_modules_dir / 'snabbdom/build',
                                  view_dir / 'script/snabbdom')],
                                task_dep=['node_modules'])
