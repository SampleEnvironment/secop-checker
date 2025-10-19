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

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

import yaml

from . import DiagnosticBase, Severity

COMMON_META = {'kind', 'name', 'version', 'description'}


@dataclass
class Property:
    name: str
    version: int
    link: str
    description: str
    dataty: object
    optional: bool


@dataclass
class Datainfo:
    name: str
    version: int
    link: str
    description: str
    dataty: object
    members: dict[str, Property]


@dataclass
class Parameter:
    name: str
    version: int
    link: str
    description: str
    datainfo: Datainfo
    readonly: bool
    optional: bool
    properties: list[Property]


@dataclass
class Command:
    name: str
    version: int
    link: str
    description: str
    argument: Datainfo | None
    result: Datainfo | None
    optional: bool
    properties: list[Property]


@dataclass
class Interface:
    name: str
    version: int
    link: str
    description: str
    base: Interface | None
    parameters: list[Parameter]
    commands: list[Command]
    properties: list[Property]


@dataclass
class Feature:
    name: str
    version: int
    link: str
    description: str
    parameters: list[Parameter]
    commands: list[Command]
    properties: list[Property]


@dataclass
class System:
    name: str
    version: int
    link: str
    description: str
    base: System | None
    modules: dict[str, Interface]
    systems: dict[str, System]


@dataclass
class Properties:
    node: list[Property]
    system: list[Property]
    module: list[Property]
    parameter: list[Property]
    command: list[Property]


@dataclass
class Repository:
    name: str
    version: int
    link: str
    description: str
    files: list[str]
    systems: list[System]
    interfaces: list[Interface]
    features: list[Feature]
    parameters: list[Parameter]
    commands: list[Command]
    properties: Properties
    datainfo: list[Datainfo]


class Inventory:
    def __init__(self):
        self._all_objects = {}
        self._global = {}
        self._global_props = {}

    def add(self, kind, obj):
        self._all_objects.setdefault(
            kind, {}).setdefault(obj.name, []).append(obj)

    def add_global(self, kind, name):
        self._global.setdefault(kind, set()).add(name)

    def add_global_props(self, kind, name):
        self._global_props.setdefault(kind, set()).add(name)

    def get(self, kind, name, version=None):
        if kind not in self._all_objects:
            return None
        if name not in self._all_objects[kind]:
            return None
        if version is not None:
            for obj in self._all_objects[kind][name]:
                if obj.version == version:
                    return obj
            return None
        return self._all_objects[kind][name][0]

    def get_all(self, kind):
        return self._all_objects.get(kind, {})

    def is_global(self, kind, name):
        return name in self._global.get(kind, {})

    def get_global(self, kind):
        # TODO: multiple versions
        return [self._all_objects[kind][name][0] for
                name in self._global.get(kind, {})]

    def get_global_props(self, kind):
        # TODO: multiple versions
        return [self._all_objects['Property'][name][0] for
                name in self._global_props.get(kind, {})]


class Loader(DiagnosticBase):
    def __init__(self, root, output):
        super().__init__(output)
        self._inv = Inventory()
        self._root = Path(root)

    def _load_one(self, uri, raw_objects):
        uri = str(uri)
        try:
            openfunc = urlopen if '://' in uri else open
            with openfunc(uri) as f:
                data = list(yaml.safe_load_all(f))
        except Exception as err:  # noqa: BLE001
            self.emit(Severity.CATASTROPHIC, 'could not load yaml from '
                      f'{uri}: {err}')
            return

        with self.with_context('File', uri):
            for spec in data:
                # check for required fields for all objects
                for req in COMMON_META:
                    if req not in spec:
                        self.emit(Severity.ERROR, 'found yaml item without '
                                  f'required {req}: {spec!r}')
                spec['description'] = spec['description'].strip()
                raw_objects.setdefault(
                    spec['kind'], {}).setdefault(
                        spec['name'], {})[spec['version']] = spec

    def load_repo(self, uri):
        uri = str(uri)
        raw_objects = {}
        self._load_one(uri, raw_objects)

        repos = raw_objects.get('Repository', {})
        if len(repos) != 1:
            self.emit(Severity.CATASTROPHIC, 'did not find exactly one '
                      f'schema repository in {uri}')
        repos = next(iter(repos.values()))
        if len(repos) != 1:
            self.emit(Severity.CATASTROPHIC, 'did not find exactly one '
                      f'schema repository in {uri}')
        repo = next(iter(repos.values()))

        for filename in repo['files']:
            if '://' in uri:
                parsed = urlparse(uri)
                new_path = Path(parsed.path) / filename
                new_uri = urlunparse(parsed._replace(path=new_path))
            else:
                new_uri = Path(uri).parent / filename
            self._load_one(new_uri, raw_objects)

        # this will also resolve all reachable subobjects and add them to
        # the inventory
        return Converter(self, raw_objects).convert(repo)

    def load(self, version, additional):
        ver_root = self._root / f'version-{version}.yaml'
        if not ver_root.is_file():
            self.emit(Severity.CATASTROPHIC, 'no root yaml found for '
                      f'version {version}')
        self.load_repo(ver_root)

        for add in additional:
            self.load_repo(add)

    def get_inv(self):
        return self._inv


ref = (dict, str)


class Converter:
    def __init__(self, loader, raw):
        self.loader = loader
        self.inv = loader.get_inv()
        self.raw = raw

    def convert(self, data):
        try:
            method = getattr(self, '_mk_' + data['kind'].lower())
        except AttributeError:
            self.loader.emit(Severity.CATASTROPHIC, 'unknown yaml kind '
                             f'{data["kind"]} in object {data["name"]!r}')
        with self.loader.with_context(data['kind'], data['name']):
            return method(data)

    def _resolve(self, kind, reference):
        if isinstance(reference, dict):
            name, props = reference.popitem()
            if reference:
                reference[name] = props
                self.loader.emit(Severity.CATASTROPHIC,
                                 f'invalid reference {reference}, needs to be '
                                 'a 1-element dictionary')
            if 'definition' not in props:
                if 'description' not in props:
                    self.loader.emit(Severity.ERROR, 'spec item must have a '
                                     'description')
                    props['description'] = ''
                props['kind'] = kind
                props['version'] = 0
                props['name'] = name
                return self.convert(props)
            base = deepcopy(self._resolve(kind, props.pop('definition')))
            for key, val in props.items():
                setattr(base, key, val)  # TODO: does not resolve!
            return base

        if not isinstance(reference, str):
            self.loader.emit(Severity.CATASTROPHIC,
                             f'invalid {kind} reference type {reference!r}')

        if ':' not in reference:
            self.loader.emit(Severity.CATASTROPHIC,
                             f'invalid {kind} reference {reference!r}')
        name, version = reference.split(':')
        try:
            version = int(version)
        except ValueError:
            self.loader.emit(Severity.ERROR, f'invalid version {version}')
            version = 0

        if done := self.inv.get(kind, name, version):
            return done

        try:
            obj = self.raw[kind][name][version]
        except KeyError:
            self.loader.emit(Severity.CATASTROPHIC, f'could not resolve {kind}'
                             f' reference {name}:{version}')
        else:
            schema_obj = self.convert(obj)
            self.inv.add(kind, schema_obj)
            return schema_obj

    def _get(self, data, key, typ, default=Ellipsis):
        if key in data:
            if isinstance(data[key], typ):
                return data[key]
            self.loader.emit(Severity.CATASTROPHIC,
                             f'expected {key} to be of type {typ}, but '
                             f'got {type(data[key])}')
        if default is Ellipsis:
            self.loader.emit(Severity.CATASTROPHIC, f'missing key {key!r}')
        return default

    def _mk_repository(self, data):
        repo = Repository(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            files=self._get(data, 'files', list),
            systems=[self._resolve('System', x)
                     for x in self._get(data, 'systems', list)],
            interfaces=[self._resolve('Interface', x)
                        for x in self._get(data, 'interfaces', list)],
            features=[self._resolve('Feature', x)
                      for x in self._get(data, 'features', list)],
            parameters=[self._resolve('Parameter', x)
                        for x in self._get(data, 'parameters', list)],
            commands=[self._resolve('Command', x)
                      for x in self._get(data, 'commands', list)],
            properties=self._mk_properties(
                self._get(data, 'properties', dict)),
            datainfo=[self._resolve('Datainfo', x)
                      for x in self._get(data, 'datainfo', list)],
        )
        for system in repo.systems:
            self.inv.add_global('System', system.name)
        for interface in repo.interfaces:
            self.inv.add_global('Interface', interface.name)
        for feature in repo.features:
            self.inv.add_global('Feature', feature.name)
        for parameter in repo.parameters:
            self.inv.add_global('Parameter', parameter.name)
        for command in repo.commands:
            self.inv.add_global('Command', command.name)
        for prop in repo.properties.node:
            self.inv.add_global_props('SECNode', prop.name)
        for prop in repo.properties.system:
            self.inv.add_global_props('System', prop.name)
        for prop in repo.properties.module:
            self.inv.add_global_props('Module', prop.name)
        for prop in repo.properties.parameter:
            self.inv.add_global_props('Parameter', prop.name)
        for prop in repo.properties.command:
            self.inv.add_global_props('Command', prop.name)

        return repo

    def _mk_properties(self, data):
        return Properties(
            node=[self._resolve('Property', x)
                  for x in self._get(data, 'SECNode', list)],
            system=[self._resolve('Property', x)
                    for x in self._get(data, 'System', list)],
            module=[self._resolve('Property', x)
                    for x in self._get(data, 'Module', list)],
            parameter=[self._resolve('Property', x)
                       for x in self._get(data, 'Parameter', list)],
            command=[self._resolve('Property', x)
                     for x in self._get(data, 'Command', list)],
        )

    def _mk_system(self, data):
        base = self._get(data, 'base', ref, None)
        modules = {name: self._resolve('Interface',
                                       x if isinstance(x, str) else {name: x})
                   for (name, x) in self._get(data, 'modules', dict).items()}
        systems = {name: self._resolve('System', x) for (name, x) in
                   self._get(data, 'systems', dict, {}).items()}
        return System(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            base=self._resolve('System', base) if base else None,
            modules=modules,
            systems=systems,
        )

    def _mk_interface(self, data):
        base = self._get(data, 'base', ref, None)
        return Interface(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            base=self._resolve('Interface', base) if base else None,
            parameters=[self._resolve('Parameter', x)
                        for x in self._get(data, 'parameters', list, [])],
            commands=[self._resolve('Command', x)
                      for x in self._get(data, 'commands', list, [])],
            properties=[self._resolve('Property', x)
                        for x in self._get(data, 'properties', list, [])],
        )

    def _mk_feature(self, data):
        return Feature(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            parameters=[self._resolve('Parameter', x)
                        for x in self._get(data, 'parameters', list, [])],
            commands=[self._resolve('Command', x)
                      for x in self._get(data, 'commands', list, [])],
            properties=[self._resolve('Property', x)
                        for x in self._get(data, 'properties', list, [])],
        )

    def _mk_parameter(self, data):
        return Parameter(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            datainfo=self._get(data, 'datainfo', ref),
            readonly=self._get(data, 'readonly', bool, default=False),
            optional=self._get(data, 'optional', bool, default=False),
            properties=[self._resolve('Property', x)
                        for x in self._get(data, 'properties', list, [])],
        )

    def _mk_command(self, data):
        return Command(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            argument=self._get(data, 'argument', ref),
            result=self._get(data, 'result', ref),
            optional=self._get(data, 'optional', bool, default=False),
            properties=[self._resolve('Property', x)
                        for x in self._get(data, 'properties', list, [])],
        )

    def _mk_property(self, data):
        return Property(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            dataty=self._get(data, 'dataty', ref),
            optional=self._get(data, 'optional', bool, default=False),
        )

    def _mk_datainfo(self, data):
        return Datainfo(
            name=self._get(data, 'name', str),
            version=self._get(data, 'version', int),
            link=self._get(data, 'link', str, None),
            description=self._get(data, 'description', str),
            dataty=self._get(data, 'dataty', ref),
            members=self._get(data, 'members', dict),
        )
