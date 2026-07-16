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

import json
import re

from rich.console import Console
from rich.highlighter import JSONHighlighter
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from . import Diagnostic, Severity
from . import context as ctx

_SEVERITY_BORDER = {
    Severity.HINT: 'dim',
    Severity.WARNING: 'yellow',
    Severity.ERROR: 'red',
    Severity.CATASTROPHIC: 'bold red',
}

_SEVERITY_COLORS = {
    Severity.HINT: 'color(44)',
    Severity.WARNING: 'color(142)',
    Severity.ERROR: 'color(196)',
    Severity.CATASTROPHIC: 'bold color(88)',
}


def print_diag_panel(diag: Diagnostic, console: Console) -> None:
    step = diag.step
    ctx = ' / '.join(str(item) for item in diag.ctx.path).strip()
    content = Text()
    if step:
        content.append(f'[{step}] ', style='bold')
    if ctx:
        content.append(ctx)
        content.append('\n\n')
    content.append(diag.msg)
    if diag.ctx.traceback:
        content.append('\n\n')
        content.append(diag.ctx.traceback, style='color(244)')
    console.print(Panel(
        content,
        title=f' {diag.severity.name} ',
        border_style=_SEVERITY_BORDER[diag.severity],
        padding=(0, 1),
    ))


def _build_line_map(
    text: str,
) -> tuple[dict[tuple[str, ...], int], list[tuple[int, int]]]:
    lines = text.splitlines()
    path: list[str] = []
    stack: list[str] = []
    line_map: dict[tuple[str, ...], int] = {}
    last_on_indent = {}
    ranges = []
    prev_indent = 0
    for i, line in enumerate(lines):
        indent = (len(line) - len(line.lstrip())) // 2
        if indent > prev_indent:
            last_on_indent[prev_indent] = i - 1
        elif indent < prev_indent:
            first_line = last_on_indent[indent]
            last_line = i - 1
            ranges.append((first_line, last_line))

        m = re.match(r'^(\s*)"([^"]+)":', line)
        if m:
            key = m.group(2)
            path[-1] = key
            line_map[tuple(path)] = i
        if line.endswith('['):
            stack.append('l')
            path.append('0')
            line_map[tuple(path)] = i + 1
        elif line.endswith('{'):
            stack.append('d')
            path.append('')
        if line.endswith(('[]', '[],', '{}', '{},')):
            pass
        elif line.endswith((']', '],', '}', '},')):
            stack.pop()
            path.pop()
        if line.endswith(',') and stack[-1] == 'l':
            path[-1] = str(int(path[-1]) + 1)
            line_map[tuple(path)] = i + 1

        prev_indent = indent

    return line_map, ranges


def _ctx_to_json_path(ctxpath: list[ctx.ContextItem]) -> tuple[str, ...]:
    parts: list[str] = []
    for item in ctxpath:
        if isinstance(item, ctx.Module):
            parts += ['modules', item.name]
        elif isinstance(item, ctx.System):
            parts += ['systems', item.name]
        elif isinstance(item, (ctx.Parameter, ctx.Command)):
            parts += ['accessibles', item.name]
        elif isinstance(item, (ctx.Property, ctx.Index, ctx.Item)):
            parts.append(item.name)
        elif isinstance(item, ctx.ConstantValue):
            parts.append('constant')
        elif isinstance(item, ctx.Argument):
            parts.append('argument')
        elif isinstance(item, ctx.Result):
            parts.append('result')
        elif isinstance(item, ctx.Datainfo) and item.name:
            parts.append(item.name)
    return tuple(parts)


def get_annotated_display(diags: list[Diagnostic], raw_json: str) -> \
        tuple[list[str], dict[int, list], list, list[tuple[int, int]]]:
    obj = json.loads(raw_json)
    text = json.dumps(obj, indent=2)
    line_map, ranges = _build_line_map(text)
    lines = text.splitlines()

    # Group diagnostics by JSON-path → line
    line_diags: dict[int, list] = {}
    unmatched = []
    for d in diags:
        path = _ctx_to_json_path(d.ctx.path)
        while path and path not in line_map:
            path = path[:-1]
        if not path:
            unmatched.append(d)
            continue
        line = line_map[path]
        line_diags.setdefault(line + 1, []).append(d)

    return lines, line_diags, unmatched, ranges


def render_summary(diags: list[Diagnostic], console: Console) -> None:
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


def render_annotated(diags: list[Diagnostic], raw_json: str) -> None:
    lines, line_diags, unmatched, _ranges = get_annotated_display(diags, raw_json)
    num_width = len(str(len(lines))) + 3
    highlighter = JSONHighlighter()
    console = Console(theme=Theme({'json.key': 'blue'}))

    for d in unmatched:
        print_diag_panel(d, console)

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
    render_summary(diags, console)
