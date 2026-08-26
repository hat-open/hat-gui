import hat.gui.server.view


async def test_empty_view_manager():
    manager = hat.gui.server.view.ViewManager([])

    assert manager.is_open

    view_name = manager.get_view({'nonexistent'})
    assert view_name is None

    view_path = manager.get_view_path('nonexistent')
    assert view_path is None

    await manager.async_close()

    assert manager.is_closed


async def test_get_view(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'view_path': str(tmp_path / 'abc.js')},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'view_path': str(tmp_path / 'def.js')},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'builtin': 'login'}]

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


async def test_get_view_path(tmp_path):
    view_confs = [{'name': 'abc',
                   'roles': ['operator'],
                   'view_path': str(tmp_path / 'abc.js')},
                  {'name': 'def',
                   'roles': ['operator', 'admin'],
                   'view_path': str(tmp_path / 'def.js')},
                  {'name': 'ghi',
                   'roles': ['guest'],
                   'builtin': 'login'}]

    manager = hat.gui.server.view.ViewManager(view_confs)

    view_path = manager.get_view_path('abc')
    assert view_path == tmp_path / 'abc.js'

    view_path = manager.get_view_path('def')
    assert view_path == tmp_path / 'def.js'

    view_path = manager.get_view_path('ghi')
    assert view_path is not None

    view_path = manager.get_view_path('nonexistent')
    assert view_path is None

    await manager.async_close()
