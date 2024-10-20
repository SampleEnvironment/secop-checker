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


class Catastrophe(Exception):
    pass


class DiagnosticBase:
    def __init__(self, output):
        self._output = output
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
        if self._output == 'json':
            print(json.dumps({
                'severity': diag.severity.name,
                'step': diag.step,
                'msg': diag.msg,
                'ctx': diag.ctx.path,
            }))
        elif self._output == 'text':
            step = f' [{diag.step}]' if diag.step else ''
            ctx = ' / '.join(f'{ty} {name}'.strip()
                             for ty, name in diag.ctx.path).strip()
            if ctx:
                ctx += ': '
            print(f'{diag.severity.name}{step}: {ctx}{diag.msg}')
