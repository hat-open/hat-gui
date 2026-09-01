import pytest

import hat.gui.server.view


async def test_empty_view_manager():
    manager = hat.gui.server.view.ViewManager([])

    assert manager.is_open

    view_names = manager.get_views({'nonexistent'})
    assert view_names == set()

    with pytest.raises(Exception):
        manager.get_view_paths('nonexistent')

    await manager.async_close()

    assert manager.is_closed


async def test_get_views(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'paths': [{'path': str(tmp_path / 'abc')}]},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'paths': [{'path': str(tmp_path / 'def')}]},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'paths': [{'builtin': 'login'}]}]

    manager = hat.gui.server.view.ViewManager(view_confs)

    view_names = manager.get_views({'admin'})
    assert view_names == {'def'}

    view_names = manager.get_views({'operator'})
    assert view_names == {'abc', 'def'}

    view_names = manager.get_views({'operator', 'admin'})
    assert view_names == {'abc', 'def'}

    view_names = manager.get_views({'guest'})
    assert view_names == {'ghi'}

    view_names = manager.get_views({'nonexistent'})
    assert view_names == set()

    await manager.async_close()


async def test_get_view_paths(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'paths': [{'path': str(tmp_path / 'abc_1')},
                             {'path': str(tmp_path / 'abc_2')}]},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'paths': [{'path': str(tmp_path / 'def')}]},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'paths': [{'builtin': 'login'}]}]

    manager = hat.gui.server.view.ViewManager(view_confs)

    view_paths = manager.get_view_paths('abc')
    assert list(view_paths) == [tmp_path / 'abc_1', tmp_path / 'abc_2']

    view_paths = manager.get_view_paths('def')
    assert list(view_paths) == [tmp_path / 'def']

    view_paths = manager.get_view_paths('ghi')
    assert view_paths is not None

    with pytest.raises(Exception):
        manager.get_view_paths('nonexistent')

    await manager.async_close()
