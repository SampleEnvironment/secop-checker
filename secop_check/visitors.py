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
from .context import Module as CtxModule
from .context import Property as CtxProperty
from .context import System as CtxSystem
from .dataty import Dataty
from .schema import (
    Command,
    Feature,
    Interface,
    Module,
    Parameter,
    ParameterPostfix,
    SECNode,
    System,
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


class SystemChecker(BaseVisitor):
    """Checks that systems are properly defined.

    Validates system entries in the SECNode description: resolves the
    system schema reference, checks that all required modules are mapped,
    that mapped modules exist on the node, and that system names don't
    clash with module names.  Also validates that mapped modules conform
    to the interface class, parameter/command, and property requirements
    specified in the system definition.
    """

    name = 'system'

    def visit_secnode(self, description: desc_dict) -> None:
        systems = description.get('systems', {})
        if not isinstance(systems, dict):
            self.checker.emit(Severity.ERROR,
                              "'systems' must be a dict")
            return

        module_names = set(description.get('modules', {}))
        modules_desc = description.get('modules', {})
        sys_props = {prop.name: (prop, None)
                     for prop in self.inv.get_global_props(System)}

        for sysname, sysdesc in systems.items():
            with self.checker.with_context(CtxSystem(sysname)):
                self._check_one(sysname, sysdesc, module_names,
                                modules_desc, sys_props)

    def _check_one(self, sysname: str, sysdesc: object,
                   module_names: set[str],
                   modules_desc: dict[str, dict],
                   sys_props: dict[str, tuple]) -> None:
        if not isinstance(sysdesc, dict):
            self.checker.emit(Severity.ERROR,
                              'systems entry must be a dict')
            return

        desc = cast('desc_dict', sysdesc)

        # system name must not clash with module names
        if sysname in module_names:
            self.checker.emit(Severity.ERROR,
                              'system name clashes with existing module')

        # system property (reference) is required
        system_ref = desc.get('system')
        if not isinstance(system_ref, str):
            self.checker.emit(Severity.ERROR,
                              "missing required key 'system'")
            return

        # parse and resolve the system reference
        if ':' in system_ref:
            sys_name, ver_str = system_ref.rsplit(':', 1)
            try:
                sys_version = int(ver_str)
            except ValueError:
                self.checker.emit(Severity.ERROR,
                                  f'invalid version in system reference '
                                  f'{system_ref!r}')
                return
        else:
            sys_name = system_ref
            sys_version = None

        system_obj = self.inv.get(System, sys_name, sys_version)
        if system_obj is None:
            self.checker.emit(Severity.ERROR,
                              f'references unknown system {system_ref!r}')
            return

        # collect all module requirements from system and its bases
        required_modules: dict[str, Interface] = {}

        def _collect(sys_obj: System) -> None:
            for base in sys_obj.bases:
                _collect(base)
            for modname, iface in sys_obj.modules.items():
                if modname in required_modules:
                    existing = required_modules[modname]
                    iface.name = existing.name
                    iface.base = existing.base
                    if not iface.parameters:
                        iface.parameters = existing.parameters
                    if not iface.commands:
                        iface.commands = existing.commands
                    if not iface.properties:
                        iface.properties = existing.properties
                required_modules[modname] = iface

        _collect(system_obj)

        # check the modules mapping
        modules_map = desc.get('modules', {})
        if not isinstance(modules_map, dict):
            self.checker.emit(Severity.ERROR,
                              "'modules' must be a dict")
            return

        self._check_module_mappings(
            required_modules, modules_map, module_names, system_ref)

        # check module specifications against actual modules
        for modname, iface in required_modules.items():
            if modname not in modules_map:
                continue
            actual_modname = modules_map[modname]
            if not isinstance(actual_modname, str) or \
               actual_modname not in module_names:
                continue
            with self.checker.with_context(CtxModule(modname)):
                self._check_module_spec(iface, actual_modname, modules_desc)

        # check system-level properties (description, system ref, etc.)
        self._check_system_props(desc, sys_props)

    def _check_module_mappings(self, required_modules: dict,
                                modules_map: dict, module_names: set[str],
                                system_ref: str) -> None:
        for modname, iface in required_modules.items():
            optional = getattr(iface, 'optional', False) if \
                hasattr(iface, 'optional') else False
            if optional:
                if modname in modules_map:
                    actual_mod = modules_map[modname]
                    if not isinstance(actual_mod, str) or \
                       actual_mod not in module_names:
                        self.checker.emit(
                            Severity.ERROR,
                            f'optional module {modname!r} maps to '
                            f'non-existent module {actual_mod!r}',
                        )
            elif modname not in modules_map:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required module {modname!r} '
                    "in 'modules' mapping",
                )
            else:
                actual_mod = modules_map[modname]
                if not isinstance(actual_mod, str) or \
                   actual_mod not in module_names:
                    self.checker.emit(
                        Severity.ERROR,
                        f'module {modname!r} maps to '
                        f'non-existent module {actual_mod!r}',
                    )

        for modname in modules_map:
            if modname not in required_modules:
                self.checker.emit(
                    Severity.WARNING,
                    f'module {modname!r} is not defined in system '
                    f'{system_ref!r}',
                )

    def _has_raw_specs(self, items: list) -> bool:
        return bool(items) and isinstance(items[0], dict)

    def _check_module_spec(self, spec: Interface, actual_modname: str,
                           modules_desc: dict[str, dict]) -> None:
        actual = modules_desc.get(actual_modname)
        if actual is None:
            return

        # 1. interface class check
        self._check_interface_class(spec, actual)

        accessibles = actual.get('accessibles', {})

        # 2. parameter specs
        if self._has_raw_specs(spec.parameters):
            for pspec in cast('list[dict[str, dict]]', spec.parameters):
                for pname, pprops in pspec.items():
                    self._check_param_spec(pname, pprops, accessibles)

        # 3. command specs
        if self._has_raw_specs(spec.commands):
            for cspec in cast('list[dict[str, dict]]', spec.commands):
                for cname, cprops in cspec.items():
                    self._check_cmd_spec(cname, cprops, accessibles)

        # 4. module-level property specs
        if self._has_raw_specs(spec.properties):
            for mpspec in cast('list[dict[str, dict]]', spec.properties):
                for pname, pprops in mpspec.items():
                    self._check_mod_prop_spec(pname, pprops, actual)

    def _check_interface_class(self, spec: Interface, actual: dict) -> None:
        required = spec.name
        actual_ifaces = actual.get('interface_classes', [])

        if required in actual_ifaces:
            return

        for iface_name in actual_ifaces:
            iface = self.inv.get(Interface, iface_name)
            if iface is not None and self._inherits(iface, required):
                return

        self.checker.emit(
            Severity.ERROR,
            f'requires interface {required!r}, '
            f'module declares {actual_ifaces}',
        )

    def _inherits(self, iface: Interface, target: str) -> bool:
        current: Interface | None = iface
        while current is not None:
            if current.name == target:
                return True
            current = current.base
        return False

    def _check_param_spec(self, pname: str, pprops: dict,
                          accessibles: dict) -> None:
        optional = pprops.get('optional', False)

        if pname not in accessibles:
            if not optional:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required parameter {pname!r}',
                )
            return

        actual = accessibles[pname]

        if 'datainfo' in pprops:
            expected_di = pprops['datainfo']
            actual_di = actual.get('datainfo', {})
            self._check_datainfo(pname, expected_di, actual_di)

        if 'readonly' in pprops:
            expected = pprops['readonly']
            actual_val = actual.get('readonly', False)
            if actual_val is not expected:
                self.checker.emit(
                    Severity.ERROR,
                    f'parameter {pname!r} has readonly={actual_val}, '
                    f'expected {expected}',
                )

        # check parameter-level properties (visibility, etc.)
        for prop_spec in pprops.get('properties', []):
            if isinstance(prop_spec, dict):
                for prop_name, prop_props in prop_spec.items():
                    forced_val = prop_props.get('value')
                    if forced_val is not None:
                        actual_val = actual.get(prop_name)
                        if actual_val != forced_val:
                            self.checker.emit(
                                Severity.ERROR,
                                f'parameter property {prop_name!r} on '
                                f'{pname!r} has {actual_val!r}, '
                                f'expected {forced_val!r}',
                            )

    def _check_datainfo(self, pname: str, expected: dict,
                        actual: dict) -> None:
        etype = expected.get('type')
        atype = actual.get('type')
        if etype and atype and etype != atype \
                and not (etype == 'string' and atype == 'enum'):
            self.checker.emit(
                    Severity.ERROR,
                    f'parameter {pname!r} has datainfo type {atype!r}, '
                    f'expected {etype!r}',
                )
        for key, evalue in expected.items():
            if key in {'type', 'description'}:
                continue
            if key not in actual:
                self.checker.emit(
                    Severity.ERROR,
                    f'parameter {pname!r} missing datainfo property '
                    f'{key!r} (expected {evalue!r})',
                )
            elif actual[key] != evalue:
                self.checker.emit(
                    Severity.ERROR,
                    f'parameter {pname!r} datainfo.{key} is '
                    f'{actual[key]!r}, expected {evalue!r}',
                )

    def _check_cmd_spec(self, cname: str, cprops: dict,
                        accessibles: dict) -> None:
        optional = cprops.get('optional', False)

        if cname not in accessibles and not optional:
            self.checker.emit(
                Severity.ERROR,
                f'missing required command {cname!r}',
            )

    def _check_mod_prop_spec(self, pname: str, pprops: dict,
                             actual: dict) -> None:
        forced_val = pprops.get('value')
        if forced_val is not None:
            actual_val = actual.get(pname)
            if isinstance(forced_val, dict) and isinstance(actual_val, dict):
                mismatches = {k: (actual_val.get(k), v)
                              for k, v in forced_val.items()
                              if actual_val.get(k) != v}
                if mismatches:
                    self.checker.emit(
                        Severity.ERROR,
                        f'module property {pname!r} mismatches: '
                        f'{mismatches}',
                    )
            elif actual_val != forced_val:
                self.checker.emit(
                    Severity.ERROR,
                    f'module property {pname!r} has {actual_val!r}, '
                    f'expected {forced_val!r}',
                )

    def _check_system_props(self, sysdesc: dict,
                            sys_props: dict[str, tuple]) -> None:
        required = {prop for prop, (propspec, _) in sys_props.items()
                    if not propspec.optional}
        for member, mvalue in sysdesc.items():
            if member == 'modules':
                continue
            required.discard(member)
            with self.checker.with_context(CtxProperty(member)):
                if member not in sys_props:
                    if not member.startswith('_'):
                        self.checker.emit(
                            Severity.WARNING,
                            "non-standard properties need '_' "
                            'as a prefix',
                        )
                else:
                    self.checker.check_dataty(
                        sys_props[member][0].dataty, mvalue)
                    fv = sys_props[member][0].forced_value
                    if fv is not None and mvalue != fv:
                        self.checker.emit(
                            Severity.ERROR,
                            f'property has forced value '
                            f'{fv!r}, got {mvalue!r}',
                        )
        if required:
            self.checker.emit(
                Severity.ERROR,
                "missing required properties: "
                f"{', '.join(map(repr, sorted(required)))}",
            )


class BasePropsChecker(BaseVisitor):
    name = 'properties-basic'

    def check_props(self, description: desc_dict, props: dict,
                    skip: str | tuple[str, ...] | None = None) -> None:
        required = {prop for prop, (propspec, _) in props.items()
                    if not propspec.optional}
        skip_set = {skip} if isinstance(skip, str) else set(skip or ())
        for member, mvalue in description.items():
            if member in skip_set:
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
                         ('modules', 'systems'))

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
               (kval == 'double' and aval == 'scaled') or \
               (kval == 'string' and aval == 'enum'):
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
    SystemChecker,
    BasePropsChecker,
    AccessibleChecker,
]
