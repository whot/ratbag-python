#!usr/bin/env python3

import ratbag.hid


def test_hid_evdev():
    assert ratbag.hid.Key.KEY_ESCAPE.evdev == 1
    assert ratbag.hid.Key.KEY_A.evdev == 30
    assert ratbag.hid.Key.KEY_RESERVED.evdev == 0

    assert ratbag.hid.Key.from_evdev(1) == ratbag.hid.Key.KEY_ESCAPE
    assert ratbag.hid.Key.from_evdev(30) == ratbag.hid.Key.KEY_A
    assert ratbag.hid.Key.from_evdev(12345) is None

    assert ratbag.hid.ConsumerControl.CC_AC_DELETE.evdev == 111
    assert ratbag.hid.ConsumerControl.CC_AC_LOCK.evdev == 0

    assert (
        ratbag.hid.ConsumerControl.from_evdev(111)
        == ratbag.hid.ConsumerControl.CC_AC_DELETE
    )
    assert ratbag.hid.ConsumerControl.from_evdev(12345) is None
