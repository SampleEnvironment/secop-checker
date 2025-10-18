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

import json
from pathlib import Path

from . import DiagnosticBase, Severity
from .schema import Loader
from .visitors import VISITORS


class Checker(DiagnosticBase):
    def __init__(self, version, additional, output):
        super().__init__(output)

        self.loader = Loader(Path(__file__).parents[1] / 'defs', output)
        self.loader._diags = self._diags
        self.loader.load(version, additional)

        self._inv = self.loader.get_inv()

        # schema of params/commands by module, combined from interfaces,
        # features and systems
        self._all_pars = {}
        self._all_cmds = {}
        # combined schema of properties by module
        self._all_modprops = {}
        # combined schema of properties by (module, accessible)
        self._all_accprops = {}

    def get_diags(self):
        return self._diags

    def check(self, desc: str):
        # for simplicity, allow a "describing" SECoP reply
        if desc.startswith('describing . '):
            desc = desc[len('describing . '):]
        try:
            desc = json.loads(desc)
        except json.JSONDecodeError as e:
            self.emit(Severity.CATASTROPHIC, f'invalid json at line {e.lineno}'
                      f' column {e.colno}:\n{e.msg}')

        schemata = desc.get('schemata', {})
        for uri in schemata:
            self.loader.load_repo(uri)

        if self._diags:
            self.emit(Severity.CATASTROPHIC, 'found errors loading spec to '
                      'validate against, exiting')

        self.visit_descriptive_data(desc)

    def add_parameters(self, name, params, source=None):
        self._all_pars.setdefault(name, {}).update(
            {par.name: (par, source) for par in params}
        )

    def add_commands(self, name, cmds, source=None):
        self._all_cmds.setdefault(name, {}).update(
            {cmd.name: (cmd, source) for cmd in cmds}
        )

    def add_mod_properties(self, name, props, source=None):
        self._all_modprops.setdefault(name, {}).update(
            {prop.name: (prop, source) for prop in props}
        )

    def add_acc_properties(self, name, acc, props, source=None):
        self._all_accprops.setdefault((name, acc), {}).update(
            {prop.name: (prop, source) for prop in props}
        )

    def get_parameters(self, name):
        return self._all_pars.get(name, {})

    def get_commands(self, name):
        return self._all_cmds.get(name, {})

    def get_mod_properties(self, name):
        return self._all_modprops.get(name, {})

    def get_acc_properties(self, name, acc):
        return self._all_accprops.get((name, acc), {})

    def check_dataty(self, description, actual, quiet=False):
        matches = False
        expected = description
        if description == 'any':
            matches = True
        elif description == 'number':
            matches = isinstance(actual, (int, float))
        elif description == 'double':
            matches = isinstance(actual, float)
        elif description == 'int':
            matches = isinstance(actual, int) or \
                (isinstance(actual, float) and actual.is_integer())
        elif description == 'string':
            matches = isinstance(actual, str)
        elif description == 'bool':
            matches = isinstance(actual, bool)
        elif description in ('array', 'tuple'):  # without further details
            matches = isinstance(actual, list)
        elif description == 'struct':            # without further details
            matches = isinstance(actual, dict)
        elif description == 'datainfo':
            self.check_datainfo(actual)
            matches = True  # check_datainfo will emit errors
        elif isinstance(description, dict) and description['type'] == 'int':
            mini = description.get('min', -float('inf'))
            maxi = description.get('max', float('inf'))
            expected = f'int in [{mini}, {maxi}]'
            matches = (isinstance(actual, int) or
                       (isinstance(actual, float) and
                        actual.is_integer())) and mini <= actual <= maxi
        elif isinstance(description, dict) and description['type'] == 'oneof':
            expected = f'any of {", ".join(description["values"])}'
            matches = isinstance(actual, str) and \
                any(actual == v for v in description['values'])
        elif isinstance(description, dict) and description['type'] == 'array':
            # TODO: the expected description sucks
            expected = f'array of {description["members"]}'
            matches = isinstance(actual, list) and \
                all(self.check_dataty(description['members'], v, quiet=True)
                    for v in actual)
        elif isinstance(description, dict) and description['type'] == 'tuple':
            expected = 'array of ' + ', '.join(map(str, description['members']))
            matches = isinstance(actual, list) and \
                len(actual) == len(description['members']) and \
                all(self.check_dataty(desc, v, quiet=True)
                    for desc, v in zip(description['members'], actual))
        elif isinstance(description, dict) and description['type'] == 'struct':
            if isinstance(description['members'], str):
                expected = ('struct with str names and '
                            f'{description["members"]} values')
                matches = isinstance(actual, dict) and \
                    all(isinstance(k, str) for k in actual) and \
                    all(self.check_dataty(description['members'],
                                          v, quiet=True)
                        for v in actual.values())
            else:
                expected = 'struct with ' + ', '.join(
                    f'{k}: {v}' for k, v in description['members'].items())
                optional = description.get('optional', [])
                matches = isinstance(actual, dict) and \
                    all((k not in actual and k in optional) or
                        (k in actual and
                         self.check_dataty(description['members'][k],
                                           actual[k], quiet=True))
                        for k in description['members'])
        else:
            self.emit(Severity.CATASTROPHIC, 'unknown dataty given in spec: '
                      f'{description}')

        if not matches and not quiet:
            self.emit(Severity.ERROR,
                      f'expected {expected}, got {actual!r}')
        return matches

    def check_datainfo(self, description):
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

        basic = self._inv.get('Datainfo', descty)
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

    def visit_descriptive_data(self, desc):
        for visitorcls in VISITORS:
            self._step = visitorcls.name
            self.visit_with(desc, visitorcls(self))

    def visit_with(self, desc, visitor):
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

    def _visit_module(self, modname, moddesc, visitor):
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

                        for prop, propdesc in accdesc.items():
                            with self.with_context('Property', prop):
                                visitor.visit_property(ty, prop, propdesc)

                        visitor.finish_accessible(accdesc)

            # other module properties
            else:
                with self.with_context('Property', prop):
                    visitor.visit_property('Module', prop, propdesc)

            visitor.finish_module(modname)
