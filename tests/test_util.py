#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import logging
import pathlib
import pytest

import ratbag
import ratbag.util


logger = logging.getLogger(__name__)


def test_find_hidraw_devices():
    devices = ratbag.util.find_hidraw_devices()
    for device in devices:
        assert device.startswith("/dev/hidraw")


@pytest.mark.skipif(not pathlib.Path("/dev/hidraw0").exists(), reason="no /dev/hidraw0")
def test_hidraw_info():
    info = ratbag.util.load_device_info("/dev/hidraw0")
    assert info["name"] is not None
    assert info["vid"] is not None
    assert info["pid"] is not None
    assert info["bus"] is not None
    assert info["report_descriptor"] is not None


def test_attr_from_data():
    class Foo(object):
        pass

    bs = bytes(range(16))
    obj = Foo()
    format = [
        ("B", "zero"),
        ("B", "first"),
        (">H", "second"),
        ("<H", "third"),
    ]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 6
    assert obj.zero == 0x0
    assert obj.first == 0x1
    assert obj.second == 0x0203
    assert obj.third == 0x0504

    obj = Foo()
    format = [("BBB", "list")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 3
    assert obj.list == (0, 1, 2)

    obj = Foo()
    format = [("3*BBB", "list")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 9
    assert obj.list == [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
