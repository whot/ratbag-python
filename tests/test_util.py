#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import logging

import ratbag
import ratbag.util

logger = logging.getLogger(__name__)


def test_find_hidraw_devices():
    devices = ratbag.util.find_hidraw_devices()
    for device in devices:
        assert device.startswith("/dev/hidraw")


def test_hidraw_info():
    info = ratbag.util.load_device_info("/dev/hidraw0")
    assert info["name"] is not None
    assert info["vid"] is not None
    assert info["pid"] is not None
    assert info["bus"] is not None
    assert info["report_descriptor"] is not None
