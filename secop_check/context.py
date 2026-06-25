# *****************************************************************************
# Copyright (c) 2024-2025 by the authors, see LICENSE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Module authors:
#   Alexander Zaft <a.zaft@fz-juelich.de>
#   Georg Brandl <g.brandl@fz-juelich.de>
#
# *****************************************************************************

"""Context items for the diagnostic path."""


class ContextItem:
    """A single context element in the context path."""

    def __init__(self, name: str = '') -> None:
        self.name = name

    def __str__(self) -> str:
        return f'{type(self).__name__} {self.name}'.strip()

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.name!r})'


class SECNode(ContextItem):
    pass


class Module(ContextItem):
    pass


class Property(ContextItem):
    pass


class Parameter(ContextItem):
    pass


class Command(ContextItem):
    pass


class ConstantValue(ContextItem):
    def __str__(self) -> str:
        return f'constant value {self.name}'.strip()


class Argument(ContextItem):
    def __str__(self) -> str:
        return f'argument {self.name}'.strip()


class Result(ContextItem):
    def __str__(self) -> str:
        return f'result {self.name}'.strip()


class Datainfo(ContextItem):
    def __init__(self, desctype: str, prop: str) -> None:
        super().__init__(prop)
        self.desctype = desctype

    def __str__(self) -> str:
        return f'datainfo {self.desctype} {self.name}'


class File(ContextItem):
    pass


class Generic(ContextItem):
    def __init__(self, kind: str, name: str) -> None:
        super().__init__(name)
        self.kind = kind

    def __str__(self) -> str:
        return f'{self.kind} {self.name}'
