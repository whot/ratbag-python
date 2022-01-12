#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

from dbus_next import BusType, Message
from dbus_next.glib import MessageBus
from unittest.mock import patch, MagicMock
from gi.repository import GLib, GObject
from typing import List, Tuple
from itertools import count

import attr
import xml.etree.ElementTree as ET
import pathlib
from ratbagd import Ratbagd

import ratbag as ratbag_mod
import pytest
import os

counter = count()

pytestmark = pytest.mark.skipif(
    "DBUS_SESSION_BUS_ADDRESS" not in os.environ, reason="DBus daemon not available"
)


@attr.frozen
class RatbagBus:
    bus: MessageBus = attr.ib()
    busname: str = attr.ib(default="org.freedesktop.ratbag1_test")


@pytest.fixture
def bus():
    busname = f"org.freedesktop.ratbag1.test{next(counter)}"
    return RatbagBus(
        bus=MessageBus(bus_type=BusType.SESSION).connect_sync(),
        busname=busname,
    )


def introspect(bus: RatbagBus, objpath: str) -> str:
    """
    Return the introspecion XML for the given object path
    """
    msg = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=objpath,
            interface="org.freedesktop.DBus.Introspectable",
            member="Introspect",
        )
    )
    assert msg is not None
    return "".join(msg.body)


@attr.frozen
class Prop:
    """
    Helper class to compare introspection XML, see :func:`check_introspection`
    """

    name: str = attr.ib()
    type: str = attr.ib(
        validator=attr.validators.in_(
            ["s", "ao", "i", "u", "au", "(uuu)", "(uv)", "b", "v"]
        )
    )  # expand list as needed by the API, this is just to prevent typos
    access: str = attr.ib(validator=attr.validators.in_(["read", "readwrite"]))


@attr.frozen
class Method:
    """
    Helper class to compare introspection XML, see :func:`check_introspection`
    """

    name: str = attr.ib()
    args: List[Tuple[str, str, str]] = attr.ib(
        default=attr.Factory(list)
    )  # (name, type, direction)


@attr.frozen
class Signal:
    """
    Helper class to compare introspection XML, see :func:`check_introspection`
    """

    name: str = attr.ib()
    args: List[Tuple[str, str, str]] = attr.ib(
        default=attr.Factory(list)
    )  # (name, type, direction)


def check_introspection(
    xml,
    interface_name,
    props: List[Prop],
    methods: List[Method],
    signals: List[Signal],
    require_all=True,
):
    """
    Given a DBusIntrospection XML, check for the ``interface_name`` and
    compare all its props and methods. Assert on any failure.

    :param require_all: If ``True``, all props and methods given must be
        present in the interface.
    """
    intf = [i for i in xml.findall("interface") if i.attrib["name"] == interface_name]
    assert len(intf) == 1, f"Unable to find interface {interface_name}"

    found = []
    proplut = {p.name: p for p in props}
    for prop in intf[0].findall("property"):
        propname = prop.attrib["name"]
        try:
            p = proplut[propname]
            assert prop.attrib["type"] == p.type, f"Incorrect type for {propname}"

            assert prop.attrib["access"] == p.access, f"Incorrect access for {propname}"
            found.append(propname)
        except KeyError:
            assert False, f"Unknown property '{propname}'"

    if require_all:
        missing = [p for p in proplut.keys() if p not in found]
        assert not missing, f"Required properties {missing} are missing"

    found = []
    methlut = {m.name: m for m in methods}
    for method in intf[0].findall("method"):
        methodname = method.attrib["name"]
        try:
            m = methlut[methodname]
            args_found = []
            for arg in method.findall("args"):
                argname = arg.attrib["name"]
                argdir = arg.attrib["direction"]
                argtype = arg.attrib["type"]

                assert (argname, argtype, argdir) in m.args

                args_found.append(argname)
            if require_all:
                missing = [a[0] for a in m.args if a[0] not in args_found]
                assert not missing, f"Required args {missing} are missing"

            found.append(methodname)
        except KeyError:
            assert False, f"Unknown method '{methodname}'"

    if require_all:
        missing = [m for m in methlut.keys() if m not in found]
        assert not missing, f"Required method {missing} are missing"


@pytest.fixture
def ratbag():
    rb = MagicMock(spec=ratbag_mod.Ratbag)
    rb.start = MagicMock()
    rb.connect = MagicMock()

    device = MagicMock(spec=ratbag_mod.Device)
    device.name = "mock test device"
    device.model = "usb:1234:abcd:0"
    device.path = pathlib.Path("/dev/hidraw990")
    device.profiles = []
    rb._devices = [device]

    for i in range(5):
        profile = MagicMock(spec=ratbag_mod.Profile)
        profile.index = i
        profile.device = device

        profile.resolutions = []
        for j in range(3):
            res = MagicMock(spec=ratbag_mod.Resolution)
            res.profile = profile
            res.index = j
            profile.resolutions.append(res)

        profile.buttons = []
        for j in range(8):
            button = MagicMock(spec=ratbag_mod.Button)
            button.profile = profile
            button.index = j
            profile.buttons.append(button)

        profile.leds = []
        for j in range(2):
            led = MagicMock(spec=ratbag_mod.Led)
            led.profile = profile
            led.index = j
            profile.leds.append(led)

        device.profiles.append(profile)
    return rb


@pytest.fixture
def loop():
    loop = GLib.MainLoop()
    GLib.timeout_add(500, loop.quit)
    return loop


def test_to_stop_segfaults():
    # Some weird bug triggers with this test suite but I've been unable to
    # reproduce it.
    #
    # tests/test_ratbagd.py Fatal Python error: Segmentation fault
    # Current thread 0x00007fab2f1f2740 (most recent call first):
    # File "/usr/lib/python3.10/site-packages/gi/overrides/GLib.py", line 497 in run
    # File "/usr/lib/python3.10/site-packages/dbus_next/glib/message_bus.py", line 239 in connect_sync
    # File "/home/whot/code/ratbag/ratbag-python/tests/test_ratbagd.py", line 36 in bus
    #
    # Weirdly enough, it only triggers on a full pytest run, not when the test
    # case is selected with pytest -k or just this file is tested with
    # pytest $filename
    #
    # Touching the file lets the next test run succeed, subsequent ones fail
    #
    # Adding this test case prevents it from happening. Why I don't know
    pass


def test_manager_introspection(bus, loop, ratbag):
    """
    Check the DBus interface for the right signatures. If this test fails,
    we've broken the DBus API
    """

    ratbagd = Ratbagd(ratbag)
    ratbagd.init_dbus(bus.busname, use_system_bus=False)
    ratbagd.start()
    loop.run()

    for d in ratbag._devices:
        # This should be done through ratbag.emit("device-added") but I don't know
        # how to make that work
        # ratbag.emit("device-added", d)
        ratbagd.manager.cb_device_added(ratbagd, d)

    # The manager interface
    objpath = "/org/freedesktop/ratbag1"
    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Manager",
        props=[
            Prop("APIVersion", "i", "read"),
            Prop("Devices", "ao", "read"),
        ],
        methods=[],
        signals=[],
    )

    # Now query the Manager for the Devices property
    first_device = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=objpath,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.freedesktop.ratbag1.Manager", "Devices"],
        )
    )

    # Devices is an 'ao' Variant
    ao = first_device.body[0]
    assert len(ao.value) > 0, "Expected at least one device"
    objpath = ao.value[0]

    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Device",
        props=[
            Prop("Model", "s", "read"),
            Prop("Name", "s", "read"),
            Prop("Profiles", "ao", "read"),
        ],
        methods=[
            Method("Commit"),
        ],
        signals=[
            Signal("Resync"),
        ],
    )

    # Now query the device for the first Profile
    first_profile = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=objpath,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.freedesktop.ratbag1.Device", "Profiles"],
        )
    )

    # Profiles is an 'ao' Variant
    ao = first_profile.body[0]
    assert len(ao.value) > 0, "Expected at least one Profile"
    objpath = ao.value[0]

    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Profile",
        props=[
            Prop("Index", "u", "read"),
            Prop("Name", "s", "read"),
            Prop("Capabilities", "au", "read"),
            Prop("Enabled", "b", "readwrite"),
            Prop("IsActive", "b", "read"),
            Prop("IsDefault", "b", "read"),
            Prop("ReportRate", "u", "readwrite"),
            Prop("ReportRates", "au", "read"),
            Prop("Buttons", "ao", "read"),
            Prop("Leds", "ao", "read"),
            Prop("Resolutions", "ao", "read"),
        ],
        methods=[
            Method("SetActive"),
            Method("SetDefault"),
        ],
        signals=[],
    )

    profile_objpath = objpath

    # Now query the profile for the first Resolution
    first_resolution = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=profile_objpath,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.freedesktop.ratbag1.Profile", "Resolutions"],
        )
    )

    # Resolutions is an 'ao' Variant
    ao = first_resolution.body[0]
    assert len(ao.value) > 0, "Expected at least one Resolution"
    objpath = ao.value[0]

    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Resolution",
        props=[
            Prop("Index", "u", "read"),
            Prop("IsActive", "b", "read"),
            Prop("IsDefault", "b", "read"),
            Prop("Resolution", "v", "readwrite"),
            Prop("Resolutions", "au", "read"),
        ],
        methods=[
            Method("SetActive"),
            Method("SetDefault"),
        ],
        signals=[],
    )

    # Now query the profile for the first Led
    first_led = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=profile_objpath,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.freedesktop.ratbag1.Profile", "Leds"],
        )
    )

    # Leds is an 'ao' Variant
    ao = first_led.body[0]
    assert len(ao.value) > 0, "Expected at least one Led"
    objpath = ao.value[0]

    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Led",
        props=[
            Prop("Index", "u", "read"),
            Prop("Brightness", "u", "readwrite"),
            Prop("Color", "(uuu)", "readwrite"),
            Prop("ColorDepth", "u", "read"),
            Prop("EffectDuration", "u", "readwrite"),
            Prop("Mode", "u", "readwrite"),
            Prop("Modes", "au", "read"),
        ],
        methods=[],
        signals=[],
    )

    # Now query the profile for the first Button
    first_button = bus.bus.call_sync(
        Message(
            destination=bus.busname,
            path=profile_objpath,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.freedesktop.ratbag1.Profile", "Buttons"],
        )
    )

    # Buttons is an 'ao' Variant
    ao = first_button.body[0]
    assert len(ao.value) > 0, "Expected at least one Led"
    objpath = ao.value[0]

    introspection = introspect(bus, objpath)
    xml = ET.fromstring(introspection)

    check_introspection(
        xml,
        "org.freedesktop.ratbag1.Button",
        props=[
            Prop("Index", "u", "read"),
            Prop("ActionTypes", "au", "read"),
            Prop("Mapping", "(uv)", "readwrite"),
        ],
        methods=[
            Method("Disable"),
        ],
        signals=[],
    )
