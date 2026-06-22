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

from __future__ import annotations

from abc import abstractmethod
from typing import Any

# ruff: noqa: ARG002

class Dataty:
    def __init__(self, **kwds: dict) -> None:
        self.__dict__.update(kwds)

    @staticmethod
    def from_desc(dct: str | dict[str, Any]) -> Dataty:  # noqa: PLR0911
        if isinstance(dct, str):
            dct = {'type': dct}
        type_ = dct.get('type')
        if type_ == 'any':
            return AnyType()
        if type_ == 'number':
            return Number()
        if type_ == 'double':
            return Double()
        if type_ == 'int':
            return Int(dct)
        if type_ == 'string':
            return String()
        if type_ == 'bool':
            return Bool()
        if type_ == 'datainfo':
            return Datainfo()
        if type_ == 'array':
            return Array(dct)
        if type_ == 'tuple':
            return Tuple(dct)
        if type_ == 'struct':
            return Struct(dct)
        if type_ == 'oneof':
            return OneOf(dct)
        if type_ == 'enum':
            return OneOfEnum(dct)
        if type_ == 'parent':
            return Parent()
        raise ValueError

    @abstractmethod
    def validate(self, value: object) -> bool:
        """Validate the given value."""

    @abstractmethod
    def describe(self) -> str:
        """Return a string description of this datatype."""


class AnyType(Dataty):
    def validate(self, value: object) -> bool:
        return True

    def describe(self) -> str:
        return 'any type'


class Number(Dataty):
    def validate(self, value: object) -> bool:
        return isinstance(value, (int, float))

    def describe(self) -> str:
        return 'number'


class Double(Dataty):
    def validate(self, value: object) -> bool:
        return isinstance(value, (int, float))

    def describe(self) -> str:
        return 'double'


class Int(Dataty):
    minimum = None
    maximum = None

    def __init__(self, dct: dict[str, Any]) -> None:
        self.minimum = dct.get('minimum')
        self.maximum = dct.get('maximum')

    def validate(self, value: object) -> bool:
        if not (isinstance(value, int) or
                (isinstance(value, float) and value.is_integer())):
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:  # noqa: SIM103
            return False
        return True

    def describe(self) -> str:
        desc = 'integer'
        if self.minimum is not None:
            desc += f' (>= {self.minimum})'
        if self.maximum is not None:
            desc += f' (<= {self.maximum})'
        return desc


class String(Dataty):
    def validate(self, value: object) -> bool:
        return isinstance(value, str)

    def describe(self) -> str:
        return 'string'


class Bool(Dataty):
    def validate(self, value: object) -> bool:
        return isinstance(value, bool)

    def describe(self) -> str:
        return 'bool'


class Array(Dataty):
    itemtype = None

    def __init__(self, dct: dict[str, Any]) -> None:
        if 'members' in dct:
            self.itemtype = Dataty.from_desc(dct['members'])

    def validate(self, value: object) -> bool:
        if not isinstance(value, list):
            return False
        if self.itemtype is None:
            return True
        return all(self.itemtype.validate(item) for item in value)

    def describe(self) -> str:
        if self.itemtype is None:
            return 'array'
        return f'array of {self.itemtype.describe()}'


class Tuple(Dataty):
    itemtypes = None

    def __init__(self, dct: dict[str, Any]) -> None:
        if 'members' in dct:
            self.itemtypes = [Dataty.from_desc(item) for item in dct['members']]

    def validate(self, value: object) -> bool:
        if not isinstance(value, list):
            return False
        if self.itemtypes is None:
            return True
        if len(value) != len(self.itemtypes):
            return False
        return all(itemtype.validate(item)
                   for itemtype, item in zip(self.itemtypes, value))

    def describe(self) -> str:
        if self.itemtypes is None:
            return 'tuple'
        return 'tuple of (' + ', '.join(item.describe()
                                        for item in self.itemtypes) + ')'


class Struct(Dataty):
    fieldtype = None
    fieldtypes = None
    optional: list[str]

    def __init__(self, dct: dict[str, Any]) -> None:
        if 'members' in dct:
            if isinstance(dct['members'], str):
                self.fieldtype = Dataty.from_desc(dct['members'])
            else:
                self.fieldtypes = {key: Dataty.from_desc(val)
                                   for key, val in dct['members'].items()}
        self.optional = dct.get('optional', [])

    def validate(self, value: object) -> bool:
        if not isinstance(value, dict):
            return False
        if self.fieldtype is not None:
            if not all(isinstance(k, str) for k in value):
                return False
            return all(self.fieldtype.validate(v) for v in value.values())
        if self.fieldtypes is not None:
            for key, fieldtype in self.fieldtypes.items():
                if key not in value and key not in self.optional:
                    return False
                if key not in value:
                    continue
                if not fieldtype.validate(value[key]):
                    return False
        return True

    def describe(self) -> str:
        if self.fieldtype is not None:
            return ('struct with str names and values of type: ' +
                    self.fieldtype.describe())
        if self.fieldtypes is not None:
            return 'struct with fields: ' + ', '.join(
                f'{key} ({field.describe()}, '
                f'{"optional" if key in self.optional else "required"})'
                for key, field in self.fieldtypes.items()
            )
        return 'struct'


class OneOf(Dataty):
    values: list[str]

    def __init__(self, dct: dict[str, Any]) -> None:
        self.values = [str(item) for item in dct['values']]

    def validate(self, value: object) -> bool:
        return isinstance(value, str) and value in self.values

    def describe(self) -> str:
        return 'one of: ' + ', '.join(self.values)


class OneOfEnum(Dataty):
    values: list[int]

    def __init__(self, dct: dict[str, Any]) -> None:
        self.values = [int(item) for item in dct['members'].values()]

    def validate(self, value: object) -> bool:
        return isinstance(value, int) and value in self.values

    def describe(self) -> str:
        return 'one of [' + ', '.join(map(str, self.values)) + ']'


class Datainfo(Dataty):
    def validate(self, value: object) -> bool:
        # more checks in Checker.check_datainfo
        return isinstance(value, dict)

    def describe(self) -> str:
        return 'datainfo'


class Parent(Dataty):
    def validate(self, value: object) -> bool:
        # this is a special case and needs to be checked somewhere else
        return True

    def describe(self) -> str:
        return 'type of parent element'
