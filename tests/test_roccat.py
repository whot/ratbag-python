#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import libevdev
import logging
import pytest

from gi.repository import GLib

import ratbag.driver
import ratbag.drivers.roccat as roccat
from ratbag.util import as_hex
from unittest.mock import MagicMock

logger = logging.getLogger(__name__)

# From a  Roccat Kone XTD
ROCCAT_HID_REPORT = bytes(
    int(x, 16)
    for x in """
05 01 09 02 a1 01 85 01 09 01 a1 00 05 09 19 01 29 05
15 00 25 01 95 05 75 01 81 02 75 03 95 01 81 03 05 01 09 30 09 31 16 00 80 26
ff 7f 95 02 75 10 81 06 09 38 15 81 25 7f 75 08 95 01 81 06 05 0c 0a 38 02 81
06 c0 c0 05 0c 09 01 a1 01 85 02 19 00 2a 3c 02 15 00 26 3c 02 95 01 75 10 81
00 c0 05 0a 09 00 a1 01 85 03 19 00 29 00 15 00 25 00 95 04 75 08 81 00 c0 05
0b 09 00 a1 01 85 04 19 00 29 00 15 00 25 00 95 02 75 08 b1 01 85 05 95 02 b1
01 85 06 95 2a b1 01 85 07 95 4c b1 01 85 08 96 21 08 b1 01 85 09 95 05 b1 01
85 0a 95 07 b1 01 85 0c 95 03 b1 01 85 0d 96 03 04 b1 01 85 0e 95 02 b1 01 85
0f 95 05 b1 01 85 10 95 0f b1 01 85 1a 96 04 04 b1 01 85 1b 96 01 04 b1 01 85
1c 95 02 b1 01 c0
""".strip()
    .replace("\n", " ")
    .split(" ")
)


def new_transaction(device):
    transaction = ratbag.CommitTransaction.create(device)

    def cb_finished(ta):
        assert ta.is_finished
        assert ta.seqno >= 0
        assert ta == transaction

    transaction.connect("finished", cb_finished)
    return transaction


class RoccatTestDevice(ratbag.driver.Rodent):
    class Profile:
        """
        Use for software-configuring the device
        """

        def __init__(self):
            self.buttons = list(
                range(1, roccat.MAX_BUTTONS + 2)
            )  # button actions, indexed by 1
            self.resolutions = list(
                map(lambda x: x * 100, range(5, 11))
            )  # 500 - 1000dpi
            self.macros = [None] * len(self.buttons)

    """
    This is effectively a software emulation of a roccat device supported by
    that driver. It follows the implementation closely since that's what we
    have, it's purpose is *not* to figure out how the actual device work, it's
    purpose is solely to make sure that the driver still works if we refactor
    ratbag or the driver itself.
    """

    def __init__(self):
        info = ratbag.driver.DeviceInfo(
            path="/does/not/exist",
            syspath="/sys/does/not/exist",
            name=f"{type(self).__name__}",
            bus="usb",
            vid=0x1234,
            pid=0xABCD,
            report_descriptor=ROCCAT_HID_REPORT,
        )
        super().__init__(info)
        # See hid_set_select_profile
        self.current_profile = 0
        self.subcommand = None
        # Default button actions: 1, 2, 3, etc.
        # This is currently not per-profile though
        self.profiles = [RoccatTestDevice.Profile() for _ in range(roccat.MAX_PROFILES)]
        self.active_profile = 0
        self.expected_commit_status = True
        self.commits = []  # the seqnos

    def hid_get_feature(self, report_id):
        try:
            name = roccat.ReportID(report_id).name
        except ValueError:
            name = "unnamed request"
        logger.info(f"GetFeature: {report_id:02x} {name}")
        reply = {
            roccat.ReportID.SELECT_PROFILE.value: self.hid_get_select_profile,
            roccat.ReportID.CURRENT_PROFILE.value: self.hid_get_current_profile,
            roccat.ReportID.PROFILE_SETTINGS.value: self.hid_get_profile_settings,
            roccat.ReportID.KEY_MAPPING.value: self.hid_get_key_mapping,
            roccat.ReportID.MACRO.value: self.hid_get_macro,
        }[report_id]()
        logger.info(f"GetFeature:    → {as_hex(reply)}")
        return reply

    def hid_set_feature(self, report_id, data):
        try:
            name = roccat.ReportID(report_id).name
        except ValueError:
            name = "unnamed request"
        logger.info(f"SetFeature: {report_id:02x} {name} {as_hex(data)}")
        return {
            roccat.ReportID.SELECT_PROFILE.value: self.hid_set_select_profile,
            # roccat.ReportID.CURRENT_PROFILE.value: self.hid_set_current_profile,
            roccat.ReportID.PROFILE_SETTINGS.value: self.hid_set_profile_settings,
            roccat.ReportID.KEY_MAPPING.value: self.hid_set_key_mapping,
            # roccat.ReportID.MACRO.value: self.hid_set_macro,
        }[report_id](data)

    def hid_get_current_profile(self):
        return bytes([roccat.ReportID.CURRENT_PROFILE.value, self.active_profile, 0])

    def hid_get_select_profile(self):
        # get feature on this report ID replies wether the device is ready
        # 0x1 means everything ok (so we don't busy wait)
        return bytes([roccat.ReportID.SELECT_PROFILE.value, 0x1, 0])

    def hid_set_select_profile(self, data):
        # This set feature decides what we do next for the various get
        # features later. byte[1] is the profile ID, byte[2] is what we want
        # to get next
        self.current_profile = data[1]
        self.subcommand = data[2]
        logger.debug(
            f"Selected profile {self.current_profile}, subcommand {self.subcommand}"
        )

    def hid_get_profile_settings(self):
        # Ensure we've switched to the right subcommand in a previous select
        # profile call
        assert self.subcommand == roccat.ConfigureCommand.SETTINGS.value
        assert self.current_profile < roccat.MAX_PROFILES

        # RoccatProfile sets report id and length for us
        profile = roccat.RoccatProfile(0)
        profile.profile_id = self.current_profile
        profile.x_sensitivity = 0
        profile.y_sensitivity = 0
        profile.xy_linked = False
        profile.current_dpi = 0
        profile.update_report_rate(500)
        for idx, dpi in enumerate([800] * 5):
            profile.update_dpi(idx, (800, 800), True)
        return bytes(profile)

    def hid_set_profile_settings(self, data):
        profile = roccat.RoccatProfile(0).from_data(data)
        profile.index = profile.profile_id
        self.profiles[profile.index].resolutions = [
            (x * 50, y * 50) for x, y in zip(profile.xres, profile.yres)
        ]
        # FIXME: a few bits missing here

    def hid_get_key_mapping(self):
        # Ensure we've switched to the right subcommand in a previous select
        # profile call
        assert self.subcommand == roccat.ConfigureCommand.KEY_MAPPING.value
        assert self.current_profile < roccat.MAX_PROFILES

        mapping = roccat.RoccatKeyMapping(0)
        mapping.profile_id = self.current_profile
        mapping.actions = tuple(
            map(lambda x: (x, 0, 0), self.profiles[self.current_profile].buttons)
        )
        return bytes(mapping)

    def hid_set_key_mapping(self, data):
        mapping = roccat.RoccatKeyMapping(0).from_data(data)
        for idx, k in enumerate(mapping.actions):
            self.profiles[mapping.profile_id].buttons[idx] = k[0]

    def hid_get_macro(self):
        # Subcommond is supposed to be the button index
        assert self.subcommand < roccat.MAX_BUTTONS
        assert self.current_profile < roccat.MAX_PROFILES
        macro = roccat.RoccatMacro(self.current_profile, self.subcommand)
        mconfig = self.profiles[self.current_profile].macros[self.subcommand]
        for idx, m in enumerate(mconfig):
            macro.update_key(idx, m)
        return bytes(macro)


@pytest.fixture
def driver():
    cls = ratbag.driver.load_driver_by_name("roccat")
    return cls(supported_devices=[])


def test_load_driver():
    # the most basic test case...
    cls = ratbag.driver.load_driver_by_name("roccat")
    assert cls == roccat.RoccatDriver


class TestRoccatDriver(object):
    def mainloop(self):
        ctx = GLib.MainContext.default()
        while ctx.pending():
            ctx.iteration(False)

    def cb_device_added(self, ratbag, device):
        logger.info(f"Adding device {device.name}")
        self.ratbag_device = device

    def test_init_device_defaults(self, driver):
        # The most basic test, start a device, check the various default values
        # **we** define for this device (not the driver)
        dev = RoccatTestDevice()
        driver.connect("device-added", self.cb_device_added)
        # Note: we bypass the hidraw monitor because we don't need it
        driver.probe(dev, None)
        self.mainloop()

        assert self.ratbag_device is not None
        device = self.ratbag_device
        assert len(device.profiles) == roccat.MAX_PROFILES
        assert device.profiles[0].active
        for p in device.profiles:
            assert len(p.resolutions) == 5
            assert len(p.buttons) == roccat.MAX_BUTTONS

            # buttons are 1, 2, ... etc.
            act = p.buttons[0].action
            assert act.type == ratbag.Action.Type.BUTTON
            assert act.button == 1

            act = p.buttons[1].action
            assert act.type == ratbag.Action.Type.BUTTON
            assert act.button == 2

            # button value 9 (index 8) is the first special
            act = p.buttons[8].action
            assert act.type == ratbag.Action.Type.SPECIAL
            assert act.special == ratbag.ActionSpecial.Special.WHEEL_LEFT

    def test_init_buttons_cc_action_is_macro(self, driver):
        # On init, driver converts ConsumerControl keys into a simple macro of
        # press/release with a minimal wait in between
        dev = RoccatTestDevice()
        dev.profiles[1].buttons[5] = 36  # ConsumerControl.CC_STOP
        driver.connect("device-added", self.cb_device_added)
        # Note: we bypass the hidraw monitor because we don't need it
        driver.probe(dev, None)
        self.mainloop()

        device = self.ratbag_device
        act = device.profiles[1].buttons[5].action
        assert act.type == ratbag.Action.Type.MACRO
        macro = [
            (ratbag.ActionMacro.Event.KEY_PRESS, libevdev.EV_KEY.KEY_STOP.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 1),
            (ratbag.ActionMacro.Event.KEY_RELEASE, libevdev.EV_KEY.KEY_STOP.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 1),
        ]
        assert act.events == macro

    def test_init_buttons_macro(self, driver):
        # Set up an actual macro on a button, make sure it comes across
        # correctly
        kcA = ratbag.hid.Key.KEY_A.value
        kcTab = ratbag.hid.Key.KEY_TAB.value
        dev = RoccatTestDevice()
        dev.profiles[0].buttons[2] = 48  # Macro
        # a down, tab down, tab up, a up - with wait times in between
        dev.profiles[0].macros[2] = [
            (kcA, 0x01, 100),
            (kcTab, 0x01, 200),
            (kcTab, 0x00, 300),
            (kcA, 0x00, 400),
        ]
        driver.connect("device-added", self.cb_device_added)
        # Note: we bypass the hidraw monitor because we don't need it
        driver.probe(dev, None)
        self.mainloop()

        device = self.ratbag_device
        act = device.profiles[0].buttons[2].action
        assert act.type == ratbag.Action.Type.MACRO
        macro = [
            (ratbag.ActionMacro.Event.KEY_PRESS, libevdev.EV_KEY.KEY_A.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 100),
            (ratbag.ActionMacro.Event.KEY_PRESS, libevdev.EV_KEY.KEY_TAB.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 200),
            (ratbag.ActionMacro.Event.KEY_RELEASE, libevdev.EV_KEY.KEY_TAB.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 300),
            (ratbag.ActionMacro.Event.KEY_RELEASE, libevdev.EV_KEY.KEY_A.value),
            (ratbag.ActionMacro.Event.WAIT_MS, 400),
        ]
        assert act.events == macro

        # sanity check, we only configured one button to have a macro so let's
        # make sure that is the case
        for pidx, p in enumerate(device.profiles):
            for bidx, b in enumerate(p.buttons):
                if (pidx, bidx) == (0, 2):
                    continue
                assert b.action != ratbag.Action.Type.MACRO

    def test_button_change_action(self, driver):
        dev = RoccatTestDevice()
        driver.connect("device-added", self.cb_device_added)
        # Note: we bypass the hidraw monitor because we don't need it
        driver.probe(dev, None)
        self.mainloop()

        device = self.ratbag_device
        button = device.profiles[3].buttons[2]
        button.set_action(ratbag.ActionButton.create(1))  # change to left button

        transaction = new_transaction(device)
        transaction.commit()
        self.mainloop()

        assert transaction.success is True
        assert dev.profiles[3].buttons[2] == 1

    def test_dpi_change(self, driver):
        dev = RoccatTestDevice()
        driver.connect("device-added", self.cb_device_added)
        # Note: we bypass the hidraw monitor because we don't need it
        driver.probe(dev, None)
        self.mainloop()

        device = self.ratbag_device
        res = device.profiles[2].resolutions[4]
        res.set_dpi((1300, 1300))
        res = device.profiles[1].resolutions[1]
        res.set_dpi((1400, 1400))
        transaction = new_transaction(device)
        transaction.commit()
        self.mainloop()

        assert transaction.success is True
        assert dev.profiles[1].resolutions[1] == (1400, 1400)
        assert dev.profiles[2].resolutions[4] == (1300, 1300)
