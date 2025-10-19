# *****************************************************************************
# Copyright (c) 2024-2024 by the authors, see LICENSE
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

import json
from pathlib import Path
from typing import Any, Union

from . import DiagnosticBase, Severity
from .schema import Command, Datainfo, Inventory, Loader, Parameter, Property
from .visitors import VISITORS, BaseVisitor

desc_dict = dict[str, Any]
source = Union[str, None]


class Checker(DiagnosticBase):
    def __init__(self, version: str, additional: list[str], output: str) -> None:
        super().__init__(output)

        self.loader = Loader(Path(__file__).parents[1] / 'defs', output)
        self.loader.set_diags(self._diags)
        self.loader.load(version, additional)

        self._inv = self.loader.get_inv()

        # schema of params/commands by module, combined from interfaces,
        # features and systems
        self._all_pars: dict[str, dict] = {}
        self._all_cmds: dict[str, dict] = {}
        # combined schema of properties by module
        self._all_modprops: dict[str, dict] = {}
        # combined schema of properties by (module, accessible)
        self._all_accprops: dict[tuple[str, str], dict] = {}

    def get_inv(self) -> Inventory:
        return self._inv

    def check(self, desc: str) -> None:
        # for simplicity, allow a "describing" SECoP reply
        desc = desc.removeprefix('describing . ')
        try:
            desc_obj = json.loads(desc)
        except json.JSONDecodeError as e:
            self.emit_catastrophic(f'invalid json at line {e.lineno} '
                                   f'column {e.colno}:\n{e.msg}')

        schemata = desc_obj.get('schemata', {})
        for uri in schemata:
            self.loader.load_repo(uri)

        if self._diags:
            self.emit_catastrophic('found errors loading spec to '
                                   'validate against, exiting')

        self.visit_descriptive_data(desc_obj)

    def add_parameters(self, name: str, params: list[Parameter],
                       source: str | None = None) -> None:
        self._all_pars.setdefault(name, {}).update(
            {par.name: (par, source) for par in params},
        )

    def add_commands(self, name: str, cmds: list[Command],
                     source: str | None = None) -> None:
        self._all_cmds.setdefault(name, {}).update(
            {cmd.name: (cmd, source) for cmd in cmds},
        )

    def add_mod_properties(self, name: str, props: list[Property],
                           source: str | None = None) -> None:
        self._all_modprops.setdefault(name, {}).update(
            {prop.name: (prop, source) for prop in props},
        )

    def add_acc_properties(self, name: str, acc: str, props: list[Property],
                           source: str | None = None) -> None:
        self._all_accprops.setdefault((name, acc), {}).update(
            {prop.name: (prop, source) for prop in props},
        )

    def get_parameters(self, name: str) -> dict[str, tuple[Parameter, source]]:
        return self._all_pars.get(name, {})

    def get_commands(self, name: str) -> dict[str, tuple[Command, source]]:
        return self._all_cmds.get(name, {})

    def get_mod_properties(self, name: str) -> dict[str, tuple[Property, source]]:
        return self._all_modprops.get(name, {})

    def get_acc_properties(self, name: str, acc: str,
                           ) -> dict[str, tuple[Property, source]]:
        return self._all_accprops.get((name, acc), {})

    def _fixup_dataty(self, s: str | dict) -> dict:
        if isinstance(s, str):
            return {'type': s}
        return s

    def _check_dataty_struct(self, description: dict[str, Any],
                             actual: object) -> tuple[str, bool]:
        expected = 'struct'
        members = description.get('members')
        if members is None:
            # just check for object, without further details
            matches = isinstance(actual, dict)
        elif isinstance(members, str):
            # TODO: the expected description sucks
            expected = f'struct with str names and {members} values'
            matches = isinstance(actual, dict) and \
                all(isinstance(k, str) for k in actual) and \
                all(self.check_dataty({'type': members}, v, quiet=True)
                    for v in actual.values())
        else:
            # TODO: the expected description sucks
            expected = 'struct with ' + ', '.join(
                f'{k}: {v}' for k, v in members.items())
            optional = description.get('optional', [])
            matches = isinstance(actual, dict) and \
                all((k not in actual and k in optional) or
                    (k in actual and
                     self.check_dataty(self._fixup_dataty(members[k]),
                                       actual[k], quiet=True))
                    for k in members)
        return expected, matches

    def _check_dataty_tuple(self, description: dict[str, Any],
                            actual: object) -> tuple[str, bool]:
        members = description.get('members')
        expected = 'tuple'
        if members is None:
            # just check for array, without further details
            matches = isinstance(actual, list)
        else:
            # TODO: the expected description sucks
            expected = 'array of ' + ', '.join(map(str, members))
            matches = isinstance(actual, list) and \
                len(actual) == len(members) and \
                all(self.check_dataty(self._fixup_dataty(desc), v,
                                      quiet=True)
                    for desc, v in zip(members, actual))
        return expected, matches

    def check_dataty(self, description: dict[str, Any], actual: object, *,
                     quiet: bool = False) -> bool:
        matches = False
        descty = expected = description['type']
        if descty == 'any':
            matches = True
        elif descty == 'number':
            matches = isinstance(actual, (int, float))
        elif descty == 'double':
            matches = isinstance(actual, float)
        elif descty == 'int':
            is_int = isinstance(actual, int) or \
                (isinstance(actual, float) and actual.is_integer())
            mini = description.get('min', -float('inf'))
            maxi = description.get('max', float('inf'))
            if 'min' in description or 'max' in description:
                expected = f'int in [{mini}, {maxi}]'
            matches = is_int and mini <= actual <= maxi
        elif descty == 'string':
            matches = isinstance(actual, str)
        elif descty == 'bool':
            matches = isinstance(actual, bool)
        elif descty == 'array':
            members = description.get('members')
            if members is None:
                matches = isinstance(actual, list)
            else:
                # TODO: the expected description sucks
                expected = f'array of {members}'
                matches = isinstance(actual, list) and \
                    all(self.check_dataty(self._fixup_dataty(members), v,
                                          quiet=True)
                        for v in actual)
        elif descty == 'tuple':
            expected, matches = self._check_dataty_tuple(description, actual)
        elif descty == 'struct':
            expected, matches = self._check_dataty_struct(description, actual)
        elif descty == 'datainfo':
            if isinstance(actual, dict):
                self.check_datainfo(actual)
                matches = True  # check_datainfo will emit errors
            else:
                matches = False
        elif descty == 'oneof':
            values = description['values']
            expected = f'any of {", ".join(values)}'
            matches = isinstance(actual, str) and actual in values
        else:
            self.emit_catastrophic('unknown dataty given in spec: '
                                   f'{description}')

        if not matches and not quiet:
            self.emit(Severity.ERROR,
                      f'expected {expected}, got {actual!r}')
        return matches

    def check_datainfo(self, description: desc_dict) -> None:
        """Check validity of a datainfo description."""
        if not description:
            self.emit(Severity.ERROR, 'datainfo is empty')
            return
        if 'type' not in description:
            self.emit(Severity.ERROR, 'datainfo does not have a type')
            description['type'] = 'unknown'

        descty = description['type']

        # handle commands recursively
        if descty == 'command':
            if 'argument' in description:
                with self.with_context('argument', ''):
                    self.check_datainfo(description['argument'])
            if 'result' in description:
                with self.with_context('result', ''):
                    self.check_datainfo(description['result'])
            return

        basic = self._inv.get(Datainfo, descty)
        if basic is None:
            self.emit(Severity.ERROR, f'unknown datainfo type {descty}')
            return

        actual_props = set(description) - {'type'}
        for prop, propdesc in basic.members.items():
            if prop not in actual_props:
                if not propdesc.get('optional', False):
                    self.emit(Severity.ERROR,
                              'missing required property for datainfo '
                              f'{descty}: {prop}')
            else:
                with self.with_context('datainfo ' + descty, prop):
                    self.check_dataty(propdesc['dataty'], description[prop])
            actual_props.discard(prop)

        if actual_props:
            self.emit(Severity.WARNING,
                      'unknown properties given for datainfo '
                      f'{descty}: {actual_props}')

    def visit_descriptive_data(self, desc: desc_dict) -> None:
        for visitorcls in VISITORS:
            self._step = visitorcls.name
            self.visit_with(desc, visitorcls(self))

    def visit_with(self, desc: desc_dict, visitor: BaseVisitor) -> None:
        with self.with_context('SECNode', ''):
            visitor.visit_secnode(desc)

            for prop, propdesc in desc.items():
                if prop == 'modules':
                    for module, moddesc in propdesc.items():
                        with self.with_context('Module', module):
                            self._visit_module(module, moddesc, visitor)

                # other node properties
                else:
                    with self.with_context('Property', prop):
                        visitor.visit_property('SECNode', prop, propdesc)

            visitor.finish()

    def _visit_module(self, modname: str, moddesc: desc_dict,
                      visitor: BaseVisitor) -> None:
        visitor.visit_module(modname, moddesc)

        for prop, propdesc in moddesc.items():
            if prop == 'accessibles':
                for accname, accdesc in propdesc.items():
                    datainfo = accdesc.get('datainfo', {})
                    ty = 'Command' if datainfo.get('type') == 'command' \
                        else 'Parameter'
                    with self.with_context(ty, accname):
                        if ty == 'Command':
                            visitor.visit_command(modname, accname, accdesc)
                        else:
                            visitor.visit_parameter(modname, accname, accdesc)

                        for aprop, apropdesc in accdesc.items():
                            with self.with_context('Property', aprop):
                                visitor.visit_property(ty, aprop, apropdesc)

                        visitor.finish_accessible(accdesc)

            # other module properties
            else:
                with self.with_context('Property', prop):
                    visitor.visit_property('Module', prop, propdesc)

            visitor.finish_module(modname)
