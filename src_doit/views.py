from pathlib import Path
import functools
import subprocess
import tempfile

from hat.doit import common


__all__ = ['task_views',
           'task_views_login']


src_py_dir = Path('src_py')
src_js_dir = Path('src_js')
src_static_dir = Path('src_static')
node_modules_dir = Path('node_modules')


def task_views():
    """Build views"""
    return {'actions': None,
            'task_dep': ['views_login']}


def task_views_login():
    """Build login view"""
    return _get_task_view('login')


def _get_task_view(name):
    src_path = src_js_dir / f'views/{name}/main.js'
    dst_dir = src_py_dir / f'hat/gui/views/{name}'
    static_dir = src_static_dir / f'views/{name}'
    action = functools.partial(_build_view, src_path, dst_dir, static_dir)
    return {'actions': [action],
            'pos_arg': 'args',
            'task_dep': ['deps']}


def _build_view(src_path, dst_dir, static_dir, args):
    args = args or []
    common.rm_rf(dst_dir)
    common.cp_r(static_dir, dst_dir)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        config_path = tmpdir / 'webpack.config.js'
        config_path.write_text(_webpack_conf.format(
            src_path=src_path.resolve(),
            dst_dir=dst_dir.resolve()))
        subprocess.run([str(node_modules_dir / '.bin/webpack'),
                        '--config', str(config_path),
                        *args],
                       check=True)


_webpack_conf = r"""
module.exports = {{
    mode: 'none',
    entry: '{src_path}',
    output: {{
        libraryTarget: 'commonjs',
        filename: 'index.js',
        path: '{dst_dir}'
    }},
    module: {{
        rules: [
            {{
                test: /\.scss$/,
                use: [
                    "style-loader",
                    {{
                        loader: "css-loader",
                        options: {{url: false}}
                    }},
                    {{
                        loader: "sass-loader",
                        options: {{sourceMap: true}}
                    }}
                ]
            }}
        ]
    }},
    watchOptions: {{
        ignored: /node_modules/
    }},
    devtool: 'eval-source-map',
    stats: 'errors-only'
}};
"""
