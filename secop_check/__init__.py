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
import socket
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum


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


class Catastrophe(Exception):  # noqa: N818
    pass


class DiagnosticBase:
    def __init__(self, output):
        self._output = output
        self._diags = []
        self._step = ''
        self._context = Context(path=[])
        self._out = sys.stdout

    def get_diags(self):
        return self._diags

    def set_diags(self, diags):
        self._diags = diags

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
        if self._output == 'json':
            self._out.write(json.dumps({
                'severity': diag.severity.name,
                'step': diag.step,
                'msg': diag.msg,
                'ctx': diag.ctx.path,
            }))
            self._out.write('\n')
        elif self._output == 'text':
            step = f' [{diag.step}]' if diag.step else ''
            ctx = ' / '.join(f'{ty} {name}'.strip()
                             for ty, name in diag.ctx.path).strip()
            if ctx:
                ctx += ': '
            self._out.write(f'{diag.severity.name}{step}: {ctx}{diag.msg}\n')


def load_from_node(addr):
    addr = addr.removeprefix('tcp://')
    host, port = addr.split(':')
    port = int(port)

    with socket.create_connection((host, port)) as s:
        with s.makefile('rw') as sf:
            sf.write('*IDN?\n')
            sf.write('describe\n')
            sf.flush()
            idn = sf.readline()
            ver = idn.strip().split(',')[-1].strip('vV')
            desc = sf.readline()

    return ver, desc
