import base64

import pytest

from hat import json

import hat.gui.server.view


async def test_empty_view_manager():
    manager = hat.gui.server.view.ViewManager([])

    assert manager.is_open

    with pytest.raises(Exception):
        await manager.get('abc')

    await manager.async_close()


@pytest.mark.parametrize('files, data', [
    ({},
     {}),

    ({'a/b/c.txt': 'abc',
      'x.js': 'x',
      'y.css': 'y'},
     {'a/b/c.txt': 'abc',
      'x.js': 'x',
      'y.css': 'y'}),

    ({'a.json': '[1, true, null, {}]'},
     {'a.json': [1, True, None, {}]}),

    ({'test1.yaml': '1',
      'test2.yml': '2'},
     {'test1.yaml': 1,
      'test2.yml': 2}),

    ({'a.xml': '<a>123</a>',
      'b.svg': '<b1><b2>123</b2></b1>'},
     {'a.xml': ['a', '123'],
      'b.svg': ['b1', ['b2', '123']]}),

    ({'a.bin': '123'},
     {'a.bin': base64.b64encode(b'123').decode('utf-8')}),
])
async def test_view_data(tmp_path, files, data):
    name = 'name'
    view_confs = [{'name': name,
                   'view_path': str(tmp_path),
                   'conf': 123}]
    manager = hat.gui.server.view.ViewManager(view_confs)

    view = await manager.get(name)
    assert view.name == name
    assert view.conf == 123
    assert view.data == {}

    for file_name, file_content in files.items():
        path = tmp_path / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(file_content)

    view = await manager.get(name)
    assert view.name == name
    assert view.conf == 123
    assert view.data == data

    await manager.async_close()

    with pytest.raises(Exception):
        await manager.get(name)


async def test_invalid_view_path():
    name = 'name'
    view_confs = [{'name': name,
                   'view_path': None,
                   'conf': None}]
    manager = hat.gui.server.view.ViewManager(view_confs)

    with pytest.raises(Exception):
        await manager.get(name)

    await manager.async_close()


async def test_validate_conf(tmp_path):
    name = 'name'
    conf_path = tmp_path / 'conf.json'
    schema_path = tmp_path / 'schema.json'
    view_confs = [{'name': name,
                   'view_path': str(tmp_path),
                   'conf_path': str(conf_path)}]
    manager = hat.gui.server.view.ViewManager(view_confs)

    with pytest.raises(Exception):
        await manager.get(name)

    schema = {'id': 'test://schema',
              'type': 'object',
              'required': ['abc']}
    json.encode_file(schema, schema_path)

    with pytest.raises(Exception):
        await manager.get(name)

    data = {'cba': 123}
    json.encode_file(data, conf_path)

    with pytest.raises(Exception):
        await manager.get(name)

    data = {'abc': 321}
    json.encode_file(data, conf_path)

    view = await manager.get(name)
    assert view.name == name
    assert view.conf == data
    assert view.data == {conf_path.name: data,
                         schema_path.name: schema}

    await manager.async_close()


async def test_builtin_view():
    name = 'name'
    view_confs = [{'name': name,
                   'builtin': 'login',
                   'conf': None}]
    manager = hat.gui.server.view.ViewManager(view_confs)

    view = await manager.get(name)
    assert view.name == name
    assert view.conf is None

    await manager.async_close()
