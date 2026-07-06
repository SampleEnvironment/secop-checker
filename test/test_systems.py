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

from copy import deepcopy
from pathlib import Path

from secop_check import Severity

from .test_diagnostics import (
    MIN_NODE,
    NODE_PROPS,
    READABLE_MOD,
    assert_has,
    check,
)

HERE = Path(__file__).parent
ERROR = Severity.ERROR
WARNING = Severity.WARNING

SYSTEM_FIXTURE = str(HERE / 'data' / 'test_system.yaml')
TEMP_SYSTEMS_FIXTURE = str(HERE / 'data' / 'test_temp_systems.yaml')


class TestSystems:
    """Tests for the SystemChecker visitor."""

    def test_empty_systems(self):
        """Empty systems dict produces no diagnostics."""
        d = deepcopy(MIN_NODE)
        d['systems'] = {}
        assert len(check(d, version='2.0')) == 0

    def test_valid_system(self):
        """Valid system with all required modules mapped passes."""
        d = {
            'modules': {
                'my_main': READABLE_MOD,
                'my_extra': READABLE_MOD,
            },
            'systems': {
                'test': {
                    'description': 'a test system',
                    'system': 'TestSystem:1',
                    'modules': {
                        'main': 'my_main',
                        'extra': 'my_extra',
                    },
                },
            },
            **NODE_PROPS,
        }
        diags = check(d, SYSTEM_FIXTURE, version='2.0')
        assert not diags

    def test_valid_system_optional_missing(self):
        """Optional module not mapped is OK."""
        d = {
            'modules': {
                'my_main': READABLE_MOD,
            },
            'systems': {
                'test': {
                    'description': 'a test system',
                    'system': 'TestSystem:1',
                    'modules': {
                        'main': 'my_main',
                    },
                },
            },
            **NODE_PROPS,
        }
        diags = check(d, SYSTEM_FIXTURE, version='2.0')
        assert not diags

    def test_system_entry_not_dict(self):
        """Non-dict system entry is an error."""
        d = deepcopy(MIN_NODE)
        d['systems'] = {'bad': 'not a dict'}
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, 'systems entry must be a dict', 'System bad'))

    def test_missing_system_key(self):
        """System entry without 'system' key is an error."""
        d = deepcopy(MIN_NODE)
        d['systems'] = {'bad': {'modules': {}}}
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, "missing required key 'system'", 'System bad'))

    def test_bad_system_reference(self):
        """Reference to non-existent system is an error."""
        d = {
            'modules': {},
            'systems': {
                'test': {
                    'description': 'x',
                    'system': 'NoSuchSystem:42',
                    'modules': {},
                },
            },
            **NODE_PROPS,
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, "references unknown system 'NoSuchSystem:42'",
                    'System test'))

    def test_system_name_clash(self):
        """System name clashing with module name is an error."""
        d = deepcopy(MIN_NODE)
        d['modules']['my_main'] = {
            'accessibles': {},
            'description': 'x', 'interface_classes': [],
            'features': [], 'implementation': 'x',
        }
        d['systems'] = {
            'my_main': {
                'description': 'x',
                'system': 'TestSystem:1',
                'modules': {'main': 'my_main'},
            },
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, 'system name clashes with existing module',
                    'System my_main'),
                   (ERROR, "requires interface 'Readable'",
                    'System my_main:Module main'))

    def test_missing_required_module(self):
        """Required module not in mapping is an error."""
        d = {
            'modules': {},
            'systems': {
                'test': {
                    'description': 'x',
                    'system': 'TestSystem:1',
                    'modules': {},
                },
            },
            **NODE_PROPS,
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, "missing required module 'main' in "
                    "'modules' mapping", 'System test'))

    def test_module_maps_to_nonexistent(self):
        """Module mapping points to non-existent module name."""
        d = {
            'modules': {},
            'systems': {
                'test': {
                    'description': 'x',
                    'system': 'TestSystem:1',
                    'modules': {'main': 'no_such_mod'},
                },
            },
            **NODE_PROPS,
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, "module 'main' maps to non-existent "
                    "module 'no_such_mod'", 'System test'))

    def test_extra_module_mapping(self):
        """Extra entries in modules mapping produce a warning."""
        d = {
            'modules': {
                'my_main': READABLE_MOD,
            },
            'systems': {
                'test': {
                    'description': 'x',
                    'system': 'TestSystem:1',
                    'modules': {
                        'main': 'my_main',
                        'ghost': 'my_main',
                    },
                },
            },
            **NODE_PROPS,
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (WARNING, "module 'ghost' is not defined in system "
                    "'TestSystem:1'", 'System test'),
        )

    def test_modules_not_a_dict(self):
        """Non-dict modules value is an error."""
        d = deepcopy(MIN_NODE)
        d['systems'] = {
            'test': {
                'description': 'x',
                'system': 'TestSystem:1',
                'modules': 'not_a_dict',
            },
        }
        assert_has(check(d, SYSTEM_FIXTURE, version='2.0'),
                   (ERROR, "'modules' in systems must be a dict",
                    'System test'))


STATUS_ACS = {
    'description': 's',
    'datainfo': {
        'type': 'tuple',
        'members': [
            {'type': 'enum', 'members': {'IDLE': 100, 'ERROR': 400}},
            {'type': 'string'},
        ],
    },
    'readonly': True,
}


def _valid_te_node() -> dict:
    """Build a valid TemperatureEnvironment SECNode."""
    return {
        'modules': {
            'temperature_reg': {
                'accessibles': {
                    'value': {'description': 'x',
                              'datainfo': {'type': 'double', 'unit': 'K'},
                              'readonly': True},
                    'status': STATUS_ACS,
                    'target': {'description': 't',
                               'datainfo': {'type': 'double', 'unit': 'K'},
                               'readonly': False},
                    'stop': {'description': 's',
                             'datainfo': {'type': 'command'}},
                },
                'interface_classes': ['Drivable'],
                'features': [],
                'implementation': 'x',
                'description': 'x',
                'meaning': {'function': 'temperature_regulation'},
            },
            'temperature_sample': {
                'accessibles': {
                    'value': {'description': 'x',
                              'datainfo': {'type': 'double', 'unit': 'K'},
                              'readonly': True},
                    'status': STATUS_ACS,
                },
                'interface_classes': ['Readable'],
                'features': [],
                'implementation': 'x',
                'description': 'x',
                'meaning': {'function': 'temperature'},
            },
        },
        'systems': {
            'te': {
                'description': 'a temperature environment',
                'system': 'TemperatureEnvironment:0',
                'modules': {
                    'temperature_reg': 'temperature_reg',
                    'temperature_sample': 'temperature_sample',
                },
            },
        },
        **NODE_PROPS,
    }


class TestSystemSpecs:
    """Tests for SystemChecker spec validation."""

    def test_te_valid(self):
        """Valid TE system produces no diagnostics."""
        assert not check(_valid_te_node(), TEMP_SYSTEMS_FIXTURE,
                         version='2.0')

    def test_te_param_wrong_type(self):
        """Parameter datainfo type mismatch on system module."""
        d = _valid_te_node()
        di = d['modules']['temperature_sample']['accessibles']['value']['datainfo']
        di.clear()
        di.update({'type': 'string'})
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, "datainfo type is 'string', expected 'double' "
                    'from system definition',
                    'System te:Module temperature_sample:Parameter value'),
                   (ERROR, "missing datainfo property 'unit' "
                    "(expected 'K' from system definition)",
                    'System te:Module temperature_sample:Parameter value'))

    def test_te_param_wrong_unit(self):
        """Parameter datainfo unit mismatch on system module."""
        d = _valid_te_node()
        di = d['modules']['temperature_sample']['accessibles']['value']['datainfo']
        di['unit'] = 'degC'
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, "datainfo.unit is 'degC', expected 'K' "
                    'from system definition',
                    'System te:Module temperature_sample:Parameter value'))

    def test_te_param_missing_unit(self):
        """Parameter missing required datainfo key on system module."""
        d = _valid_te_node()
        di = d['modules']['temperature_sample']['accessibles']['value']['datainfo']
        del di['unit']
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, "missing datainfo property 'unit' (expected 'K' "
                    'from system definition)',
                    'System te:Module temperature_sample:Parameter value'))

    def test_te_missing_required_param(self):
        """Missing required parameter on system module."""
        d = _valid_te_node()
        del d['modules']['temperature_sample']['accessibles']['value']
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, "parameter is required by the system definition",
                    'System te:Module temperature_sample:Parameter value'),
                   (ERROR, 'missing required parameter value '
                    'from Interface Readable',
                    'Module temperature_sample'))

    def test_te_module_property_wrong(self):
        """Module property forced value mismatch on system module."""
        d = _valid_te_node()
        d['modules']['temperature_sample']['meaning'] = {'function': 'bad'}
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, "value does not match system definition: "
                    "{'function': ('bad', 'temperature')}",
                    'System te:Module temperature_sample:Property meaning'),
                   (ERROR, 'expected struct with fields: function',
                    'Module temperature_sample:Property meaning'))

    def test_te_module_property_extra_keys(self):
        """Module property with valid extra keys beyond forced value is OK."""
        d = _valid_te_node()
        d['modules']['temperature_sample']['meaning'] = {
            'function': 'temperature',
            'importance': 3,
        }
        assert not check(d, TEMP_SYSTEMS_FIXTURE, version='2.0')

    def test_te_module_property_missing(self):
        """Module property missing on system module."""
        d = _valid_te_node()
        del d['modules']['temperature_sample']['meaning']
        assert_has(check(d, TEMP_SYSTEMS_FIXTURE, version='2.0'),
                   (ERROR, 'property does not exist, expected '
                   "{'function': 'temperature'} from system definition",
                   'System te:Module temperature_sample:Property meaning'))
