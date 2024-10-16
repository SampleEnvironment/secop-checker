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
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml


class opt:
    def __init__(self, ty):
        self.ty = ty


META_SCHEMA = {
    'Version': {
        'systems': list,
        'interfaces': list,
        'features': list,
        'parameters': list,
        'commands': list,
        'properties': dict,
    },
    'System': {
        'base': opt(str),
        'modules': list,
        'systems': list,
    },
    'Interface': {
        'base': opt(str),
        'parameters': opt(list),
        'commands': opt(list),
        'properties': opt(list),
    },
    'Feature': {
        'parameters': opt(list),
        'commands': opt(list),
        'properties': opt(list),
    },
    'Parameter': {
        'readonly': bool,
        'datainfo': str,
        'properties': opt(list),
        'optional': opt(bool),
    },
    'Command': {
        'argument': str,
        'result': str,
        'properties': opt(list),
        'optional': opt(bool),
    },
    'Property': {
        'datainfo': str,
        'optional': opt(bool),
    },
    'Datatype': {
        'dataty': str,
        'members': dict,
    }
}
COMMON_META = {'kind', 'name', 'version', 'description'}


# int-enum?
class Severity(Enum):
    # not a violation, but might be interesting
    HINT = 0
    # something that only violates semantics
    WARNING = 1
    # something that violates non-semantic requirements of the spec
    ERROR = 2
    # something that makes the checking stop directly
    CATASTROPHIC = 3


@dataclass
class Context:
    path: list[tuple[str, str]]
    # system?


@dataclass
class Diagnostic:
    severity: Severity
    step: str
    ctx: Context
    msg: str


class Catastrophe(Exception):
    pass


@dataclass
class Spec:
    name: str
    version: int
    description: str
    # Member lists of the given version
    members: dict
    # Properties by kind
    prop_map: dict
    # All other objects, by kind
    inventory: dict


class DiagnosticBase:
    def __init__(self, output_json=False):
        self._output_json = output_json
        self._diags = []
        self._step = ''
        self._context = Context(path=[])

    @contextmanager
    def with_context(self, kind, name):
        self._context.path.append((kind, name))
        yield
        self._context.path.pop()

    def emit(self, severity, msg):
        diag = Diagnostic(severity, self._step, deepcopy(self._context), msg)
        self._diags.append(diag)
        self._print(diag)
        if severity == Severity.CATASTROPHIC:
            raise Catastrophe

    def _print(self, diag):
        if self._output_json:
            print(json.dumps({
                'severity': diag.severity.name,
                'step': diag.step,
                'msg': diag.msg,
                'ctx': diag.ctx.path,
            }))
        else:
            step = f' [{diag.step}]' if diag.step else ''
            ctx = ' / '.join(f'{ty} {name}'.strip()
                             for ty, name in diag.ctx.path).strip()
            if ctx:
                ctx += ': '
            print(f'{diag.severity.name}{step}: {ctx}{diag.msg}')


class Loader(DiagnosticBase):
    def __init__(self, root, output_json=False):
        super().__init__(output_json)
        self._root = root
        self._all_objects = {}

    def _load_one(self, filename):
        with filename.open() as f:
            data = list(yaml.safe_load_all(f))

        # check all objects in the file
        with self.with_context('File', filename):
            for spec in data:
                # check for required fields for all objects
                for req in COMMON_META:
                    if req not in spec:
                        self.emit(Severity.ERROR, 'found spec item without '
                                  f'required `{req}`: {spec!r}')
                spec['description'] = spec['description'].strip()

                # check for kind and required fields for kind
                kind = spec['kind']
                if kind not in META_SCHEMA:
                    self.emit(Severity.ERROR, f'unknown kind {kind} '
                              f'in {spec!r}')
                fields = set(spec) - COMMON_META
                for field, ftype in META_SCHEMA[kind].items():
                    fields.discard(field)
                    if field not in spec and not isinstance(ftype, opt):
                        self.emit(Severity.ERROR, f'missing field {field} '
                                  f'in {spec!r}')
                    elif field in spec:
                        ftype = ftype.ty if isinstance(ftype, opt) else ftype
                        if not isinstance(spec[field], ftype):
                            self.emit(Severity.ERROR, f'invalid type for '
                                      f'field {field} in {spec!r}')
                if fields:
                    self.emit(Severity.ERROR, f'unknown fields {fields} '
                              f'in {spec!r}')

                # check for duplicates
                key = spec['name'], spec['version']
                if key in self._all_objects.setdefault(kind, {}):
                    self.emit(Severity.ERROR, 'duplicate spec for '
                              f'{kind} {key}')
                self._all_objects[kind][key] = spec

    def _resolve(self, kind, reference):
        if isinstance(reference, dict):
            name, props = reference.popitem()
            if reference:
                reference[name] = props
                self.emit(Severity.ERROR,
                          f'invalid reference {reference}, needs to be a '
                          '1-element dictionary')
            if 'definition' not in props:
                # TODO allow this or not?
                if 'description' not in props:
                    self.emit(Severity.ERROR, 'spec item must have a '
                              'description')
                    props['description'] = ''
                return name, props
            base = deepcopy(self._resolve(kind, props.pop('definition'))[1])
            base.update(props)
            return name, base

        # TODO: implement references to other inventories
        if ':' not in reference:
            self.emit(Severity.CATASTROPHIC, f'invalid reference {reference}')
        name, version = reference.split(':')
        try:
            version = int(version)
        except ValueError:
            self.emit(Severity.ERROR, f'invalid version {version}')
            version = 0
        try:
            return name, self._all_objects[kind][name, version]
        except KeyError:
            self.emit(Severity.CATASTROPHIC, f'could not resolve {kind} '
                      f'reference {name}:{version}')

    def load(self, version):
        # resolve by version
        if not (self._root / f'version-{version}.yaml').exists():
            self.emit(Severity.CATASTROPHIC, 'no root yaml found for '
                      f'version {version}')

        for doc in self._root.glob('*.yaml'):
            self._load_one(doc)

        # build up objects from version inventory
        ver = self._all_objects['Version'][(version, 1)]  # TODO: other revs?
        inv = {}
        prop_map = {}

        with self.with_context('Version', version):
            for ref in ver['systems']:
                # TODO
                pass

            for ref in ver['interfaces']:
                name, iface = self._resolve('Interface', ref)

                with self.with_context('Interface', name):
                    if 'base' in iface:
                        iface['base'] = self._resolve('Interface', iface['base'])
                    else:
                        iface['base'] = None

                    new_params = {}
                    for param in iface.get('parameters', []):
                        pname, param = self._resolve('Parameter', param)
                        new_params[pname] = param
                    iface['parameters'] = new_params

                    new_cmds = {}
                    for cmd in iface.get('commands', []):
                        cname, cmd = self._resolve('Command', cmd)
                        new_cmds[cname] = cmd
                    iface['commands'] = new_cmds

                    new_props = {}
                    for prop in iface.get('properties', []):
                        pname, prop = self._resolve('Property', prop)
                        new_props[pname] = prop
                    iface['properties'] = new_props

                # TODO: check for duplicate interfaces
                inv.setdefault('Interface', {})[name] = iface

            for ref in ver['features']:
                name, feat = self._resolve('Feature', ref)

                with self.with_context('Feature', name):
                    new_params = {}
                    for param in feat.get('parameters', []):
                        pname, param = self._resolve('Parameter', param)
                        new_params[pname] = param
                    feat['parameters'] = new_params

                    new_cmds = {}
                    for cmd in feat.get('commands', []):
                        cname, cmd = self._resolve('Command', cmd)
                        new_cmds[cname] = cmd
                    feat['commands'] = new_cmds

                    new_props = {}
                    for prop in feat.get('properties', []):
                        pname, prop = self._resolve('Property', prop)
                        new_props[pname] = prop
                    feat['properties'] = new_props

                # TODO: check for duplicates
                inv.setdefault('Feature', {})[name] = feat

            for ref in ver['parameters']:
                name, par = self._resolve('Parameter', ref)

                with self.with_context('Parameter', name):
                    new_props = {}
                    for prop in par.get('properties', []):
                        pname, prop = self._resolve('Property', prop)
                        new_props[pname] = prop
                    par['properties'] = new_props

                # TODO: check for duplicates
                inv.setdefault('Parameter', {})[name] = par

            for ref in ver['commands']:
                name, cmd = self._resolve('Command', ref)

                with self.with_context('Command', name):
                    new_props = {}
                    for prop in cmd.get('properties', []):
                        pname, prop = self._resolve('Property', prop)
                        new_props[pname] = prop
                    cmd['properties'] = new_props

                # TODO: check for duplicates
                inv.setdefault('Command', {})[name] = cmd

            for (proptype, props) in ver['properties'].items():
                for ref in props:
                    name, prop = self._resolve('Property', ref)
                    prop_map.setdefault(proptype, {})[name] = prop

        return Spec(version, ver['version'], ver['description'], {
            'systems': ver['systems'],
            'interfaces': ver['interfaces'],
            'features': ver['features'],
            'parameters': ver['parameters'],
            'commands': ver['commands'],
            'properties': ver['properties'],
        }, prop_map, inv)


class Checker(DiagnosticBase):
    def __init__(self, version='latest', output_json=False):
        super().__init__(output_json)

        loader = Loader(Path(__file__).parents[1] / 'defs')
        self._spec = loader.load(version)
        if loader._diags:
            self.emit(Severity.CATASTROPHIC, 'found errors loading spec to '
                      'validate against, exiting')

        # schema of params/commands by module, combined from interfaces,
        # features and systems
        self._all_pars = {}
        self._all_cmds = {}
        # combined schema of properties by module
        self._all_modprops = {}
        # combined schema of properties by (module, accessible)
        self._all_accprops = {}

    def check(self, desc: str):
        try:
            desc = json.loads(desc)
        except json.JSONDecodeError as e:
            self.emit(Severity.CATASTROPHIC, f'invalid json at line {e.lineno}'
                      f' column {e.colno}:\n{e.msg}')
        # TODO: add mechanism to add additional yaml repos from desc here

        self.visit_descriptive_data(desc)

    def visit_descriptive_data(self, desc):
        for checkercls in CHECKERS:
            self._step = checkercls.name
            self.visit_with_checker(desc, checkercls(self))

    def visit_with_checker(self, desc, checker):
        with self.with_context('SECNode', ''):
            checker.visit_secnode(desc)

            for prop, propdesc in desc.items():
                if prop == 'modules':
                    for module, moddesc in propdesc.items():
                        with self.with_context('Module', module):
                            self._visit_module(module, moddesc, checker)

                # other node properties
                else:
                    with self.with_context('Property', prop):
                        checker.visit_property('SECNode', prop, propdesc)

            checker.finish()

    def _visit_module(self, modname, moddesc, checker):
        checker.visit_module(modname, moddesc)

        for prop, propdesc in moddesc.items():
            if prop == 'accessibles':
                for accname, accdesc in propdesc.items():
                    datainfo = accdesc.get('datainfo', {})
                    ty = 'Command' if datainfo.get('type') == 'command' \
                        else 'Parameter'
                    with self.with_context(ty, accname):
                        checker.visit_datainfo(datainfo)

                        if ty == 'Command':
                            checker.visit_command(modname, accname, accdesc)
                        else:
                            checker.visit_parameter(modname, accname, accdesc)

                        for prop, propdesc in accdesc.items():
                            with self.with_context('Property', prop):
                                checker.visit_property(ty, prop, propdesc)

                        checker.finish_accessible(accdesc)

            # other module properties
            else:
                with self.with_context('Property', prop):
                    checker.visit_property('Module', prop, propdesc)

            checker.finish_module(modname)


def is_command(desc):
    datainfo = desc.get('datainfo', {})
    return datainfo.get('type') == 'command'


class BaseTestChecker:
    name = 'check-base'

    def __init__(self, checker):
        self.checker = checker
        self.spec = checker._spec

    def visit_property(self, nodekind, name, description):
        """Visiting properties of any node."""

    def visit_secnode(self, description):
        """Visiting the root SECNode element."""

    def visit_module(self, name, description):
        """Visiting each module of a SECnode."""

    def visit_parameter(self, modname, name, description):
        """Visiting each accessible of a module."""

    def visit_command(self, modname, name, description):
        """Visiting each accessible of a module."""

    def visit_datainfo(self, description):
        """Visiting datainfo entries of accessibles."""

    def finish_accessible(self, description):
        """Called after all subelements of an accessible."""

    def finish_module(self, name):
        """Called after all subelements of a module."""

    def finish(self):
        """Called after all elements are processed."""


class BasicStructureChecker(BaseTestChecker):
    """Checks for basic structure of the descriptive data.

    It should fail with CATASTROPHIC errors because further checkers probably
    will raise a lot of KeyErrors.
    """
    name = 'structure'

    def visit_secnode(self, description):
        if 'modules' not in description:
            self.checker.emit(Severity.ERROR, 'missing modules dict')
            description['modules'] = {}

    def visit_module(self, name, description):
        if 'accessibles' not in description:
            self.checker.emit(Severity.ERROR,
                              'missing dict of module accessibles')
            description['accessibles'] = {}


class DatainfoChecker(BaseTestChecker):
    """Checks for valid datainfos, no matter where they are defined.
    """
    name = 'datainfo'

    def visit_datainfo(self, description):
        if not description:
            self.checker.emit(Severity.ERROR, 'datainfo is empty')
        if 'type' not in description:
            self.checker.emit(Severity.ERROR, 'datainfo does not have a type')
            description['type'] = 'unknown'
        if description['type'] == 'command':
            if 'argument' in description:
                with self.checker.with_context('datainfo', 'argument'):
                    self.visit_datainfo(description['argument'])
            if 'result' in description:
                with self.checker.with_context('datainfo', 'result'):
                    self.visit_datainfo(description['result'])
        # TODO more


class NameChecker(BaseTestChecker):
    """Checks that names conform to the required format."""
    name = 'names'

    _mod = re.compile(r'^[a-zA-Z]\w{0,62}$')
    _ident = re.compile(r'^[_a-zA-Z]\w{0,62}$')

    def visit_module(self, name, description):
        if not self._mod.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required module name format')

    def visit_parameter(self, modname, name, description):
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required parameter name format')

    def visit_command(self, modname, name, description):
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required command name format')

    def visit_property(self, nodekind, name, description):
        if not self._ident.match(name):
            self.checker.emit(Severity.ERROR,
                              'does not match required property name format')


class InterfaceChecker(BaseTestChecker):
    """Checks that all declared interfaces exist."""
    name = 'interface'

    def visit_module(self, name, description):
        self.checker._all_pars[name] = {
            pname: (par, None)
            for (pname, par) in self.spec.inventory['Parameter'].items()
        }
        self.checker._all_cmds[name] = {
            cname: (cmd, None)
            for (cname, cmd) in self.spec.inventory['Command'].items()
        }
        self.checker._all_modprops[name] = self.spec.prop_map['Module'].copy()

        for acc, accdesc in description['accessibles'].items():
            if is_command(accdesc):
                self.checker._all_accprops[name, acc] = \
                    self.spec.prop_map['Command'].copy()
            else:
                self.checker._all_accprops[name, acc] = \
                    self.spec.prop_map['Parameter'].copy()

        for iface in description.get('interface_classes', []):
            if iface.startswith('_'):  # TODO custom classes are allowed?
                continue

            if iface not in self.spec.inventory['Interface']:
                self.checker.emit(Severity.ERROR,
                                  f'declares unknown interface class {iface}')
                return

            desc = self.spec.inventory['Interface'][iface]
            self.checker._all_pars[name].update({
                pname: (par, 'interface ' + iface)
                for (pname, par) in desc['parameters'].items()
            })
            self.checker._all_cmds[name].update({
                cname: (cmd, 'interfae ' + iface)
                for (cname, cmd) in desc['commands'].items()
            })
            self.checker._all_modprops[name].update(desc['properties'])

            # TODO: accessible props

        for feat in description.get('features', []):
            if feat.startswith('_'):  # TODO custom classes are allowed?
                continue

            if feat not in self.spec.inventory['Feature']:
                self.checker.emit(Severity.ERROR,
                                  f'declares unknown feature {feat}')
                return

            desc = self.spec.inventory['Feature'][feat]
            self.checker._all_pars[name].update({
                pname: (par, 'feature ' + feat)
                for (pname, par) in desc['parameters'].items()
            })
            self.checker._all_cmds[name].update({
                cname: (cmd, 'feature ' + feat)
                for (cname, cmd) in desc['commands'].items()
            })
            self.checker._all_modprops[name].update(desc['properties'])

            # TODO: accessible props


class BasePropsChecker(BaseTestChecker):
    name = 'properties-basic'

    def check_props_present(self, description, props, skip=None):
        required = set(
            [prop for prop, propspec in props.items()
             if not propspec.get('optional', False)]
        )
        for member, mvalues in description.items():
            if member == skip:
                continue
            required.discard(member)
            if member not in props:
                if not member.startswith('_'):
                    self.checker.emit(
                        Severity.WARNING,
                        f'{member}: non-standard properties need \'_\' as a prefix'
                    )
                # TODO: check custom property datainfo etc if possible
        if required:
            self.checker.emit(
                Severity.ERROR,
                f'missing required properties: {required}'
            )

    def visit_secnode(self, description):
        self.check_props_present(description,
                                 self.spec.prop_map['SECNode'],
                                 'modules')

    def visit_module(self, name, description):
        self.check_props_present(description,
                                 self.checker._all_modprops[name],
                                 'accessibles')

    def visit_parameter(self, modname, name, description):
        self.check_props_present(description,
                                 self.checker._all_accprops[modname, name])

    def visit_command(self, modname, name, description):
        self.check_props_present(description,
                                 self.checker._all_accprops[modname, name])


class AccessibleChecker(BaseTestChecker):
    """Checks that modules have all accessibles required by their
    interfaces/features and that accessibles match the spec.
    """
    name = 'accessibles'

    def visit_module(self, name, description):
        for pname, (parspec, from_) in self.checker._all_pars[name].items():
            if from_ and not parspec.get('optional', False) and \
               pname not in description['accessibles']:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required parameter {pname} from {from_}'
                )
        for cname, (cmdspec, from_) in self.checker._all_cmds[name].items():
            if from_ and not cmdspec.get('optional', False) and \
               cname not in description['accessibles']:
                self.checker.emit(
                    Severity.ERROR,
                    f'missing required command {cname} from {from_}'
                )

    def check_datainfo(self, description, should):
        pass  # TODO nothing we can do so far

    def visit_parameter(self, modname, name, description):
        should = self.checker._all_pars[modname].get(name)
        if should is None:
            if not name.startswith('_'):
                self.checker.emit(
                    Severity.WARNING,
                    'non-standard parameters need \'_\' as a prefix'
                )
            return
        should = should[0]

        if description['readonly'] != should['readonly']:
            if should['readonly']:
                self.checker.emit(Severity.WARNING,
                                  'parameter should be readonly')
            else:
                self.checker.emit(Severity.WARNING,
                                  'parameter should not be readonly')
        self.check_datainfo(description['datainfo'], should['datainfo'])

    def visit_command(self, modname, name, description):
        should = self.checker._all_cmds[modname].get(name)
        if should is None:
            if not name.startswith('_'):
                self.checker.emit(
                    Severity.WARNING,
                    'non-standard commands need \'_\' as a prefix'
                )
            return
        should = should[0]

        if 'argument' in description['datainfo']:
            if should['argument'] == 'none':
                self.checker.emit(Severity.WARNING,
                                  'command should not have an argument')
            else:
                self.check_datainfo(description['datainfo']['argument'],
                                    should['argument'])
        else:
            if should['argument'] != 'none':
                self.checker.emit(Severity.WARNING,
                                  'command should have an argument: '
                                  f'{should["argument"]}')

        if 'result' in description['datainfo']:
            if should['result'] == 'none':
                self.checker.emit(Severity.WARNING,
                                  'command should not have an result')
            else:
                self.check_datainfo(description['datainfo']['result'],
                                    should['result'])
        else:
            if should['result'] != 'none':
                self.checker.emit(Severity.WARNING,
                                  'command should have an result: '
                                  f'{should["result"]}')


CHECKERS = [BasicStructureChecker, DatainfoChecker, NameChecker,
            InterfaceChecker, BasePropsChecker, AccessibleChecker]
