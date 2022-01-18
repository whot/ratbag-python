#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#


import ratbag.driver
import ratbag.drivers.hidpp20 as hidpp20

import pytest


@pytest.fixture
def driver():
    cls = ratbag.driver.load_driver_by_name("hidpp20")
    return cls


def test_load_driver():
    # the most basic test case...
    cls = ratbag.driver.load_driver_by_name("hidpp20")
    assert cls == hidpp20.Hidpp20Driver
