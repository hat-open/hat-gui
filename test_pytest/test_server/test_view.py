import pytest

import hat.gui.server.view


async def test_empty_view_manager():
    manager = hat.gui.server.view.ViewManager([])

    assert manager.is_open

    view_name = manager.get_view({'nonexistent'})
    assert view_name is None

    with pytest.raises(Exception):
        manager.get_view_paths('nonexistent')

    await manager.async_close()

    assert manager.is_closed


async def test_get_view(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'paths': [{'path': str(tmp_path / 'abc.js')}]},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'paths': [{'path': str(tmp_path / 'def.js')}]},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'paths': [{'builtin': 'login'}]}]

    manager = hat.gui.server.view.ViewManager(view_confs)

    view_name = manager.get_view({'admin'})
    assert view_name == 'def'

    view_name = manager.get_view({'operator'})
    assert view_name == 'abc'

    view_name = manager.get_view({'operator', 'admin'})
    assert view_name == 'abc'

    view_name = manager.get_view({'guest'})
    assert view_name == 'ghi'

    view_name = manager.get_view({'nonexistent'})
    assert view_name is None

    await manager.async_close()


async def test_get_view_paths(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'paths': [{'path': str(tmp_path / 'abc.js')}]},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'paths': [{'path': str(tmp_path / 'def.js')}]},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'paths': [{'builtin': 'login'}]}]

    manager = hat.gui.server.view.ViewManager(view_confs)

    view_paths = manager.get_view_paths('abc')
    assert list(view_paths) == [tmp_path / 'abc.js']

    view_paths = manager.get_view_paths('def')
    assert list(view_paths) == [tmp_path / 'def.js']

    view_paths = manager.get_view_paths('ghi')
    assert view_paths is not None

    with pytest.raises(Exception):
        manager.get_view_paths('nonexistent')

    await manager.async_close()
