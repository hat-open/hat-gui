from .views import *  # NOQA

from pathlib import Path

from hat.doit import common
from hat.doit.docs import (build_sphinx,
                           build_pdoc)
from hat.doit.js import (ESLintConf,
                         run_eslint)
from hat.doit.py import (get_task_build_wheel,
                         get_task_run_pytest,
                         run_flake8)

from . import views


__all__ = ['task_clean_all',
           'task_node_modules',
           'task_build',
           'task_check',
           'task_test',
           'task_docs',
           'task_json_schema_repo',
           *views.__all__]


build_dir = Path('build')
docs_dir = Path('docs')
node_modules_dir = Path('node_modules')
pytest_dir = Path('test_pytest')
schemas_json_dir = Path('schemas_json')
src_js_dir = Path('src_js')
src_py_dir = Path('src_py')
src_static_dir = Path('src_static')

build_docs_dir = build_dir / 'docs'
build_js_dir = build_dir / 'js'
build_py_dir = build_dir / 'py'

views_dir = src_py_dir / 'hat/gui/server/views'
json_schema_repo_path = src_py_dir / 'hat/gui/json_schema_repo.json'


def task_clean_all():
    """Clean all"""
    return {'actions': [(common.rm_rf, [build_dir,
                                        views_dir,
                                        json_schema_repo_path])]}


def task_node_modules():
    """Install node_modules"""
    return {'actions': ['npm install --silent --progress false']}


def task_build():
    """Build"""
    return get_task_build_wheel(src_dir=src_py_dir,
                                build_dir=build_py_dir,
                                task_dep=['views',
                                          'json_schema_repo'])


def task_check():
    """Check with flake8"""
    return {'actions': [(run_flake8, [src_py_dir]),
                        (run_flake8, [pytest_dir]),
                        (run_eslint, [src_js_dir, ESLintConf.TS])],
            'task_dep': ['node_modules']}


def task_test():
    """Test"""
    return get_task_run_pytest(task_dep=['json_schema_repo'])


def task_docs():
    """Docs"""

    def build():
        build_sphinx(src_dir=docs_dir,
                     dst_dir=build_docs_dir,
                     project='hat-gui',
                     extensions=['sphinx.ext.graphviz',
                                 'sphinxcontrib.plantuml',
                                 'sphinxcontrib.programoutput'])
        build_pdoc(module='hat.gui',
                   dst_dir=build_docs_dir / 'py_api')

    return {'actions': [build],
            'task_dep': ['json_schema_repo']}


def task_json_schema_repo():
    """Generate JSON Schema Repository"""
    return common.get_task_json_schema_repo(schemas_json_dir.rglob('*.yaml'),
                                            json_schema_repo_path)
