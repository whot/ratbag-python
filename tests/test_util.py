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


@pytest.mark.skipif(
    not list(pathlib.Path("/dev").glob("hidraw*")), reason="no /dev/hidraw*"
)
def test_find_hidraw_devices():
    devices = ratbag.util.find_hidraw_devices()
    assert devices != []
    for device in devices:
        assert device.startswith("/dev/hidraw")


@pytest.mark.skipif(
    not list(pathlib.Path("/dev").glob("hidraw*")), reason="no /dev/hidraw*"
)
def test_device_info():
    for path in ratbag.util.find_hidraw_devices():
        info = ratbag.drivers.DeviceInfo.from_path(path)
        assert info.path == path
        assert info.name is not None
        assert info.vid is not None
        assert info.pid is not None
        assert info.bus is not None
        assert info.report_descriptor is not None


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
    reverse = ratbag.util.attr_to_data(obj, format)
    assert reverse == bs[:offset]

    bs = bytes(range(16))
    obj = Foo()
    format = [("BBB", "list")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 3
    assert obj.list == (0, 1, 2)
    reverse = ratbag.util.attr_to_data(obj, format)
    assert reverse == bs[:offset]

    bs = bytes(range(16))
    obj = Foo()
    format = [("3*BBB", "list")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 9
    assert obj.list == [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
    reverse = ratbag.util.attr_to_data(obj, format)
    assert reverse == bs[:offset]

    bs = bytes(range(16))
    obj = Foo()
    format = [("H", "?"), ("3*BBB", "_")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 11
    reverse = ratbag.util.attr_to_data(obj, format)
    assert reverse == bytes([0] * 11)

    bs = bytes(range(16))
    obj = Foo()
    format = [("H", "something"), ("3*BBB", "other"), ("H", "map_me")]
    offset = ratbag.util.attr_from_data(obj, format, bs, offset=0)
    assert offset == 13
    reverse = ratbag.util.attr_to_data(obj, format, maps={"map_me": lambda x: sum(x)})
    assert reverse[-2] << 8 | reverse[-1] == sum(range(11))


def test_add_to_sparse_tuple():
    t = (None,)
    t = ratbag.util.add_to_sparse_tuple(t, 3, "d")
    assert t == (None, None, None, "d")

    t = ratbag.util.add_to_sparse_tuple(t, 0, "a")
    assert t == ("a", None, None, "d")
    t = ratbag.util.add_to_sparse_tuple(t, 1, "b")
    assert t == ("a", "b", None, "d")

    with pytest.raises(AssertionError):
        ratbag.util.add_to_sparse_tuple(t, 1, "B")

    t = ratbag.util.add_to_sparse_tuple(t, 2, "c")
    assert t == ("a", "b", "c", "d")
    t = ratbag.util.add_to_sparse_tuple(t, 4, "e")
    assert t == ("a", "b", "c", "d", "e")


def test_parser():
    from ratbag.parser import Parser, Spec

    data = bytes(range(16))
    spec = [
        Spec("B", "zero"),
        Spec("B", "first"),
        Spec("H", "second", endian="BE"),
        Spec("H", "third", endian="le"),
        Spec("BB", "tuples", repeat=5),
    ]

    result = Parser.to_object(data, spec)

    assert result.size == 16
    assert result.object.zero == 0x0
    assert result.object.first == 0x1
    assert result.object.second == 0x0203
    assert result.object.third == 0x0504
    assert result.object.tuples == [(6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]
    reverse = Parser.from_object(result.object, spec)
    assert reverse == data[: result.size]

    data = bytes(range(16))
    spec = [Spec("BBB", "list")]
    result = Parser.to_object(data, spec)
    assert result.size == 3
    assert result.object.list == (0, 1, 2)
    reverse = Parser.from_object(result.object, spec)
    assert reverse == data[: result.size]

    data = bytes(range(16))
    spec = [Spec("BBB", "list", repeat=3)]
    result = Parser.to_object(data, spec)
    assert result.size == 9
    assert result.object.list == [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
    reverse = Parser.from_object(result.object, spec)
    assert reverse == data[: result.size]

    data = bytes(range(16))
    spec = [Spec("H", "?"), Spec("BBB", "_", repeat=3)]
    result = Parser.to_object(data, spec)
    assert result.size == 11
    reverse = Parser.from_object(result.object, spec)
    assert reverse == bytes([0] * 11)

    reverse = Parser.from_object(result.object, spec, pad_to=50)
    assert reverse == bytes([0] * 50)
    reverse = Parser.from_object(result.object, spec, pad_to=1)
    assert reverse == bytes([0] * 11)

    data = bytes(range(16))
    spec = [
        Spec("H", "something"),
        Spec("BBB", "other", repeat=3),
        Spec("H", "map_me", convert_to_data=lambda arg: sum(arg.bytes)),
    ]
    result = Parser.to_object(data, spec)
    assert result.size == 13
    reverse = Parser.from_object(result.object, spec)
    assert reverse[-2] << 8 | reverse[-1] == sum(range(11))
