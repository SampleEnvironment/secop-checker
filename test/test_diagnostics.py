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

# ruff: noqa: ANN201  -- pytest test methods don't need -> None

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from secop_check import Catastrophe, Severity
from secop_check import Diagnostic as Diag
from secop_check.checker import Checker, desc_dict
from secop_check.context import SECNode as CtxSECNode

ERROR = Severity.ERROR
WARNING = Severity.WARNING
HINT = Severity.HINT
CATASTROPHIC = Severity.CATASTROPHIC

# helpers

def check(desc: dict, schema_path: str | None = None,
          version: str = '1.1') -> list[Diag]:
    c = Checker(version, [] if schema_path is None else [schema_path],
                output='text')
    c.check(json.dumps(desc))
    return c.get_diags()


# base dicts

NODE_PROPS = {
    'equipment_id': 'x',
    'firmware': 'x',
    'description': 'x',
}

MIN_NODE: dict[str, Any] = {
    'modules': {
        'm': {
            'accessibles': {},
            'description': 'x',
            'interface_classes': [],
            'features': [],
            'implementation': 'x',
        },
    },
    **NODE_PROPS,
}

COMM_ACS: dict[str, Any] = {
    'communicate': {'description': 'talk', 'datainfo': {'type': 'command'}},
}

READ_ACS: dict[str, Any] = {
    'value': {
        'description': 'x',
        'datainfo': {'type': 'double', 'unit': 'K'},
        'readonly': True,
    },
    'status': {
        'description': 's',
        'datainfo': {
            'type': 'tuple',
            'members': [
                {'type': 'enum', 'members': {'IDLE': 100, 'ERROR': 400}},
                {'type': 'string'},
            ],
        },
        'readonly': True,
    },
}

MOD_BASE = {
    'description': 'x', 'features': [], 'implementation': 'x',
}

COMMUNICATOR: dict[str, Any] = {
    'modules': {'m': {'accessibles': COMM_ACS,
                      'interface_classes': ['Communicator'],
                      **MOD_BASE}},
    **NODE_PROPS,
}

DRIVABLE_MOD = {
    'accessibles': {
        'value': READ_ACS['value'],
        'status': READ_ACS['status'],
        'target': {
            'description': 't',
            'datainfo': {'type': 'double', 'unit': 'K'},
            'readonly': False,
        },
        'stop': {'description': 'stop', 'datainfo': {'type': 'command'}},
    },
    'interface_classes': ['Drivable'],
    **MOD_BASE,
}

READABLE_MOD = {
    'accessibles': READ_ACS,
    'interface_classes': ['Readable'],
    **MOD_BASE,
}

READABLE_NODE: desc_dict = {
    'modules': {'m': READABLE_MOD}, **NODE_PROPS}
DRIVABLE_NODE: desc_dict = {
    'modules': {'m': DRIVABLE_MOD}, **NODE_PROPS}



def assert_has(diags: list[Diag],
               *expected: tuple[Severity, str, str]) -> None:
    """Assert exactly `expected` diagnostics are present (and nothing else).

    Each element is (severity, msg, ctx).
    """
    unmatched = list(diags)
    for sev, msg, ctx in expected:
        for i, d in enumerate(unmatched):
            d_path = [p for p in d.ctx.path if not isinstance(p, CtxSECNode)]
            d_ctx = ':'.join(str(p) for p in d_path).strip()
            if d.severity is sev and msg in d.msg and ctx == d_ctx:
                unmatched.pop(i)
                break
        else:
            raise AssertionError(
                f'expected diagnostic ({sev}, {msg!r}) not found. '
                f'Got: {[(d.severity.name, d.msg) for d in diags]}')
    if unmatched:
        raise AssertionError(
            'unexpected diagnostics: ' +
            ', '.join(f'{d.severity.name}:{d.msg!r}' for d in unmatched))


HERE = Path(__file__).parent
FORCED_VALUE_FIXTURE = str(HERE / 'data' / 'test_forced_value.yaml')
COMPOUND_DI_FIXTURE = str(HERE / 'data' / 'test_compound_datainfo_types.yaml')


class TestCheckEntryPoint:
    def test_invalid_json_catastrophic(self):
        c = Checker('1.1', [], output='text')
        with pytest.raises(Catastrophe):
            c.check('not json')

    def test_minimal_valid_no_diags(self):
        assert len(check(MIN_NODE)) == 0


class TestBasicStructure:
    def test_missing_modules(self):
        d = deepcopy(MIN_NODE)
        del d['modules']
        assert_has(check(d), (ERROR, 'missing dict of modules', ''))

    def test_missing_accessibles(self):
        d = deepcopy(MIN_NODE)
        del d['modules']['m']['accessibles']
        assert_has(check(d), (ERROR, 'missing dict of module accessibles',
                              'Module m'))


class TestNames:
    def test_bad_module_name(self):
        d = deepcopy(MIN_NODE)
        d['modules']['9bad'] = d['modules'].pop('m')
        assert_has(check(d), (ERROR, 'does not match required module name format',
                              'Module 9bad'))

    def test_bad_param_name(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            '9bad': {'description': 'x', 'datainfo': {'type': 'double'},
                     'readonly': True},
        }
        assert_has(check(d),
                   (ERROR, 'does not match required parameter name format',
                    'Module m:Parameter 9bad'),
                   (WARNING, "non-standard parameters need '_' as a prefix",
                    'Module m:Parameter 9bad'))

    def test_bad_command_name(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            '9bad': {'description': 'x', 'datainfo': {'type': 'command'}},
        }
        assert_has(check(d),
                   (ERROR, 'does not match required command name format',
                    'Module m:Command 9bad'),
                   (WARNING, "non-standard commands need '_' as a prefix",
                    'Module m:Command 9bad'))

    def test_bad_property_name(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['9bad'] = 'x'
        assert_has(check(d),
                   (ERROR, 'does not match required property name format',
                    'Module m:Property 9bad'),
                   (WARNING, "non-standard properties need '_' as a prefix",
                    'Module m:Property 9bad'))


class TestInterfaces:
    def test_unknown_interface(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['interface_classes'] = ['NonExistent']
        assert_has(check(d), (ERROR, "declares unknown Interface: 'NonExistent'",
                              'Module m'))

    def test_unknown_feature(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['features'] = ['NonExistent']
        assert_has(check(d), (ERROR, "declares unknown Feature: 'NonExistent'",
                              'Module m'))

    def test_valid_readable_no_interface_error(self):
        assert len(check(READABLE_NODE)) == 0


class TestBaseProps:
    def test_unknown_node_property(self):
        d = deepcopy(MIN_NODE)
        d['zombie'] = 'blah'
        assert_has(check(d),
                   (WARNING, "non-standard properties need '_' as a prefix",
                    'Property zombie'))

    def test_missing_required_property(self):
        d = deepcopy(MIN_NODE)
        del d['equipment_id']
        assert_has(check(d),
                   (ERROR, "missing required properties: 'equipment_id'", ''))

    def test_wrong_property_type(self):
        d = deepcopy(MIN_NODE)
        d['equipment_id'] = 42
        assert_has(check(d), (ERROR, 'expected string, got 42',
                              'Property equipment_id'))

    def test_forced_value_mismatch(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['testprop'] = 'wrong'
        assert_has(check(d, FORCED_VALUE_FIXTURE),
                   (ERROR, "property has forced value 'must_be_this', got 'wrong'",
                    'Module m:Property testprop'))

    def test_forced_value_correct(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['testprop'] = 'must_be_this'
        diags = check(d, FORCED_VALUE_FIXTURE)
        assert not diags

    def test_unknown_struct_key(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['meaning'] = {'function': 'temperature', 'xxx': 'yyy'}
        assert_has(check(d, version='2.0'),
                   (WARNING, 'unknown struct keys: xxx',
                    'Module m:Property meaning'))


class TestDatainfoStructure:
    def test_empty_datainfo(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {}
        assert_has(check(d),
                   (ERROR, 'datainfo is empty',
                    'Module m:Parameter value:Property datainfo'),
                   (ERROR, "missing required datainfo key 'type'",
                    'Module m:Parameter value'))

    def test_datainfo_no_type(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {'unit': 'K'}
        assert_has(check(d),
                   (ERROR, 'datainfo does not have a type',
                    'Module m:Parameter value:Property datainfo'),
                   (ERROR, "missing required datainfo key 'type'",
                    'Module m:Parameter value'))

    def test_unknown_datainfo_type(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {'type': 'nope'}
        assert_has(check(d), (ERROR, "unknown datainfo type 'nope'",
                              'Module m:Parameter value:Property datainfo'))

    def test_missing_required_dataprop(self):
        """Int datainfo requires min/max; omitting them triggers error."""
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {'type': 'int'}
        assert_has(check(d),
                   (ERROR, "missing required property for datainfo type int: 'min'",
                    'Module m:Parameter value:Property datainfo'),
                   (ERROR, "missing required property for datainfo type int: 'max'",
                    'Module m:Parameter value:Property datainfo'))

    def test_unknown_dataprop(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {
            'type': 'double', 'unit': 'K', 'garbage': 1}
        assert_has(check(d),
                   (WARNING,
                    "unknown properties given for datainfo type double: 'garbage'",
                    'Module m:Parameter value:Property datainfo'))

    def test_bad_enum_in_tuple_members(self):
        """Array(Datainfo): nested datainfo inside tuple is validated."""
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles']['_x'] = {
            'description': 'x',
            'datainfo': {
                'type': 'tuple',
                'members': [
                    {'type': 'enum', 'members': {'IDLE': 100}},
                    {'type': 'enum', 'members': {'BAD': 'not_int'}},
                ],
            },
            'readonly': True,
        }
        assert_has(check(d),
                   (ERROR, "expected struct with str names and values of "
                    "type: integer, got {'BAD': 'not_int'}",
                    'Module m:Parameter _x:Property datainfo'
                    ':datainfo tuple members:datainfo enum members'))

    def test_bad_enum_in_struct_members(self):
        """Struct(fieldtype=Datainfo): nested datainfo inside struct is validated."""
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles']['_x'] = {
            'description': 'x',
            'datainfo': {
                'type': 'struct',
                'members': {
                    'field1': {'type': 'enum', 'members': {'a': 1}},
                    'field2': {'type': 'enum', 'members': {'b': 'bad'}},
                },
            },
            'readonly': True,
        }
        assert_has(check(d),
                   (ERROR, "expected struct with str names and values of "
                    "type: integer, got {'b': 'bad'}",
                    'Module m:Parameter _x:Property datainfo'
                    ':datainfo struct members:datainfo enum members'))

    def test_bad_enum_in_tuple_dataprop(self):
        """Tuple(Datainfo...): datainfo inside tuple-typed dataprop is validated."""
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles']['_x'] = {
            'description': 'x',
            'datainfo': {
                'type': 'test_tuple_di',
                'items': [
                    {'type': 'enum', 'members': {'BAD': 'not_int'}},
                    'some_string',
                ],
            },
            'readonly': True,
        }
        assert_has(check(d, COMPOUND_DI_FIXTURE),
                   (ERROR, "expected struct with str names and values of "
                    "type: integer, got {'BAD': 'not_int'}",
                    'Module m:Parameter _x:Property datainfo'
                    ':datainfo test_tuple_di items:datainfo enum members'))

    def test_bad_enum_in_named_struct_dataprop(self):
        """Struct(fieldtypes=...): validates nested datainfo in named struct."""
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles']['_x'] = {
            'description': 'x',
            'datainfo': {
                'type': 'test_struct_di',
                'items': {
                    'field1': {'type': 'enum', 'members': {'a': 'bad'}},
                    'field2': 'some_string',
                },
            },
            'readonly': True,
        }
        assert_has(check(d, COMPOUND_DI_FIXTURE),
                   (ERROR, "expected struct with str names and values of "
                    "type: integer, got {'a': 'bad'}",
                    'Module m:Parameter _x:Property datainfo'
                    ':datainfo test_struct_di items:datainfo enum members'))


class TestDatainfoTemplate:
    def test_missing_required_datainfo_key(self):
        """Status should have 'members' key; omitting it triggers error."""
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['status']['datainfo'] = {'type': 'tuple'}
        assert_has(check(d),
                   (ERROR,
                    "missing required property for datainfo type tuple: 'members'",
                    'Module m:Parameter status:Property datainfo'),
                   (ERROR, "missing required datainfo key 'members'",
                    'Module m:Parameter status'))

    def test_datainfo_type_mismatch(self):
        """Status should have type 'tuple'; using 'string' triggers error."""
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['status']['datainfo'] = {'type': 'string'}
        assert_has(check(d),
                   (ERROR, "expected datainfo type 'tuple', got 'string'",
                    'Module m:Parameter status'))

    def test_datainfo_nested_type_mismatch(self):
        """Status members[0] should be 'enum'; using 'string' triggers error."""
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['status']['datainfo'] = {
            'type': 'tuple',
            'members': [
                {'type': 'string'},
                {'type': 'string'},
            ],
        }
        assert_has(check(d), (ERROR,
                              "expected datainfo type 'enum', got 'string'",
                              'Module m:Parameter status'))

    def test_pollinterval_type_mismatch(self):
        """Pollinterval should have {type: double}; string triggers error."""
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            'value': READ_ACS['value'],
            'status': READ_ACS['status'],
            'pollinterval': {
                'description': 'p',
                'datainfo': {'type': 'string'},
                'readonly': False,
            },
        }
        d['modules']['m']['interface_classes'] = ['Readable']
        assert_has(check(d), (ERROR,
                              "expected datainfo type 'double', got 'string'",
                              'Module m:Parameter pollinterval'))

    def test_datainfo_any_pass(self):
        """'any' type should not raise template validation errors."""
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['datainfo'] = {'type': 'any'}
        diags = check(d)
        assert not any('expected datainfo' in d.msg for d in diags)


class TestParameterChecks:
    def test_missing_required_param(self):
        d = deepcopy(READABLE_NODE)
        del d['modules']['m']['accessibles']['status']
        assert_has(check(d),
                   (ERROR, 'missing required parameter status from Interface Readable',
                    'Module m'))

    def test_nonstandard_param_no_prefix(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['extra'] = {
            'description': 'e', 'datainfo': {'type': 'double'},
            'readonly': True}
        assert_has(check(d), (WARNING, "non-standard parameters need '_' as a prefix",
                              'Module m:Parameter extra'))

    def test_nonstandard_param(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['_extra'] = {
            'description': 'e', 'datainfo': {'type': 'double'},
            'readonly': True}
        diags = check(d)
        assert not diags

    def test_constant_not_readonly(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['constant'] = 42.0
        d['modules']['m']['accessibles']['value']['readonly'] = False
        assert_has(check(d),
                   (WARNING, 'constant parameters should be readonly',
                    'Module m:Parameter value'),
                   (WARNING, 'parameter should be readonly',
                    'Module m:Parameter value'))

    def test_constant_wrong_type(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['constant'] = 'not a number'
        assert_has(check(d), (ERROR, "expected double, got 'not a number'",
                              'Module m:Parameter value:constant value'))

    def test_readonly_mismatch_should_be_readonly(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['accessibles']['value']['readonly'] = False
        assert_has(check(d), (WARNING, 'parameter should be readonly',
                              'Module m:Parameter value'))

    def test_readonly_mismatch_should_not_be_readonly(self):
        d = deepcopy(READABLE_NODE)
        d['modules']['m']['interface_classes'] = ['Writable']
        d['modules']['m']['accessibles']['target'] = {
            'description': 't', 'datainfo': {'type': 'double', 'unit': 'K'},
            'readonly': True}
        assert_has(check(d), (WARNING, 'parameter should not be readonly',
                              'Module m:Parameter target'))


class TestCommandChecks:
    def test_missing_required_command(self):
        d = deepcopy(DRIVABLE_NODE)
        del d['modules']['m']['accessibles']['stop']
        assert_has(check(d),
                   (ERROR, 'missing required command stop from Interface Drivable',
                    'Module m'))

    def test_nonstandard_command_no_prefix(self):
        d = deepcopy(DRIVABLE_NODE)
        d['modules']['m']['accessibles']['mycmd'] = {
            'description': 'c', 'datainfo': {'type': 'command'}}
        assert_has(check(d), (WARNING, "non-standard commands need '_' as a prefix",
                              'Module m:Command mycmd'))

    def test_cmd_unexpected_argument(self):
        d = deepcopy(DRIVABLE_NODE)
        d['modules']['m']['accessibles']['stop']['datainfo'] = {
            'type': 'command', 'argument': {'type': 'double'}}
        assert_has(check(d), (WARNING, 'command should not have an argument',
                              'Module m:Command stop'))

    def test_cmd_unexpected_result(self):
        d = deepcopy(DRIVABLE_NODE)
        d['modules']['m']['accessibles']['stop']['datainfo'] = {
            'type': 'command', 'result': {'type': 'double'}}
        assert_has(check(d), (WARNING, 'command should not have a result',
                              'Module m:Command stop'))

    def test_cmd_missing_arg_and_result(self):
        assert_has(check(COMMUNICATOR),
                   (WARNING, "command should have an argument: {'type': 'string'}",
                    'Module m:Command communicate'),
                   (WARNING, "command should have a result: {'type': 'string'}",
                    'Module m:Command communicate'))


class TestPostfixedParams:
    def test_missing_base_param(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            'value_min': {
                'description': 'vmin',
                'datainfo': {'type': 'double', 'unit': 'K'},
                'readonly': False,
            },
        }
        assert_has(check(d, version='2.0'),
                   (ERROR, "postfixed parameter 'value_min' requires "
                    "non-postfixed parameter 'value'",
                    'Module m:Parameter value_min'),
                   (ERROR, "expected datainfo type 'parent', got 'double'",
                    'Module m:Parameter value_min'))

    def test_wrong_datatype(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            'value': {
                'description': 'value',
                'datainfo': {'type': 'double', 'unit': 'K'},
                'readonly': True,
            },
            'value_min': {
                'description': 'vmin',
                'datainfo': {'type': 'int', 'unit': 'K', 'min': 0, 'max': 1},
                'readonly': False,
            },
        }
        assert_has(check(d, version='2.0'),
                   (ERROR, "expected datainfo type 'double', got 'int'",
                    'Module m:Parameter value_min'))

    def test_valid_postfixed_param(self):
        d = deepcopy(MIN_NODE)
        d['modules']['m']['accessibles'] = {
            'value': READ_ACS['value'],
            'value_min': {
                'description': 'vmin',
                'datainfo': {'type': 'double', 'unit': 'K'},
                'readonly': False,
            },
            'status': READ_ACS['status'],
        }
        d['modules']['m']['interface_classes'] = ['Readable']
        diags = check(d, version='2.0')
        assert not diags
