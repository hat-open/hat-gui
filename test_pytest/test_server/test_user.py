import pytest

import hat.gui.server.user
import hat.gui.passwd


def test_authenticate():
    conf = {'name': 'user',
            'password': hat.gui.passwd.generate('pass'),
            'roles': ['a', 'b'],
            'view': 'view1'}

    manager = hat.gui.server.user.UserManager([conf])

    user = manager.authenticate('user', 'pass')

    assert user.name == 'user'
    assert user.roles == {'a', 'b'}
    assert user.view == 'view1'


def test_authenticate_invalid_name():
    conf = {'name': 'user',
            'password': hat.gui.passwd.generate('pass'),
            'roles': [],
            'view': None}

    manager = hat.gui.server.user.UserManager([conf])

    with pytest.raises(hat.gui.server.user.AuthenticationError):
        manager.authenticate('not user', 'pass')


def test_authenticate_invalid_password():
    conf = {'name': 'user',
            'password': hat.gui.passwd.generate('pass'),
            'roles': [],
            'view': None}

    manager = hat.gui.server.user.UserManager([conf])

    with pytest.raises(hat.gui.server.user.AuthenticationError):
        manager.authenticate('user', 'not pass')
