from hat.gui.common import *  # NOQA

import abc
import typing

from hat import aio

from hat.gui.common import User


UserSessionId: typing.TypeAlias = str

Timestamp: typing.TypeAlias = float


class UserSession(aio.Resource):

    @property
    @abc.abstractmethod
    def user(self) -> User:
        pass

    @property
    @abc.abstractmethod
    def session_id(self) -> UserSessionId:
        pass

    @property
    @abc.abstractmethod
    def created(self) -> Timestamp:
        pass

    @property
    @abc.abstractmethod
    def updated(self) -> Timestamp:
        pass

    @abc.abstractmethod
    def update(self):
        pass
