#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import ratbag

import pytest


@pytest.fixture
def device():
    fake_driver = object()
    return ratbag.Device(fake_driver, "test device", "nopath", "model")


def test_resolution(device):
    profile = ratbag.Profile.create(device, 0)

    # invalid index
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, -1, (0, 0))

    # negative dp
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, (-1, -1))

    # dpi not an int
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, ("asbc", 1))

    # dpi not a 2-value tuple
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, (1, 2, 3))

    # dpi list negative
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, (1, 2), dpi_list=[-1])

    # dpi list not a list
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, (1, 2), dpi_list=-1)

    # capability not in the enum
    with pytest.raises(ValueError):
        ratbag.Resolution.create(profile, 0, (1, 2), capabilities=[1])

    # default values
    r = ratbag.Resolution.create(profile, 0, (200, 200))
    assert r.capabilities == ()
    assert not r.active
    assert not r.default
    assert r.enabled
    # correctly added to the profile?
    assert r in profile.resolutions
    assert r.dpi == (200, 200)

    # individual x/y res not supported
    with pytest.raises(ratbag.ConfigError):
        r.set_dpi((100, 200))

    # duplicate index
    with pytest.raises(AssertionError):
        ratbag.Resolution.create(profile, 0, (200, 200))

    # caps assigned properly?
    r = ratbag.Resolution.create(
        profile,
        1,
        (200, 200),
        capabilities=[ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION],
        dpi_list=[100, 200],
    )
    assert r.capabilities == (ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION,)

    r.set_dpi((100, 200))
    assert r.dpi == (100, 200)


def test_resolution_set_default(device):
    for i in range(5):
        profile = ratbag.Profile(device, i)
        for j in range(5):
            ratbag.Resolution.create(profile, j, (j * 100, j * 100))

    r11 = device.profiles[1].resolutions[1]
    r13 = device.profiles[1].resolutions[3]
    r22 = device.profiles[2].resolutions[2]
    r24 = device.profiles[2].resolutions[4]
    # we start with no default resolution
    assert [r.default for r in device.profiles[1].resolutions].count(True) == 0

    r13.set_default()
    assert r13.default
    assert r13.dirty
    assert [r.default for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 1
    r11.set_default()
    assert r11.default
    assert r11.dirty
    assert not r13.default
    assert r13.dirty
    assert [r.default for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    # different profile, shouldn't affect r11/r13
    r22.set_default()
    assert r22.default
    assert r22.dirty
    assert r11.default
    assert r11.dirty
    assert not r13.default
    assert r13.dirty
    assert [r.default for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    assert [r.default for r in device.profiles[2].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[2].resolutions].count(True) == 1
    r24.set_default()
    assert r24.default
    assert r24.dirty
    assert not r22.default
    assert r22.dirty
    assert r11.default
    assert r11.dirty
    assert not r13.default
    assert r13.dirty
    assert [r.default for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    assert [r.default for r in device.profiles[2].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[2].resolutions].count(True) == 2


def test_resolution_set_active(device):
    for i in range(5):
        profile = ratbag.Profile(device, i)
        for j in range(5):
            ratbag.Resolution.create(profile, j, (j * 100, j * 100))

    r11 = device.profiles[1].resolutions[1]
    r13 = device.profiles[1].resolutions[3]
    r22 = device.profiles[2].resolutions[2]
    r24 = device.profiles[2].resolutions[4]
    # we start with no active resolution
    assert [r.active for r in device.profiles[1].resolutions].count(True) == 0

    r13.set_active()
    assert r13.active
    assert r13.dirty
    assert [r.active for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 1
    r11.set_active()
    assert r11.active
    assert r11.dirty
    assert not r13.active
    assert r13.dirty
    assert [r.active for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    # different profile, shouldn't affect r11/r13
    r22.set_active()
    assert r22.active
    assert r22.dirty
    assert r11.active
    assert r11.dirty
    assert not r13.active
    assert r13.dirty
    assert [r.active for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    assert [r.active for r in device.profiles[2].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[2].resolutions].count(True) == 1
    r24.set_active()
    assert r24.active
    assert r24.dirty
    assert not r22.active
    assert r22.dirty
    assert r11.active
    assert r11.dirty
    assert not r13.active
    assert r13.dirty
    assert [r.active for r in device.profiles[1].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[1].resolutions].count(True) == 2
    assert [r.active for r in device.profiles[2].resolutions].count(True) == 1
    assert [r.dirty for r in device.profiles[2].resolutions].count(True) == 2


def test_led(device):
    profile = ratbag.Profile(device, 0)
    led = ratbag.Led.create(profile, 0)

    # color checks
    invalid_colors = [
        "abc",
        (1, 2, 3, 4),
        (-1, 2, 3),
        -1,
        (1, 3, 256),
    ]

    for v in invalid_colors:
        with pytest.raises(ratbag.ConfigError):
            led.set_color(v)

    led.set_color((0, 10, 200))
    assert led.color == (0, 10, 200)
    led.set_color((0, 0, 0))
    assert led.color == (0, 0, 0)

    # brightness checks
    invalid_brightness = [
        -1,
        "a",
        (1, 2),
        256,
    ]
    for v in invalid_brightness:
        with pytest.raises(ratbag.ConfigError):
            led.set_brightness(v)

    led.set_brightness(200)
    assert led.brightness == 200
    led.set_brightness(0)
    assert led.brightness == 0

    # effect duration checks
    invalid_effect_duration = [
        -1,
        "a",
        (1, 2),
        10001,
    ]
    for v in invalid_effect_duration:
        with pytest.raises(ratbag.ConfigError):
            led.set_effect_duration(v)

    led.set_effect_duration(200)
    assert led.effect_duration == 200
    led.set_effect_duration(0)
    assert led.effect_duration == 0

    with pytest.raises(ratbag.ConfigError):
        led.set_mode(1)

    # LED modes
    assert led.modes == (ratbag.Led.Mode.OFF,)
    led = ratbag.Led.create(
        profile, 1, modes=tuple(ratbag.Led.Mode), mode=ratbag.Led.Mode.ON
    )
    assert led.modes == tuple(ratbag.Led.Mode)
    for m in led.modes:
        led.set_mode(m)
        assert led.dirty
        assert led.mode == m


def test_profile_set_active(device):
    for i in range(5):
        ratbag.Profile(device, i)

    p1 = device.profiles[1]
    p3 = device.profiles[3]

    # None are active by default
    assert [p.active for p in device.profiles].count(True) == 0

    p1.set_active()
    assert p1.active
    assert p1.dirty
    assert [p.active for p in device.profiles].count(True) == 1
    assert [p.dirty for p in device.profiles].count(True) == 1

    p3.set_active()
    assert not p1.active
    assert p1.dirty
    assert p3.active
    assert p3.dirty
    assert [p.active for p in device.profiles].count(True) == 1
    assert [p.dirty for p in device.profiles].count(True) == 2


def test_profile_set_enabled(device):
    for i in range(5):
        ratbag.Profile(device, i, capabilities=[ratbag.Profile.Capability.DISABLE])

    p1 = device.profiles[1]
    p3 = device.profiles[3]

    # All are enabled by default
    assert [p.enabled for p in device.profiles].count(False) == 0

    p1.set_enabled(False)
    assert not p1.enabled
    assert p1.dirty
    assert [p.enabled for p in device.profiles].count(False) == 1
    assert [p.dirty for p in device.profiles].count(True) == 1

    p3.set_enabled(False)
    assert not p3.enabled
    assert p3.dirty
    assert [p.enabled for p in device.profiles].count(False) == 2
    assert [p.dirty for p in device.profiles].count(True) == 2

    # Can't disable profiles unless the profile explicitly supports it
    p = ratbag.Profile(device, 6)
    with pytest.raises(ratbag.ConfigError):
        p.set_enabled(False)


def test_profile_set_default(device):
    for i in range(5):
        ratbag.Profile(device, i, capabilities=[ratbag.Profile.Capability.SET_DEFAULT])

    p1 = device.profiles[1]
    p3 = device.profiles[3]

    # None are active by default
    assert [p.default for p in device.profiles].count(True) == 0

    p1.set_default()
    assert p1.default
    assert p1.dirty
    assert [p.default for p in device.profiles].count(True) == 1
    assert [p.dirty for p in device.profiles].count(True) == 1

    p3.set_default()
    assert not p1.default
    assert p1.dirty
    assert p3.default
    assert p3.dirty
    assert [p.default for p in device.profiles].count(True) == 1
    assert [p.dirty for p in device.profiles].count(True) == 2


def test_profile_out_of_order(device):
    p3 = ratbag.Profile(device, 3)
    p1 = ratbag.Profile(device, 1)

    assert p1 in device.profiles
    assert p3 in device.profiles
    assert device.profiles[0] is None
    assert device.profiles[2] is None
    assert len(device.profiles) == 4


def test_action_equals():
    assert ratbag.ActionUnknown.create() == ratbag.ActionUnknown.create()
    assert ratbag.ActionUnknown.create() != ratbag.ActionButton.create(1)
    assert ratbag.ActionUnknown.create() != ratbag.ActionSpecial.create(
        ratbag.ActionSpecial.Special.DOUBLECLICK
    )

    assert ratbag.ActionButton.create(1) == ratbag.ActionButton.create(1)
    assert ratbag.ActionButton.create(2) != ratbag.ActionButton.create(1)
    assert ratbag.ActionButton.create(1) != ratbag.ActionSpecial.create(
        ratbag.ActionSpecial.Special.DOUBLECLICK
    )

    assert ratbag.ActionSpecial.create(
        ratbag.ActionSpecial.Special.DOUBLECLICK
    ) == ratbag.ActionSpecial.create(ratbag.ActionSpecial.Special.DOUBLECLICK)
    assert ratbag.ActionSpecial.create(
        ratbag.ActionSpecial.Special.WHEEL_DOWN
    ) != ratbag.ActionSpecial.create(ratbag.ActionSpecial.Special.DOUBLECLICK)

    # name is not checked for equality
    assert ratbag.ActionMacro.create(
        name="foo", events=[(ratbag.ActionMacro.Event.KEY_PRESS, 1)]
    ) == ratbag.ActionMacro.create(
        name="bar", events=[(ratbag.ActionMacro.Event.KEY_PRESS, 1)]
    )
    assert ratbag.ActionMacro.create(
        name="foo",
        events=[
            (ratbag.ActionMacro.Event.KEY_PRESS, 1),
            (ratbag.ActionMacro.Event.KEY_PRESS, 2),
        ],
    ) != ratbag.ActionMacro.create(
        name="bar", events=[(ratbag.ActionMacro.Event.KEY_PRESS, 1)]
    )
