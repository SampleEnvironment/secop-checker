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

# ruff: noqa: ANN201

"""Tests for build_line_map and ctx_to_json_path."""

import json
from typing import cast

from secop_check import context as ctx
from secop_check.checker import build_line_map, ctx_to_json_path


def test_build_line_map_empty():
    assert build_line_map('') == {}


def test_build_line_map_simple():
    text = '{\n  "a": 1\n}'
    assert build_line_map(text) == {'a': 1}


def test_build_line_map_nested():
    text = json.dumps({'a': {'b': 1, 'c': 2}}, indent=2)
    assert build_line_map(text) == {'a': 1, 'a.b': 2, 'a.c': 3}


def test_build_line_map_non_matching():
    text = '[\n  1,\n  2\n]'
    assert build_line_map(text) == {}


def test_ctx_to_json_path_empty():
    assert ctx_to_json_path([]) == ''


def test_ctx_to_json_path_module():
    assert ctx_to_json_path([ctx.Module('m1')]) == 'modules.m1'


def test_ctx_to_json_path_param():
    path = cast(list[ctx.ContextItem], [ctx.Module('m1'), ctx.Parameter('value')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.value'


def test_ctx_to_json_path_command():
    path = cast(list[ctx.ContextItem], [ctx.Module('m1'), ctx.Command('reset')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.reset'


def test_ctx_to_json_path_property():
    assert ctx_to_json_path([ctx.Property('visibility')]) == 'visibility'


def test_ctx_to_json_path_datainfo():
    path = cast(list[ctx.ContextItem],
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.Datainfo('struct', '')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.v.datainfo'


def test_ctx_to_json_path_datainfo_named():
    path = cast(list[ctx.ContextItem],
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.Datainfo('struct', 'field_x')])
    assert ctx_to_json_path(path) == \
        'modules.m1.accessibles.v.datainfo.field_x'


def test_ctx_to_json_path_constant():
    path = cast(list[ctx.ContextItem],
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.ConstantValue('')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.v.constant'


def test_ctx_to_json_path_argument():
    path = cast(list[ctx.ContextItem],
                [ctx.Module('m1'), ctx.Command('cmd'),
                 ctx.Argument('')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.cmd.argument'


def test_ctx_to_json_path_result():
    path = cast(list[ctx.ContextItem],
                [ctx.Module('m1'), ctx.Command('cmd'),
                 ctx.Result('')])
    assert ctx_to_json_path(path) == 'modules.m1.accessibles.cmd.result'
