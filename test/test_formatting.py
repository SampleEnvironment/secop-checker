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
from secop_check.formatting import _build_line_map as build_line_map
from secop_check.formatting import _ctx_to_json_path


def test_build_line_map_empty():
    lm, r = build_line_map('')
    assert lm == {}
    assert r == []


def test_build_line_map_simple():
    text = '{\n  "a": 1\n}'
    lm, r = build_line_map(text)
    assert lm == {('a',): 1}
    assert r == [(0, 1)]


def test_build_line_map_nested():
    text = json.dumps({'a': {'b': 1, 'c': 2}}, indent=2)
    lm, r = build_line_map(text)
    assert lm == {('a',): 1, ('a', 'b'): 2, ('a', 'c'): 3}
    assert r == [(1, 3), (0, 4)]


def test_build_line_map_with_array():
    text = json.dumps({'items': [1, 2, 3]}, indent=2)
    lm, r = build_line_map(text)
    assert lm == {('items',): 1, ('items', '0'): 2,
                  ('items', '1'): 3, ('items', '2'): 4}
    assert r == [(1, 4), (0, 5)]


def test_build_line_map_array_of_objects():
    text = json.dumps({'items': [{'name': 'a'}, {'name': 'b'}]}, indent=2)
    lm, r = build_line_map(text)
    assert lm == {('items',): 1, ('items', '0'): 2,
                  ('items', '0', 'name'): 3,
                  ('items', '1'): 5,
                  ('items', '1', 'name'): 6}
    assert r == [(2, 3), (5, 6), (1, 7), (0, 8)]


def joined_ctx(p: list) -> str:
    return '.'.join(_ctx_to_json_path(p))


def test_ctx_to_json_path_empty():
    assert joined_ctx([]) == ''


def test_ctx_to_json_path_module():
    assert joined_ctx([ctx.Module('m1')]) == 'modules.m1'


def test_ctx_to_json_path_param():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Parameter('value')])
    assert joined_ctx(path) == 'modules.m1.accessibles.value'


def test_ctx_to_json_path_command():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Command('reset')])
    assert joined_ctx(path) == 'modules.m1.accessibles.reset'


def test_ctx_to_json_path_property():
    assert joined_ctx([ctx.Property('visibility')]) == 'visibility'


def test_ctx_to_json_path_datainfo():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.Datainfo('struct', 'blah')])
    assert joined_ctx(path) == 'modules.m1.accessibles.v.blah'


def test_ctx_to_json_path_datainfo_named():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.Datainfo('struct', 'field_x')])
    assert joined_ctx(path) == \
        'modules.m1.accessibles.v.field_x'


def test_ctx_to_json_path_constant():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Parameter('v'),
                 ctx.ConstantValue('')])
    assert joined_ctx(path) == 'modules.m1.accessibles.v.constant'


def test_ctx_to_json_path_argument():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Command('cmd'),
                 ctx.Argument('')])
    assert joined_ctx(path) == 'modules.m1.accessibles.cmd.argument'


def test_ctx_to_json_path_result():
    path = cast('list[ctx.ContextItem]',
                [ctx.Module('m1'), ctx.Command('cmd'),
                 ctx.Result('')])
    assert joined_ctx(path) == 'modules.m1.accessibles.cmd.result'
