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

from pathlib import Path

import pytest

from secop_check.checker import Checker

datadir = Path(__file__).parent / 'data'
json_files = [p.name for p in datadir.glob('*.json')]


@pytest.mark.parametrize('json', json_files)
def test_frappy_json(json: str) -> None:
    checker = Checker('1.1', [], output='text')
    content = (datadir / json).read_text()
    checker.check(content)

    assert not checker.get_diags()
