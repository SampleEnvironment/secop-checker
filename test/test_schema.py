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

# ruff: noqa: ANN001, ANN201  -- pytest fixtures/methods; no type annotations needed

"""Tests for catastrophic errors during schema loading.

Each test asserts that a specific Catastrophe is raised when malformed
YAML or JSON is fed to the loader/checker.
"""

from __future__ import annotations

import json

import pytest

from secop_check import Catastrophe
from secop_check.checker import Checker

# helpers

def _checker_with_yaml(yaml: str, tmp_path, *,
                       name: str = 'repo.yaml') -> Checker:
    """Write *yaml* into *tmp_path*/*name* and create a Checker pointing at it.

    Shortcut for tests that need a single YAML file with everything inline.
    """
    p = tmp_path / name
    p.write_text(yaml)
    return Checker('2.0', [str(p)], output='text')


BASE_REPO = """\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
parameters: []
postfixes: []
commands: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
"""


class TestLoaderCatastrophes:
    """Errors raised during YAML loading (before the Converter)."""

    def test_nonexistent_file(self, tmp_path):
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(tmp_path / 'nope.yaml')], output='text')

    def test_malformed_yaml(self, tmp_path):
        p = tmp_path / 'bad.yaml'
        p.write_text('[unclosed')
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(p)], output='text')

    def test_no_repository(self, tmp_path):
        p = tmp_path / 'bad.yaml'
        p.write_text(
            'kind: Property\nname: x\nversion: 1\ndescription: x\n'
            'dataty: string',
        )
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(p)], output='text')

    def test_multiple_repositories(self, tmp_path):
        p = tmp_path / 'bad.yaml'
        p.write_text('---\n' + BASE_REPO + '---\n' + BASE_REPO.replace(
            'name: test\n', 'name: test2\n',
        ))
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(p)], output='text')

    def test_multiple_repo_versions(self, tmp_path):
        p = tmp_path / 'bad.yaml'
        p.write_text('---\n' + BASE_REPO + '---\n' + BASE_REPO.replace(
            'version: 1\n', 'version: 2\n',
        ))
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(p)], output='text')

    def test_nonexistent_version(self):
        with pytest.raises(Catastrophe):
            Checker('99.9', [], output='text')

    # -- _load_one edge cases ------------------------------------------------

    def test_non_dict_yaml_doc(self, tmp_path):
        """Non-dict YAML doc emits ERROR instead of crashing."""
        p = tmp_path / 'bad.yaml'
        p.write_text('null\n')
        with pytest.raises(Catastrophe):
            Checker('2.0', [str(p)], output='text')

    def test_yaml_item_missing_required_meta(self, tmp_path):
        """Missing description/name/version emits ERROR, not KeyError."""
        p = tmp_path / 'bad.yaml'
        p.write_text("""\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
parameters: []
postfixes: []
commands: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
---
kind: Datainfo
name: broken
version: 1
""")
        c = Checker('2.0', [str(p)], output='text')
        with pytest.raises(Catastrophe):
            c.check('{}')


class TestConverterRepositoryCatastrophes:
    """Errors raised when Converter processes Repository fields via _get."""

    def test_repo_wrong_field_type(self, tmp_path):
        yaml = BASE_REPO.replace('version: 1\n', 'version: "one"\n')
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)

    def test_repo_wrong_field_type_2(self, tmp_path):
        yaml = BASE_REPO.replace('datainfo: []\n', 'datainfo: 0\n')
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)


class TestConverterResolveCatastrophes:
    """Errors raised during reference resolution via _resolve."""

    def test_non_dict_non_str_parameter_ref(self, tmp_path):
        yaml = """\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
postfixes: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
parameters:
  - 42
commands: []
"""
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)

    def test_parameter_ref_without_version(self, tmp_path):
        yaml = """\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
postfixes: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
parameters:
  - badparam
commands: []
"""
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)

    def test_unresolvable_parameter_ref(self, tmp_path):
        yaml = """\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
postfixes: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
parameters:
  - NoSuchParam:1
commands: []
"""
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)

    # -- _resolve dict-path edge cases ---------------------------------------

    def test_empty_dict_reference(self, tmp_path):
        yaml = BASE_REPO.replace('datainfo: []\n',
                                 'datainfo:\n  - {}\n')
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)

    def test_inline_ref_props_not_a_dict(self, tmp_path):
        """Non-dict inline ref props give Catastrophe, not TypeError."""
        yaml = """\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
postfixes: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
parameters:
  - myparam: 42
commands: []
"""
        with pytest.raises(Catastrophe):
            _checker_with_yaml(yaml, tmp_path)


class TestConverterDatainfoCatastrophes:
    """Errors raised during datainfo/dataty validation."""

    # -- parameter datainfo errors -------------------------------------------

    def _param_repo(self, param_yaml: str, tmp_path) -> str:
        """Write a repo+sub-file and return the repo path."""
        repo = """\
kind: Repository
name: test
version: 1
description: test
files:
  - sub.yaml
systems: []
interfaces: []
features: []
postfixes: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
parameters:
  - bad:1
commands: []
"""
        rp = tmp_path / 'repo.yaml'
        rp.write_text(repo)
        sp = tmp_path / 'sub.yaml'
        sp.write_text(param_yaml)
        return str(rp)

    def test_unknown_datainfo_type(self, tmp_path):
        param = """\
kind: Parameter
name: bad
version: 1
description: test
datainfo: {type: NonexistentType}
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._param_repo(param, tmp_path)], output='text')

    def test_datainfo_spec_missing_type(self, tmp_path):
        param = """\
kind: Parameter
name: bad
version: 1
description: test
datainfo: {units: K}
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._param_repo(param, tmp_path)], output='text')

    def test_datainfo_spec_wrong_type(self, tmp_path):
        param = """\
kind: Parameter
name: bad
version: 1
description: test
datainfo: 42
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._param_repo(param, tmp_path)], output='text')

    def test_datainfo_missing_key(self, tmp_path):
        param = """\
kind: Parameter
name: bad
version: 1
description: test
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._param_repo(param, tmp_path)], output='text')

    # -- property dataty errors ----------------------------------------------

    def _prop_repo(self, prop_yaml: str, tmp_path) -> str:
        """Write a repo+sub-file that references a Property and return path."""
        repo = """\
kind: Repository
name: test
version: 1
description: test
files:
  - sub.yaml
systems: []
interfaces: []
features: []
postfixes: []
parameters: []
commands: []
properties:
  SECNode:
    - bad:1
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
"""
        rp = tmp_path / 'repo.yaml'
        rp.write_text(repo)
        sp = tmp_path / 'sub.yaml'
        sp.write_text(prop_yaml)
        return str(rp)

    def test_invalid_dataty_spec(self, tmp_path):
        prop = """\
kind: Property
name: bad
version: 1
description: test
dataty: {typo_field: double}
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._prop_repo(prop, tmp_path)], output='text')

    def test_dataty_missing_key(self, tmp_path):
        prop = """\
kind: Property
name: bad
version: 1
description: test
"""
        with pytest.raises(Catastrophe):
            Checker('2.0', [self._prop_repo(prop, tmp_path)], output='text')

    # -- datainfo dataprop errors --------------------------------------------

    def _datainfo_repo(self, di_yaml: str, tmp_path) -> str:
        """Write a repo+sub-file that references a Datainfo and return path."""
        repo = """\
kind: Repository
name: test
version: 1
description: test
files:
  - sub.yaml
systems: []
interfaces: []
features: []
postfixes: []
parameters: []
commands: []
properties:
  SECNode: []
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo:
  - bad:1
"""
        rp = tmp_path / 'repo.yaml'
        rp.write_text(repo)
        sp = tmp_path / 'sub.yaml'
        sp.write_text(di_yaml)
        return str(rp)

    def test_dataprop_not_a_dict(self, tmp_path):
        """Non-dict dataprop value emits ERROR, not AttributeError."""
        di = """\
kind: Datainfo
name: bad
version: 1
description: test
dataty: string
dataprops:
  members: not_a_dict
"""
        c = Checker('2.0', [self._datainfo_repo(di, tmp_path)], output='text')
        with pytest.raises(Catastrophe):
            c.check('{}')


class TestCheckerCatastrophes:
    """Errors raised from Checker.check()."""

    def test_invalid_json(self):
        c = Checker('1.1', [], output='text')
        with pytest.raises(Catastrophe):
            c.check('not json')

    def test_schema_loading_produced_diagnostics(self, tmp_path):
        """Error during schema loading triggers bail-out in check()."""
        p = tmp_path / 'bad_schema.yaml'
        # inline property reference without 'description' → ERROR emitted
        p.write_text("""\
kind: Repository
name: test
version: 1
description: test
files: []
systems: []
interfaces: []
features: []
parameters: []
postfixes: []
commands: []
properties:
  SECNode:
    - myprop:
        dataty: string
  System: []
  Module: []
  Parameter: []
  Command: []
datainfo: []
""")
        c = Checker('2.0', [str(p)], output='text')
        with pytest.raises(Catastrophe):
            c.check(json.dumps({
                'modules': {},
                'description': 'x',
                'equipment_id': 'x',
                'firmware': 'x',
            }))
