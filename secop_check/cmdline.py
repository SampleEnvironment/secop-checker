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

import argparse
import sys
import traceback

from rich.console import Console

from . import (
    Catastrophe,
    Context,
    Diagnostic,
    DiagnosticBase,
    Severity,
    load_from_node,
)
from .checker import Checker
from .formatting import render_annotated, render_summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('infile', help='input file with descriptive JSON '
                        'or a SEC node address in the form host:port')
    parser.add_argument('-a', '--annotate', action='store_true',
                        help='annotate diagnostics onto pretty-printed JSON')
    parser.add_argument('--json', action='store_true', help='output json')
    parser.add_argument('--version',
                        # TODO: other source
                        choices=['latest', '1.0', '1.1', '2.0'],
                        default='2.0',
                        help='version to check against (default: %(default)s),'
                        ' not used when loading from a node')
    parser.add_argument('--schema', action='append', default=[],
                        help='additional schema repository file to read')
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    version = args.version

    if args.annotate:
        output = 'none'  # we'll print separately afterwards
    elif args.json:
        output = 'json'
    else:
        output = 'text'

    try:
        if ':' in args.infile:
            version, desc = load_from_node(args.infile)
        elif args.infile == '-':
            desc = sys.stdin.read()
        else:
            with open(args.infile, encoding='utf-8') as f:  # noqa: PTH123
                desc = f.read()

        checker = Checker(version, args.schema, output)
        checker.check(desc)
        if args.annotate:
            render_annotated(checker.get_diags(), desc)
        elif output == 'text':
            render_summary(checker.get_diags(), Console())
    except Catastrophe:
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        diag = Diagnostic(
            Severity.CATASTROPHIC, '',
            Context(path=[], traceback=traceback.format_exc()),
            f'The checker encountered an internal error: {e}',
        )
        diag_out = 'json' if output == 'json' else 'text'
        DiagnosticBase(diag_out)._print(diag)  # noqa: SLF001
