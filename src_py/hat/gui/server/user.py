from collections.abc import Iterable
import hashlib
import typing

from hat import json


class AuthenticationError(Exception):
    """Authentication error"""


class User(typing.NamedTuple):
    name: str
    roles: set[str]
    view: str | None


class UserManager:

    def __init__(self, user_confs: Iterable[json.Data]):
        self._users = {}
        self._password_confs = {}

        for user_conf in user_confs:
            user = User(name=user_conf['name'],
                        roles=set(user_conf['roles']),
                        view=user_conf['view'])

            self._users[user.name] = user
            self._password_confs[user.name] = user_conf['password']

    def authenticate(self,
                     name: str,
                     password: str
                     ) -> User:
        """Authenticate user"""
        password_conf = self._password_confs.get(name)
        if not password_conf:
            raise AuthenticationError("invalid name")

        password_hash = hashlib.sha256(password.encode('utf-8')).digest()

        conf_salt = bytes.fromhex(password_conf['salt'])
        conf_hash = bytes.fromhex(password_conf['hash'])

        h = hashlib.sha256()
        h.update(conf_salt)
        h.update(password_hash)

        if h.digest() != conf_hash:
            raise AuthenticationError("invalid password")

        return self._users[name]
