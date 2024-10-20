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

from copy import deepcopy
from dataclasses import dataclass
from os import path
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

import yaml

from . import DiagnosticBase, Severity


class opt:
    def __init__(self, ty):
        self.ty = ty


META_SCHEMA = {
    'Repository': {
        'files': list,
        'systems': list,
        'interfaces': list,
        'features': list,
        'parameters': list,
        'commands': list,
        'properties': dict,
        'datainfo': list,
    },
    'System': {
        'base': opt(str),
        'modules': list,
        'systems': opt(list),
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
        'datainfo': (str, dict),
        'properties': opt(list),
        'optional': opt(bool),
    },
    'Command': {
        'argument': (str, dict),
        'result': (str, dict),
        'properties': opt(list),
        'optional': opt(bool),
    },
    'Property': {
        'dataty': (str, dict),
        'optional': opt(bool),
    },
    'Datainfo': {
        'dataty': str,
        'members': dict,
    }
}
COMMON_META = {'kind', 'name', 'version', 'description'}


@dataclass
class Inventory:
    # Properties by kind
    prop_map: dict
    # All other objects, by kind
    objects: dict


class Loader(DiagnosticBase):
    def __init__(self, root, output):
        super().__init__(output)
        self._root = root
        self._all_objects = {}

    def _load_one(self, uri, inv):
        try:
            if '://' in uri:
                fobj = urlopen(uri)
            else:
                fobj = open(uri)
            with fobj as f:
                data = list(yaml.safe_load_all(f))
        except Exception as err:
            self.emit(Severity.CATASTROPHIC, 'could not load yaml from '
                      f'{uri}: {err}')
            return

        # check all objects in the file
        with self.with_context('File', uri):
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
                        if isinstance(ftype, opt):
                            ftype = ftype.ty
                        if not isinstance(spec[field], ftype):
                            self.emit(Severity.ERROR, f'invalid type for '
                                      f'field {field} in {spec!r}')
                if fields:
                    self.emit(Severity.ERROR, f'unknown fields {fields} '
                              f'in {spec!r}')

                # check for duplicates
                subdict = inv.setdefault(kind, {}).setdefault(spec['name'], {})
                if spec['version'] in subdict:
                    self.emit(Severity.ERROR, 'duplicate spec for '
                              f'{kind} {spec["name"]} v{spec["version"]}')
                subdict[spec['version']] = spec

    def _load_repo(self, uri):
        uri = str(uri)
        inv = {}
        self._load_one(uri, inv)

        # build up objects from version inventory
        repos = inv.get('Repository', {})
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
                new_path = path.join(path.dirname(parsed.path), filename)
                new_uri = urlunparse(parsed._replace(path=new_path))
            else:
                new_uri = path.join(path.dirname(uri), filename)
            self._load_one(new_uri, self._all_objects)

        return repo

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

        if ':' not in reference:
            self.emit(Severity.CATASTROPHIC, f'invalid reference {reference}')
        name, version = reference.split(':')
        try:
            version = int(version)
        except ValueError:
            self.emit(Severity.ERROR, f'invalid version {version}')
            version = 0
        try:
            return name, self._all_objects[kind][name][version]
        except KeyError:
            self.emit(Severity.CATASTROPHIC, f'could not resolve {kind} '
                      f'reference {name}:{version}')

    def load(self, version, additional):
        # resolve by version
        ver_root = self._root / f'version-{version}.yaml'
        if not ver_root.exists():
            self.emit(Severity.CATASTROPHIC, 'no root yaml found for '
                      f'version {version}')

        repos = [self._load_repo(ver_root)]

        for add in additional:
            repos.append(self._load_repo(add))

        inv = {}
        prop_map = {}

        for repo in repos:
            with self.with_context('Repository', repo['name']):
                for ref in repo['systems']:
                    # TODO
                    pass

                for ref in repo['interfaces']:
                    name, iface = self._resolve('Interface', ref)

                    with self.with_context('Interface', name):
                        if 'base' in iface:
                            # TODO: check bases
                            iface['base'] = self._resolve('Interface', iface['base'])[1]
                        else:
                            iface['base'] = None

                        new_params = {}
                        for param in iface.get('parameters', []):
                            pname, param = self._resolve('Parameter', param)
                            new_params[pname] = param  # TODO multiple versions
                        iface['parameters'] = new_params

                        new_cmds = {}
                        for cmd in iface.get('commands', []):
                            cname, cmd = self._resolve('Command', cmd)
                            new_cmds[cname] = cmd  # TODO multiple versions
                        iface['commands'] = new_cmds

                        new_props = {}
                        for prop in iface.get('properties', []):
                            pname, prop = self._resolve('Property', prop)
                            new_props[pname] = prop  # TODO multiple versions
                        iface['properties'] = new_props

                    # TODO: check for duplicate interfaces
                    inv.setdefault('Interface', {})[name] = iface  # TODO multiple versions

                for ref in repo['features']:
                    name, feat = self._resolve('Feature', ref)

                    with self.with_context('Feature', name):
                        new_params = {}
                        for param in feat.get('parameters', []):
                            pname, param = self._resolve('Parameter', param)
                            new_params[pname] = param  # TODO multiple versions
                        feat['parameters'] = new_params

                        new_cmds = {}
                        for cmd in feat.get('commands', []):
                            cname, cmd = self._resolve('Command', cmd)
                            new_cmds[cname] = cmd  # TODO multiple versions
                        feat['commands'] = new_cmds

                        new_props = {}
                        for prop in feat.get('properties', []):
                            pname, prop = self._resolve('Property', prop)
                            new_props[pname] = prop  # TODO multiple versions
                        feat['properties'] = new_props

                    # TODO: check for duplicates
                    inv.setdefault('Feature', {})[name] = feat  # TODO multiple versions

                for ref in repo['parameters']:
                    name, par = self._resolve('Parameter', ref)

                    with self.with_context('Parameter', name):
                        new_props = {}
                        for prop in par.get('properties', []):
                            pname, prop = self._resolve('Property', prop)
                            new_props[pname] = prop  # TODO multiple versions
                        par['properties'] = new_props

                    # TODO: check for duplicates
                    inv.setdefault('Parameter', {})[name] = par  # TODO multiple versions

                for ref in repo['commands']:
                    name, cmd = self._resolve('Command', ref)

                    with self.with_context('Command', name):
                        new_props = {}
                        for prop in cmd.get('properties', []):
                            pname, prop = self._resolve('Property', prop)
                            new_props[pname] = prop  # TODO multiple versions
                        cmd['properties'] = new_props

                    # TODO: check for duplicates
                    inv.setdefault('Command', {})[name] = cmd  # TODO multiple versions

                for (proptype, props) in repo['properties'].items():
                    for ref in props:
                        name, prop = self._resolve('Property', ref)
                        prop_map.setdefault(proptype, {})[name] = prop  # TODO multiple versions

                for dtype in repo['datainfo']:
                    name, dtype = self._resolve('Datainfo', dtype)
                    inv.setdefault('Datainfo', {})[name] = dtype  # TODO multiple versions

        return Inventory(prop_map, inv)
