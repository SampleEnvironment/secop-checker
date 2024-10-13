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

# TODO:
# - version resolution
# - strategy?
#   - checker which each goes through
#   - checker once through tree with callbacks (checker.check_datainfo)
#   - just static coding?
# - define datatypes
# - how to propagate errors?
#   - stop at first error, continue on warning
#   - try best effort to continue? -> effort for all following checkers


REQUIRED_INFO = {'kind', 'name', 'version', 'description'}
ALLOWED_KINDS = {'Version', 'Interface', 'Command', 'Parameter', 'Property',
                 'Datatype', 'System', 'Feature'}


# int-enum?
class Severity(Enum):
    HINT = 0
    WARNING = 1
    ERROR = 2
    CATASTROPHIC = 3  # something, were we just stop?


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
        diag = Diagnostic(severity, self._step, self._context, msg)
        self._diags.append(diag)
        self._print(diag)
        if severity == Severity.CATASTROPHIC:
            raise SystemExit(1)

    def _print(self, diag):
        if self._output_json:
            print(json.dumps({
                'severity': diag.severity.name,
                'step': diag.step,
                'msg': diag.msg,
                'ctx': diag.ctx.path,
            }))
        else:
            ctx = ' -> '.join(f'{ty} {name}'.strip()
                              for ty, name in diag.ctx.path).strip()
            if ctx:
                ctx += ': '
            print(f'{diag.severity.name}: {ctx}{diag.msg}')


class Loader(DiagnosticBase):
    def __init__(self, root, output_json=False):
        super().__init__(output_json)
        self._root = root
        self._all_objects = {}

    def _load_one(self, filename):
        with filename.open() as f:
            data = list(yaml.safe_load_all(f))
        with self.with_context('File', filename):
            for spec in data:
                for req in REQUIRED_INFO:
                    if req not in spec:
                        self.emit(Severity.ERROR, 'found spec item without '
                                  f'required `{req}`: {spec!r}')
                spec['description'] = spec['description'].strip()
                kind = spec['kind']
                if kind not in ALLOWED_KINDS:
                    self.emit(Severity.ERROR, f'unknown kind {kind} '
                              f'in {spec!r}')
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
                self.emit(Severity.CATASTROPHIC,
                          f'invalid reference {reference}, needs to be a '
                          '1-element dictionary')
            if 'definition' not in props:
                # TODO allow this or not?
                for req in REQUIRED_INFO:
                    if req not in props:
                        self.emit(Severity.CATASTROPHIC, 'found spec item '
                                  f'without required `{req}`: {props!r}')
                if props['kind'] != kind:
                    self.emit(Severity.CATASTROPHIC, f'invalid item {props}, '
                              f'kind mismatch {kind} vs {props["kind"]}')
                return props['name'], props
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
            self.emit(Severity.CATASTROPHIC, f'invalid version {version}')
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
            self.visit_with_checker(desc, checkercls(self))

    def visit_with_checker(self, desc, checker):
        with self.with_context('SECNode', ''):
            checker.visit('SECNode', desc)
            checker.visit_secnode(desc)

            for prop, propdesc in desc.items():
                if prop == 'modules':
                    for module, moddesc in propdesc.items():
                        with self.with_context('Module', module):
                            self._visit_module(module, moddesc, checker)

                # other node properties
                else:
                    with self.with_context('Property', prop):
                        checker.visit('Property', propdesc)
                        checker.visit_property('SECNode', prop, propdesc)

            checker.finish()

    def _visit_module(self, module, moddesc, checker):
        checker.visit('Module', moddesc)
        checker.visit_module(module, moddesc)

        for prop, propdesc in moddesc.items():
            if prop == 'accessibles':
                for accname, accdesc in propdesc.items():
                    with self.with_context('Accessible', accname):
                        datainfo = accdesc.get('datainfo', {})
                        ty = 'Command' if datainfo.get('type') == 'command' \
                            else 'Parameter'
                        checker.visit_datainfo(datainfo or None)

                        checker.visit(ty, accdesc)

                        if ty == 'Command':
                            checker.visit_command(accname, accdesc)
                        else:
                            checker.visit_parameter(accname, accdesc)

                        for prop, propdesc in accdesc.items():
                            with self.with_context('Property', prop):
                                checker.visit('Property', propdesc)
                                checker.visit_property(ty, prop, propdesc)

                        checker.finish_accessible(accdesc)

            # other module properties
            else:
                with self.with_context('Property', prop):
                    checker.visit('Property', propdesc)
                    checker.visit_property('Module', prop, propdesc)

            checker.finish_module(module)


class BaseTestChecker:
    name = 'check-base'

    def __init__(self, checker):
        self.checker = checker
        self.spec = checker._spec

    def visit(self, nodekind, description, name=None):
        """Called at every element of the description."""

    def visit_property(self, nodekind, name, description):
        """Visiting properties of any node."""

    def visit_secnode(self, description):
        """Visiting the root SECNode element."""

    def visit_module(self, name, description):
        """Visiting each module of a SECnode."""

    def visit_parameter(self, name, description):
        """Visiting each accessible of a module."""

    def visit_command(self, name, description):
        """Visiting each accessible of a module."""

    def visit_datainfo(self, description):
        """Visiting datainfo entries of accessibles."""

    def finish_accessible(self, description):
        """Called after all subelements of an accessible."""

    def finish_module(self, name):
        """Called after all subelements of a module."""

    def finish(self):
        """Called after all elements are processed."""


class DatainfoChecker(BaseTestChecker):
    name = 'datainfo'

    def visit_datainfo(self, description):
        if not description:
            self.checker.emit(Severity.ERROR, 'datainfo is empty')
        if 'type' not in description:
            self.checker.emit(Severity.ERROR, 'datainfo does not have a type')
        # TODO more


class ModulenameChecker(BaseTestChecker):
    name = 'module-name'

    def visit_module(self, name, description):
        if not re.match(r'^[a-zA-Z]\w{0,62}$', name):
            self.checker.emit(
                Severity.WARNING,
                f'{name} does not match required module name format'
            )


class InterfaceChecker(BaseTestChecker):
    name = 'interface'

    def visit_module(self, name, description):
        for iface in description.get('interface_classes', []):
            if iface.startswith('_'):  # TODO custom classes are allowed?
                continue

            if iface not in self.spec.inventory['Interface']:
                self.checker.emit(Severity.ERROR,
                                  f'declares unknown interface class {iface}')
                return

            ifacedesc = self.spec.inventory['Interface'][iface]
            for cmd, cmddesc in ifacedesc['commands'].items():
                if cmddesc.get('optional', False):
                    continue
                if cmd not in description['accessibles']:
                    self.checker.emit(
                        Severity.ERROR,
                        f'missing command {cmd} from interface {iface}'
                    )

            for par, pardesc in ifacedesc['parameters'].items():
                if pardesc.get('optional', False):
                    continue
                if par not in description['accessibles']:
                    self.checker.emit(
                        Severity.ERROR,
                        f'missing parameter {par} from interface {iface}'
                    )

        for feat in description.get('features', []):
            if feat.startswith('_'):  # TODO custom classes are allowed?
                continue

            if feat not in self.spec.inventory['Feature']:
                self.checker.emit(Severity.ERROR,
                                  f'declares unknown feature {feat}')
                return

            featdesc = self.spec.inventory['Feature'][feat]
            for cmd, cmddesc in featdesc['commands'].items():
                if cmddesc.get('optional', False):
                    continue
                if cmd not in description['accessibles']:
                    self.checker.emit(
                        Severity.ERROR,
                        f'missing command {cmd} from feature {feat}'
                    )

            for par, pardesc in featdesc['parameters'].items():
                if pardesc.get('optional', False):
                    continue
                if par not in description['accessibles']:
                    self.checker.emit(
                        Severity.ERROR,
                        f'missing parameter {par} from feature {feat}'
                    )


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
                Severity.WARNING,
                f'missing required properties: {required}'
            )

    def visit_secnode(self, description):
        self.check_props_present(description,
                                 self.spec.prop_map['SECNode'],
                                 'modules')

    def visit_module(self, name, description):
        all_props = self.spec.prop_map['Module'].copy()
        for iface in description.get('interface_classes', []):
            all_props.update(self.spec.inventory['Interface'][iface]['properties'])
        for feat in description.get('features', []):
            all_props.update(self.spec.inventory['Feature'][feat]['properties'])
        # TODO add more from systems
        self.check_props_present(description, all_props, 'accessibles')

    def visit_parameter(self, name, description):
        all_props = self.spec.prop_map['Parameter'].copy()
        if name in self.spec.inventory['Parameter']:
            all_props.update(self.spec.inventory['Parameter'][name]['properties'])
        # TODO more interfaces, systems, features
        self.check_props_present(description, all_props)

    def visit_command(self, name, description):
        all_props = self.spec.prop_map['Command'].copy()
        if name in self.spec.inventory['Command']:
            all_props.update(self.spec.inventory['Command'][name]['properties'])
        # TODO more interfaces, systems, features
        self.check_props_present(description, all_props)


CHECKERS = [DatainfoChecker, ModulenameChecker, InterfaceChecker,
            BasePropsChecker]
