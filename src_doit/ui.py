from pathlib import Path
import subprocess

from hat.doit import common


__all__ = ['task_ui',
           'task_ui_ts',
           'task_ui_static']


build_dir = Path('build')
node_modules_dir = Path('node_modules')
src_js_dir = Path('src_js')
src_py_dir = Path('src_py')
src_static_dir = Path('src_static')

ui_dir = src_py_dir / 'hat/gui/server/ui'


def task_ui():
    """Build UI"""
    return {'actions': None,
            'task_dep': ['ui_ts',
                         'ui_static']}


def task_ui_ts():
    """Build UI TypeScript"""

    def build(args):
        args = args or []
        subprocess.run(['npx', 'tsc', '-p', 'tsconfig.ui.json', *args],
                       check=True)

    return {'actions': [build],
            'pos_arg': 'args',
            'task_dep': ['node_modules']}


def task_ui_static():
    """Copy UI static files"""
    return common.get_task_copy([(src_static_dir / 'ui',
                                  ui_dir),
                                 (node_modules_dir / '@hat-open/juggler',
                                  ui_dir / 'script/@hat-open/juggler'),
                                 (node_modules_dir / '@hat-open/renderer',
                                  ui_dir / 'script/@hat-open/renderer'),
                                 (node_modules_dir / '@hat-open/util',
                                  ui_dir / 'script/@hat-open/util'),
                                 (node_modules_dir / 'snabbdom/build',
                                  ui_dir / 'script/snabbdom')],
                                task_dep=['node_modules'])
