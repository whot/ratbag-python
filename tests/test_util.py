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
        info = ratbag.driver.DeviceInfo.from_path(path)
        assert info.path == path
        assert info.name is not None
        assert info.vid is not None
        assert info.pid is not None
        assert info.bus is not None
        assert info.report_descriptor is not None


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

    data = bytes(range(12))
    spec = [
        Spec("H", "something"),
        Spec("BB", "other"),
        Spec("H", "intlist", greedy=True),
    ]
    result = Parser.to_object(data, spec)
    assert result.size == len(data)
    assert result.object.intlist == [0x0405, 0x0607, 0x0809, 0x0A0B]

    data = bytes(range(64, 73))
    spec = [
        Spec("B", "something"),
        Spec(
            "B",
            "string",
            greedy=True,
            convert_from_data=lambda s: bytes(s).decode("utf-8"),
        ),
    ]
    result = Parser.to_object(data, spec)
    assert result.size == len(data)
    assert result.object.string == "ABCDEFGH"

    # Only last one can be greedy
    with pytest.raises(AssertionError):
        data = bytes(range(12))
        spec = [
            Spec("H", "something"),
            Spec("BB", "other", greedy=True),
            Spec("H", "intlist"),
        ]
        result = Parser.to_object(data, spec)

    data = bytes(range(64, 73))
    spec = [
        Spec("B", "something"),
        Spec("8s", "string", convert_from_data=lambda s: s.decode("utf-8")),
    ]
    result = Parser.to_object(data, spec)
    assert result.size == len(data)
    assert result.object.string == "ABCDEFGH"

    data = bytes(range(64, 73))
    spec = [
        Spec("B", "something"),
        Spec(
            "2s",
            "string",
            repeat=4,
            convert_from_data=lambda ss: list(s.decode("utf-8") for s in ss),
        ),
    ]
    result = Parser.to_object(data, spec)
    assert result.size == len(data)
    assert result.object.string == ["AB", "CD", "EF", "GH"]

    # Disallow anything but string repeats
    with pytest.raises(AssertionError):
        data = bytes(range(64, 73))
        spec = [
            Spec("B", "something"),
            Spec("8B", "invalid"),
        ]
        result = Parser.to_object(data, spec)

    # Test the class name for the reply object
    data = bytes(range(64, 73))
    spec = [
        Spec("B", "something"),
        Spec("B", "__ignored"),  # double leading underscore is ignored
    ]
    result = Parser.to_object(data, spec, result_class="Foo")
    assert type(result.object).__name__ == "Foo"

    # Test instantiating the right class for the reply object
    class TestResult(object):
        def __init__(self, something):
            pass

    result = Parser.to_object(data, spec, result_class=TestResult)
    assert isinstance(result.object, TestResult)

    spec = [
        Spec("B", "_something"),  # single leading underscore is dropped
        Spec("B", "__ignored"),  # double leading underscore is ignored
    ]
    result = Parser.to_object(data, spec, result_class=TestResult)
    assert isinstance(result.object, TestResult)

    # Passing a string creates a new class of that name, not our class
    result = Parser.to_object(data, spec, result_class="TestResult")
    assert not isinstance(result.object, TestResult)
    assert type(result.object).__name__ == "TestResult"
    obj1 = result.object

    # Make sure we can do this with different specs
    spec = [Spec("B", "other")]
    result = Parser.to_object(data, spec, result_class="TestResult")
    assert not isinstance(result.object, TestResult)
    assert type(result.object).__name__ == "TestResult"
    obj2 = result.object

    assert type(obj1) != type(obj2)


def test_data_files():
    datafiles = ratbag.util.load_data_files()
    assert datafiles
    assert len(datafiles) > 20  # we have more than that but whatever

    for f in datafiles:
        assert f.name
        assert f.driver
        assert len(f.matches) >= 1

    # test two random devices to make sure they're there
    g305 = ratbag.util.DataFile(
        name="Logitech Gaming Mouse G305",
        matches=["usb:046d:4074"],
        driver="hidpp20",
        driver_options={"Leds": "0", "Quirk": "G305"},
    )
    assert g305 in datafiles

    xtd = ratbag.util.DataFile(
        name="Roccat Kone XTD",
        matches=["usb:1e7d:2e22"],
        driver="roccat",
    )
    assert xtd in datafiles


def test_ffs():
    from ratbag.util import ffs

    assert ffs(0) == 0
    assert ffs(1) == 1
    assert ffs(2) == 2
    assert ffs(4) == 3

    assert ffs(3) == 1
    assert ffs(6) == 2

    assert ffs(1 << 32) == 33  # this isn't C with 4-byte integers
