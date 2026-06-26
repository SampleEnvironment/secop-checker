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

import re
from typing import TYPE_CHECKING, Any, TypeVar, cast

from . import Severity
from .context import ConstantValue
from .context import Property as CtxProperty
from .dataty import Dataty
from .schema import (
    Command,
    Feature,
    Interface,
    Module,
    Parameter,
    ParameterPostfix,
    SECNode,
)

if TYPE_CHECKING:
    IFT = TypeVar('IFT', Interface, Feature)
    from .checker import Checker


def is_command(desc: dict) -> bool:
    datainfo = desc.get('datainfo', {})
    return datainfo.get('type') == 'command'

desc_dict = dict[str, Any]


# ruff: noqa: ARG002

class BaseVisitor:
    checker: Checker
    name = ''

    def __init__(self, checker: Checker) -> None:
        self.checker = checker
        self.inv = checker.get_inv()

    def visit_property(self, nodekind: str, name: str,
                       description: desc_dict) -> None:
        """Visiting properties of any node."""

    def visit_secnode(self, description: desc_dict) -> None:
        """Visiting the root SECNode element."""

    def visit_module(self, name: str, description: desc_dict) -> None:
        """Visiting each module of a SECnode."""

    def visit_parameter(self, modname: str, name: str,
                        description: desc_dict) -> None:
        """Visiting each accessible of a module."""

    def visit_command(self, modname: str, name: str,
                      description: desc_dict) -> None:
        """Visiting each accessible of a module."""

    def finish_accessible(self, description: desc_dict) -> None:
        """Is called after all subelements of an accessible."""

    def finish_module(self, name: str) -> None:
        """Is called after all subelements of a module."""

    def finish(self) -> None:
        """Is called after all elements are processed."""


class BasicStructureChecker(BaseVisitor):
    """Checks for basic structure of the descriptive data.

    It should fail with CATASTROPHIC errors because further checkers probably
    will raise a lot of KeyErrors.
    """

    name = 'structure'

    def visit_secnode(self, description: desc_dict) -> None:
        if 'modules' not in description:
            self.checker.emit(Severity.ERROR, 'missing dict of modules')
            description['modules'] = {}

    def visit_module(self, name: str, description: desc_dict) -> None:
        if 'accessibles' not in description:
            self.checker.emit(Severity.ERROR,
                              'missing dict of module accessibles')
            description['accessibles'] = {}


class NameChecker(BaseVisitor):
    """Checks that names conform to the required format."""

    name = 'names'

    _mod = re.compile(r'^[a-zA-Z]\w{0,62}$')
    _ident = re.compile(r'^[_a-zA-Z]\w{0,62}$')

    def visit_module(self, name: str, description: desc_dict) -> None:
        if not self._mod.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required module name format')

    def visit_parameter(self, modname: str, name: str,
                        description: desc_dict) -> None:
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required parameter name format')

    def visit_command(self, modname: str, name: str,
                      description: desc_dict) -> None:
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required command name format')

    def visit_property(self, nodekind: str, name: str,
                       description: desc_dict) -> None:
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required property name format')


class InterfaceChecker(BaseVisitor):
    """Checks that all declared interfaces exist.

    Also populates the allowed parameters, commands and properties for modules
    and parameters/commands from all declared interfaces and features.

    TODO: systems
    """

    name = 'interface'

    def visit_module(self, name: str, description: desc_dict) -> None:
        self.checker.add_parameters(name, self.inv.get_global(Parameter))
        self.checker.add_commands(name, self.inv.get_global(Command))
        self.checker.add_mod_properties(name, self.inv.get_global_props(Module))

        for acc, accdesc in description['accessibles'].items():
            if is_command(accdesc):
                self.checker.add_acc_properties(
                    name, acc, self.inv.get_global_props(Command))
            else:
                self.checker.add_acc_properties(
                    name, acc, self.inv.get_global_props(Parameter))

        def add_baseclass(kind: type[IFT], clsname: str) -> None:
            if clsname.startswith('_'):
                return

            if not self.inv.is_global(kind, clsname):
                self.checker.emit(Severity.ERROR,
                                  f'declares unknown {kind.__name__}: {clsname!r}')
                return

            clsdef = cast('IFT', self.inv.get(kind, clsname))
            self.checker.add_parameters(name, clsdef.parameters,
                                        kind.__name__ + ' ' + clsname)
            self.checker.add_commands(name, clsdef.commands,
                                      kind.__name__ + ' ' + clsname)
            self.checker.add_mod_properties(name, clsdef.properties,
                                            kind.__name__ + ' ' + clsname)

            for par in clsdef.parameters:
                self.checker.add_acc_properties(name, par.name, par.properties)
            for cmd in clsdef.commands:
                self.checker.add_acc_properties(name, cmd.name, cmd.properties)
            if isinstance(kind, type(Interface)):
                clsdef = cast('Interface', clsdef)
                if clsdef.base is not None:
                    add_baseclass(Interface, clsdef.base.name)

        for iface in description.get('interface_classes', []):
            add_baseclass(Interface, iface)
        for feat in description.get('features', []):
            add_baseclass(Feature, feat)


class BasePropsChecker(BaseVisitor):
    name = 'properties-basic'

    def check_props(self, description: desc_dict, props: dict,
                    skip: str | None = None) -> None:
        required = {prop for prop, (propspec, _) in props.items()
                    if not propspec.optional}
        for member, mvalue in description.items():
            if member == skip:
                continue
            required.discard(member)
            with self.checker.with_context(CtxProperty(member)):
                if member not in props:
                    if not member.startswith('_'):
                        self.checker.emit(
                            Severity.WARNING,
                            "non-standard properties need '_' as a prefix",
                        )
                else:
                    self.checker.check_dataty(props[member][0].dataty, mvalue)
                    if props[member][0].forced_value is not None and \
                       mvalue != props[member][0].forced_value:
                        self.checker.emit(
                            Severity.ERROR,
                            f'property has forced value '
                            f'{props[member][0].forced_value!r}, got {mvalue!r}')

        if required:
            self.checker.emit(
                Severity.ERROR,
                'missing required properties: '
                f"{', '.join(map(repr, required))}")

    def visit_secnode(self, description: desc_dict) -> None:
        self.check_props(description,
                         {par.name: (par, None) for par in
                          self.inv.get_global_props(SECNode)},
                         'modules')

    def visit_module(self, name: str, description: desc_dict) -> None:
        self.check_props(description,
                         self.checker.get_mod_properties(name),
                         'accessibles')

    def visit_parameter(self, modname: str, name: str,
                        description: desc_dict) -> None:
        self.check_props(description,
                         self.checker.get_acc_properties(modname, name))

    def visit_command(self, modname: str, name: str,
                      description: desc_dict) -> None:
        self.check_props(description,
                         self.checker.get_acc_properties(modname, name))


class AccessibleChecker(BaseVisitor):
    """Check accessibles.

    Checks that modules have all accessibles required by their interfaces/
    features and that accessibles match the spec.
    """

    name = 'accessibles'
    _current_moddesc: desc_dict | None = None

    def visit_module(self, name: str, description: desc_dict) -> None:
        self._current_moddesc = description
        for pname, (parspec, from_) in self.checker.get_parameters(name).items():
            if from_ and not parspec.optional and \
               pname not in description['accessibles']:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required parameter {pname} from {from_}',
                )
        for cname, (cmdspec, from_) in self.checker.get_commands(name).items():
            if from_ and not cmdspec.optional and \
               cname not in description['accessibles']:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required command {cname} from {from_}',
                )

    def _get_value_datainfo(self) -> desc_dict | None:
        if self._current_moddesc:
            value_acc = self._current_moddesc.get('accessibles', {}).get('value')
            if value_acc is not None:
                return value_acc.get('datainfo')
        return None

    def check_datainfo_template(self,
                                should: str | desc_dict,
                                actual: desc_dict,
                                parent: str | desc_dict | None) -> None:
        """Check if a prescribed datainfo matches the actual datainfo.

        Does not check the datainfo itself for validity, this was done in
        BasePropsChecker.

        `parent` is the datainfo of the parameter that this one is derived
        from, if any. It is used to check for the special "parent" type.
        """
        if should == 'any':
            return
        if should in ['parent', {'type': 'parent'}] and parent is not None:
            should = parent
        if isinstance(should, str):
            should = {'type': should}

        # check type first, then other keys
        if 'type' in should:
            kval = should['type']
            aval = actual.get('type')
            if aval is None:
                self.checker.emit(Severity.ERROR,
                                  "missing required datainfo key 'type'")
                return

            # handle special cases
            if kval == 'any' or \
               (kval == 'number' and aval in ('double', 'scaled', 'int')) or \
               (kval == 'double' and aval == 'scaled'):
                aval = kval

            if kval != aval:
                self.checker.emit(Severity.ERROR,
                                  f'expected datainfo type {kval!r}, '
                                  f'got {aval!r}')
                return

        for key, kval in should.items():
            if key == 'type':
                continue
            aval = actual.get(key)
            if aval is None:
                self.checker.emit(Severity.ERROR,
                                  f'missing required datainfo key {key!r}')
                continue
            if should['type'] == 'array' and key == 'members':
                self.check_datainfo_template(kval, aval, parent)
            elif should['type'] == 'tuple' and key == 'members':
                for _i, (kval_item, aval_item) in \
                        enumerate(zip(kval, aval, strict=False)):
                    self.check_datainfo_template(kval_item, aval_item, parent)
            elif should['type'] == 'struct' and key == 'members':
                for kval_key, kval_item in kval.items():
                    if kval_key not in aval:
                        self.checker.emit(Severity.ERROR,
                                          f'missing struct member {kval_key}')
                    else:
                        self.check_datainfo_template(kval_item,
                                                     aval[kval_key],
                                                     parent)
            else:  # noqa: PLR5501
                if kval != aval:
                    self.checker.emit(Severity.ERROR,
                                      f'expected datainfo {key} {kval!r}, '
                                      f'got {aval!r}')

    def visit_parameter(self, modname: str, name: str,
                        description: desc_dict) -> None:
        should_src = self.checker.get_parameters(modname).get(name)
        if should_src is None:
            # it might be a postfixed parameter!
            for postfix, pf_defs in self.inv.get_all(ParameterPostfix).items():
                if name.endswith(postfix):
                    should = Parameter.from_postfix(name, pf_defs[0])

                    base_name = name[:-len(postfix)]
                    parent_datainfo = None
                    base_acc = self._current_moddesc.get(
                        'accessibles', {}).get(base_name) \
                        if self._current_moddesc else None
                    if base_acc is not None:
                        parent_datainfo = base_acc.get('datainfo')
                    else:
                        self.checker.emit(
                            Severity.ERROR,
                            f'postfixed parameter {name!r} requires '
                            f'non-postfixed parameter {base_name!r}',
                        )
                    break
            else:
                if not name.startswith('_'):
                    self.checker.emit(
                        Severity.WARNING,
                        "non-standard parameters need '_' as a prefix",
                    )
                return
        else:
            should = should_src[0]
            parent_datainfo = self._get_value_datainfo()

        # special case: check "constant" parameter value
        if 'constant' in description:
            if not description.get('readonly'):
                self.checker.emit(Severity.WARNING,
                                  'constant parameters should be readonly')
            with self.checker.with_context(ConstantValue()):
                try:
                    ty = Dataty.from_desc(description['datainfo'])
                except ValueError:
                    pass  # datainfo field has been checked elsewhere
                else:
                    self.checker.check_dataty(ty, description['constant'])

        if description['readonly'] != should.readonly:
            if should.readonly:
                self.checker.emit(Severity.WARNING,
                                  'parameter should be readonly')
            else:
                self.checker.emit(Severity.WARNING,
                                  'parameter should not be readonly')
        self.check_datainfo_template(should.datainfo, description['datainfo'],
                                     parent_datainfo)

    def visit_command(self, modname: str, name: str, description: desc_dict) -> None:
        should_src = self.checker.get_commands(modname).get(name)
        if should_src is None:
            if not name.startswith('_'):
                self.checker.emit(
                    Severity.WARNING,
                    "non-standard commands need '_' as a prefix",
                )
            return
        should = should_src[0]
        parent_datainfo = self._get_value_datainfo()

        if 'argument' in description['datainfo']:
            if should.argument == {'type': 'none'}:
                self.checker.emit(Severity.WARNING,
                                  'command should not have an argument')
            else:
                self.check_datainfo_template(
                    should.argument, description['datainfo']['argument'],
                    parent_datainfo)
        elif should.argument != {'type': 'none'}:
            self.checker.emit(Severity.WARNING,
                              'command should have an argument: '
                              f'{should.argument}')

        if 'result' in description['datainfo']:
            if should.result == {'type': 'none'}:
                self.checker.emit(Severity.WARNING,
                                  'command should not have a result')
            else:
                self.check_datainfo_template(
                    should.result, description['datainfo']['result'],
                    parent_datainfo)
        elif should.result != {'type': 'none'}:
            self.checker.emit(Severity.WARNING,
                              'command should have a result: '
                              f'{should.result}')


VISITORS = [
    BasicStructureChecker,
    NameChecker,
    InterfaceChecker,
    BasePropsChecker,
    AccessibleChecker,
]
