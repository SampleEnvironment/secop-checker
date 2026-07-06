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
import json
import sys
import traceback

from rich.console import Console
from rich.highlighter import JSONHighlighter
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from . import (
    _SEVERITY_COLORS,
    Catastrophe,
    Context,
    Diagnostic,
    DiagnosticBase,
    Severity,
    load_from_node,
)
from .checker import Checker, build_line_map, ctx_to_json_path


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



def _render_summary(checker: Checker, console: Console) -> None:
    diags = checker.get_diags()
    if not diags:
        console.print()
        console.print(Panel(
            '[green]No issues found with the description.[/green]',
            title=' Summary ',
            border_style='green'))
        return

    highest = max(d.severity for d in diags)
    border_color = _SEVERITY_COLORS[highest]

    counts = dict.fromkeys(Severity, 0)
    for d in diags:
        counts[d.severity] += 1

    content = Text()
    content.append('Found issues with the description:\n')
    for sev in (Severity.ERROR, Severity.WARNING, Severity.HINT):
        c = counts[sev]
        if not c:
            continue
        if content:
            content.append('   ')
        content.append(f'{sev.name}s: {c}', style=_SEVERITY_COLORS[sev])

    console.print()
    console.print(Panel(content, title=' Summary ',
                        border_style=border_color))


def _render_annotated(checker: Checker, raw_json: str) -> None:
    obj = json.loads(raw_json)
    text = json.dumps(obj, indent=2)
    line_map = build_line_map(text)
    lines = text.splitlines()
    num_width = len(str(len(lines))) + 3

    # Group diagnostics by JSON-path → line
    line_diags: dict[int, list] = {}
    for d in checker.get_diags():
        path = ctx_to_json_path(d.ctx.path)
        if path not in line_map:
            continue
        line = line_map[path]
        line_diags.setdefault(line + 1, []).append(d)

    highlighter = JSONHighlighter()
    console = Console(theme=Theme({'json.key': 'blue'}))
    sep_prefix = ' ' * (num_width + 1) + '│'
    for i, line_text in enumerate(lines, 1):
        row = Text()
        row.append(f'{i:>{num_width}} │ ', style='dim')
        hl = Text(line_text)
        highlighter.highlight(hl)
        hl.stylize('dim')
        row.append(hl)
        console.print(row)
        if i in line_diags:
            leading = len(line_text) - len(line_text.lstrip())
            for d in line_diags[i]:
                sev_color = _SEVERITY_COLORS[d.severity]
                ann = Text()
                ann.append('●', style=sev_color)
                ann.append(' ' * num_width + '│' + ' ' * (leading + 1),
                           style='dim')
                ann.append(f'╰─ {d.severity.name}', style=f'bold {sev_color}')
                if d.step:
                    ann.append(f' [{d.step}]')
                ann.append(f': {d.msg}',
                           style=sev_color)
                console.print(ann)
            console.print(sep_prefix, style='dim')
    _render_summary(checker, console)


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
            _render_annotated(checker, desc)
        elif output == 'text':
            _render_summary(checker, Console())
    except Catastrophe:
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        diag = Diagnostic(
            Severity.CATASTROPHIC, '',
            Context(path=[], traceback=traceback.format_exc()),
            f'The checker encountered an error: {e}',
        )
        DiagnosticBase(output)._print(diag)  # noqa: SLF001
