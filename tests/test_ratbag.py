#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import ratbag

import pytest


def test_resolution():
    device = ratbag.Device(object(), "test device", "nopath")
    profile = ratbag.Profile(device, 0)

    # invalid index
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, -1, (0, 0))

    # negative dp
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (-1, -1))

    # dpi not an int
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, ("asbc", 1))

    # dpi not a 2-value tuple
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (1, 2, 3))

    # dpi list negative
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (1, 2), dpi_list=[-1])

    # dpi list not a list
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (1, 2), dpi_list=-1)

    # capability not in the enum
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (1, 2, 3), capabilities=[1])

    # default values
    r = ratbag.Resolution(profile, 0, (200, 200))
    assert r.capabilities == []
    assert not r.active
    assert not r.default
    assert r.enabled
    # correctly added to the profile?
    assert r in profile.resolutions.values()
    assert r.index in profile.resolutions
    assert r.dpi == (200, 200)

    # duplicate index
    with pytest.raises(AssertionError):
        ratbag.Resolution(profile, 0, (200, 200))

    # caps assigned properly?
    r = ratbag.Resolution(
        profile,
        1,
        (200, 200),
        capabilities=[ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION],
    )
    assert r.capabilities == [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]


def test_profile_set_active():
    device = ratbag.Device(object(), "test device", "nopath")
    for i in range(5):
        ratbag.Profile(device, i)

    p1 = device.profiles[1]
    p3 = device.profiles[3]

    # None are active by default
    assert [p.active for p in device.profiles.values()].count(True) == 0

    p1.set_active()
    assert p1.active
    assert p1.dirty
    assert [p.active for p in device.profiles.values()].count(True) == 1
    assert [p.dirty for p in device.profiles.values()].count(True) == 1

    p3.set_active()
    assert not p1.active
    assert p1.dirty
    assert p3.active
    assert p3.dirty
    assert [p.active for p in device.profiles.values()].count(True) == 1
    assert [p.dirty for p in device.profiles.values()].count(True) == 2


def test_profile_set_enabled():
    device = ratbag.Device(object(), "test device", "nopath")
    for i in range(5):
        ratbag.Profile(device, i)

    p1 = device.profiles[1]
    p3 = device.profiles[3]

    # All are enabled by default
    assert [p.enabled for p in device.profiles.values()].count(False) == 0

    p1.enabled = False
    assert not p1.enabled
    assert p1.dirty
    assert [p.enabled for p in device.profiles.values()].count(False) == 1
    assert [p.dirty for p in device.profiles.values()].count(True) == 1

    p3.enabled = False
    assert not p3.enabled
    assert p3.dirty
    assert [p.enabled for p in device.profiles.values()].count(False) == 2
    assert [p.dirty for p in device.profiles.values()].count(True) == 2
