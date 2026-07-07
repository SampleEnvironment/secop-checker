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

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from . import DiagnosticBase, Severity
from . import context as ctx
from .dataty import Array as DatatyArray
from .dataty import Datainfo as DatatyDatainfo
from .dataty import Struct as DatatyStruct
from .dataty import Tuple as DatatyTuple
from .schema import Command, Datainfo, Inventory, Loader, Parameter, Property
from .visitors import VISITORS, BaseVisitor

if TYPE_CHECKING:
    from .dataty import Dataty

desc_dict = dict[str, Any]
source = str | None


def build_line_map(text: str) -> dict[str, int]:
    lines = text.splitlines()
    path: list[str] = []
    line_map: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)"([^"]+)":', line)
        if not m:
            continue
        key = m.group(2)
        depth = len(m.group(1)) // 2
        while len(path) >= depth:
            path.pop()
        path.append(key)
        line_map['.'.join(path)] = i
    return line_map


def ctx_to_json_path(ctxpath: list[ctx.ContextItem]) -> str:
    parts: list[str] = []
    for item in ctxpath:
        if isinstance(item, ctx.Module):
            parts += ['modules', item.name]
        elif isinstance(item, ctx.Property):
            parts.append(item.name)
        elif isinstance(item, (ctx.Parameter, ctx.Command)):
            parts += ['accessibles', item.name]
        elif isinstance(item, ctx.ConstantValue):
            parts.append('constant')
        elif isinstance(item, ctx.Argument):
            parts.append('argument')
        elif isinstance(item, ctx.Result):
            parts.append('result')
        elif isinstance(item, ctx.System):
            parts += ['systems', item.name]
        elif isinstance(item, ctx.Datainfo):
            parts.append('datainfo')
            if item.name:
                parts.append(item.name)
    return '.'.join(parts)


class Checker(DiagnosticBase):
    def __init__(self, version: str, additional: list[str], output: str) -> None:
        super().__init__(output)

        self.loader = Loader(Path(__file__).parent / 'defs', output)
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
            raise self.emit_catastrophic(
                f'invalid json at line {e.lineno} column {e.colno}:\n{e.msg}') \
                from None

        schemata = desc_obj.get('schemata', [])
        for uri in schemata:
            self.loader.load_repo(uri)

        if self._diags:
            raise self.emit_catastrophic('found errors loading spec to '
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

    def check_dataty(self, dataty: Dataty, actual: object) -> None:
        if not dataty.validate(actual):
            self.emit(Severity.ERROR,
                      f'expected {dataty.describe()}, got {actual!r}')
            return
        if isinstance(dataty, DatatyDatainfo):
            self.check_datainfo(cast('dict', actual))
        elif isinstance(dataty, DatatyArray) \
                and isinstance(dataty.itemtype, DatatyDatainfo):
            items = cast('list', actual)
            for item in items:
                self.check_datainfo(cast('dict', item))
        elif isinstance(dataty, DatatyTuple) and dataty.itemtypes:
            items = cast('list', actual)
            for itemtype, item in zip(dataty.itemtypes, items,
                                      strict=False):
                if isinstance(itemtype, DatatyDatainfo):
                    self.check_datainfo(cast('dict', item))
        elif isinstance(dataty, DatatyStruct):
            actual_dict = cast('dict', actual)
            if dataty.fieldtype is not None \
                    and isinstance(dataty.fieldtype, DatatyDatainfo):
                for val in actual_dict.values():
                    self.check_datainfo(cast('dict', val))
            elif dataty.fieldtypes:
                unknown = set(actual_dict) - set(dataty.fieldtypes)
                if unknown:
                    self.emit(Severity.WARNING,
                              f'unknown struct keys: '
                              f'{", ".join(sorted(unknown))}')
                for key, fieldtype in dataty.fieldtypes.items():
                    if isinstance(fieldtype, DatatyDatainfo) \
                            and key in actual_dict:
                        self.check_datainfo(cast('dict', actual_dict[key]))

    def check_datainfo(self, description: desc_dict) -> None:
        """Check validity of a datainfo description."""
        if not description:
            self.emit(Severity.ERROR, 'datainfo is empty')
            return
        if 'type' not in description:
            self.emit(Severity.ERROR, 'datainfo does not have a type')
            return

        descty = description['type']

        # handle commands recursively
        if descty == 'command':
            if 'argument' in description:
                with self.with_context(ctx.Argument()):
                    self.check_datainfo(description['argument'])
            if 'result' in description:
                with self.with_context(ctx.Result()):
                    self.check_datainfo(description['result'])
            return

        basic = self._inv.get(Datainfo, descty)
        if basic is None:
            self.emit(Severity.ERROR, f'unknown datainfo type {descty!r}')
            return

        actual_dprops = set(description) - {'type'}
        for dprop, dpropdesc in basic.dataprops.items():
            if dprop not in actual_dprops:
                if not dpropdesc.optional:
                    self.emit(Severity.ERROR,
                              'missing required property for datainfo type '
                              f'{descty}: {dprop!r}')
            else:
                with self.with_context(ctx.Datainfo(descty, dprop)):
                    self.check_dataty(dpropdesc.dataty, description[dprop])
            actual_dprops.discard(dprop)

        if actual_dprops:
            self.emit(Severity.WARNING,
                      'unknown properties given for datainfo type '
                      f"{descty}: {', '.join(map(repr, actual_dprops))}")

    def visit_descriptive_data(self, desc: desc_dict) -> None:
        for visitorcls in VISITORS:
            self._step = visitorcls.name
            self.visit_with(desc, visitorcls(self))

    def visit_with(self, desc: desc_dict, visitor: BaseVisitor) -> None:
        # TODO: better context for the SECNode itself, e.g. the file/host
        with self.with_context(ctx.SECNode()):
            visitor.visit_secnode(desc)

            for prop, propdesc in desc.items():
                if prop == 'modules':
                    for module, moddesc in propdesc.items():
                        with self.with_context(ctx.Module(module)):
                            self._visit_module(module, moddesc, visitor)

                elif prop == 'systems':
                    # handled by SystemChecker in visit_secnode
                    pass

                # other node properties
                else:
                    with self.with_context(ctx.Property(prop)):
                        visitor.visit_property('SECNode', prop, propdesc)

            visitor.finish()

    def _visit_module(self, modname: str, moddesc: desc_dict,
                      visitor: BaseVisitor) -> None:
        visitor.visit_module(modname, moddesc)

        for prop, propdesc in moddesc.items():
            if prop == 'accessibles':
                for accname, accdesc in propdesc.items():
                    datainfo = accdesc.get('datainfo', {})
                    is_command = datainfo.get('type') == 'command'
                    ty = 'Command' if is_command else 'Parameter'
                    ctx_item = ctx.Command(accname) if is_command \
                        else ctx.Parameter(accname)
                    with self.with_context(ctx_item):
                        if is_command:
                            visitor.visit_command(modname, accname, accdesc)
                        else:
                            visitor.visit_parameter(modname, accname, accdesc)

                        for aprop, apropdesc in accdesc.items():
                            with self.with_context(ctx.Property(aprop)):
                                visitor.visit_property(ty, aprop, apropdesc)

                        visitor.finish_accessible(accdesc)

            # other module properties
            else:
                with self.with_context(ctx.Property(prop)):
                    visitor.visit_property('Module', prop, propdesc)

            visitor.finish_module(modname)
