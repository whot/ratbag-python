#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#


import ratbag.drivers
import ratbag.drivers.hidpp20 as hidpp20
from ratbag.util import as_hex

import pytest


@pytest.fixture
def driver():
    return hidpp20.load_driver("hidpp20")


def test_load_driver():
    # the most basic test case...
    assert hidpp20.load_driver("hidpp20") is not None
    with pytest.raises(AssertionError):
        hidpp20.load_driver("wrong-name")
