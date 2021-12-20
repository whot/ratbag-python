#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import enum
import logging
import struct
import time
import traceback

import hidtools
import hidtools.hidraw
import hidtools.hid

from gi.repository import GObject

import ratbag
import ratbag.hid
import ratbag.drivers
import ratbag.util

from ratbag.util import as_hex

logger = logging.getLogger(__name__)

MAX_PROFILES = 5
MAX_BUTTONS = 24


def crc(data):
    if len(data) < 3:
        return -1
    return sum(data[:-2]) & 0xFFFF


class ConfigureCommand(enum.IntEnum):
    """
    Third byte in the SetFeature request, specifies what we're trying to
    retrieve from the feature next.

    First byte is the :class:`ReportID`, second byte is the profile id.
    """

    ZERO = 0x00
    # 0x01 to MAX_BUTTONS are the buttons
    SETTINGS = 0x80
    KEY_MAPPING = 0x90


class ReportID(enum.IntEnum):
    """
    Feature Report IDs used for various settings
    """

    CONFIGURE_PROFILE = 0x4
    PROFILE = 0x5
    SETTINGS = 0x6
    KEY_MAPPING = 0x7
    MACRO = 8


class RoccatProfile(object):
    """
    Represents the reply from the :attr:`ReportID.SETTINGS` feature request.
    In ratbag parlance this is called a profile, so let's use that name here
    too.

    .. attribute:: name

        The profile name. This is software-generated, the device doesn't have
        profile names.

    .. attribute:: data

        The raw bytes represeting this profile

    .. attribute:: dpi

        A list of `(x, y)` resolution tuples. This list has a constant length
        of the supported resolutions, a resolution that is disabled is ``(0, 0)``.

    """

    SIZE = 43

    format = [
        ("B", "report_id"),
        ("B", "report_length"),
        ("B", "profile_id"),
        ("B", "xy_linked"),
        ("B", "x_sensitivity"),
        ("B", "y_sensitivity"),
        ("B", "dpi_mask"),
        ("BBBBB", "xres"),
        ("B", "current_dpi"),
        ("BBBBB", "yres"),
        ("B", "_"),
        ("B", "_report_rate_idx"),
        ("B" * 21, "_"),  # 21 bytes padding
        ("<H", "checksum"),
    ]

    report_rates = [125, 250, 500, 1000]

    def __init__(self, idx):
        self.idx = idx
        self.name = f"Profile {idx}"
        self.buttons = []
        self.active = False
        self.ratbag_profile = None
        self.key_mapping = None

    def from_data(self, data):
        if len(data) != RoccatProfile.SIZE:
            raise ratbag.ProtocolError(f"Invalid size {len(data)} for Profile")

        ratbag.util.attr_from_data(self, RoccatProfile.format, data, offset=0)

        # Checksum first because if we have garbage, don't touch anything
        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(f"CRC validation failed for profile {self.idx}")

        # the x/y dpi is in multiples of 50
        def times_50(x):
            return x * 50

        self.dpi = list(zip(map(times_50, self.xres), map(times_50, self.yres)))
        # but if the mask isn't set it's disabled
        for idx in range(len(self.dpi)):
            mask = 1 << idx
            if (self.dpi_mask & mask) == 0:
                self.dpi[idx] = (0, 0)

        self.report_rate = RoccatProfile.report_rates[self._report_rate_idx]

        return self  # just to allow for chaining

    def dpi_is_enabled(self, idx):
        return self.dpi_mask & (1 << idx) != 0

    def init_ratbag_profile(self, ratbag_device):
        assert self.ratbag_profile is None
        caps = [ratbag.Profile.Capability.INDIVIDUAL_REPORT_RATE]
        p = ratbag.Profile(
            ratbag_device,
            self.idx,
            name=self.name,
            capabilities=caps,
            report_rate=self.report_rate,
            report_rates=[125, 250, 500, 1000],  # Not sure we can query this
        )
        for (dpi_idx, dpi) in enumerate(self.dpi):
            dpi_list = list(range(200, 8200 + 1, 50))
            caps = [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]
            r = ratbag.Resolution(
                p,
                dpi_idx,
                dpi,
                enabled=self.dpi_is_enabled(dpi_idx),
                capabilities=caps,
                dpi_list=dpi_list,
            )
            p.add_resolution(r)

        for btn_idx in range(self.key_mapping.num_buttons):
            caps = [
                ratbag.Action.Type.BUTTON,
                ratbag.Action.Type.SPECIAL,
                ratbag.Action.Type.MACRO,
            ]
            action = self.key_mapping.button_to_ratbag(btn_idx)
            button = ratbag.Button(p, btn_idx, types=caps, action=action)
            p.add_button(button)

        self.ratbag_profile = p
        return p

    def update_dpi(self, index, values, is_enabled):
        assert len(values) == 2
        self.dpi[index] = values
        self.xres = [v[0] // 50 for v in self.dpi]
        self.yres = [v[1] // 50 for v in self.dpi]
        mask = 1 << index
        if is_enabled:
            self.dpi_mask |= mask
        else:
            self.dpi_mask &= ~mask

    def update_button(self, index, action):
        self.key_mapping.actions[index] = (action, 0, 0)

    def update_report_rate(self, rate):
        self._report_rate_idx = RoccatProfile.report_rates.index(rate)

    def __bytes__(self):
        # need to do this twice, once to fill in the data, the second time so
        # the checksum is correct
        return ratbag.util.attr_to_data(
            self, RoccatProfile.format, maps={"checksum": lambda x: crc(x)}
        )


class RoccatMacro(object):
    """
    Represents the reply from the :attr:`ReportID.MACRO` feature request.
    """

    SIZE = 2082

    format = [
        ("B", "report_id"),
        ("<H", "report_length"),
        ("B", "profile"),
        ("B", "button_index"),
        ("B", "active"),
        ("B" * 24, "_"),
        ("B" * 24, "group"),
        ("B" * 24, "_name"),
        ("<H", "length"),
        ("<500*BBH", "_keys"),  # keycode, flag, time
        ("<H", "checksum"),
    ]

    def __init__(self, mapping, button_idx):
        self.mapping = mapping
        self.button = button_idx
        self.name = f"macro on {button_idx}"
        self.keys = 500 * [(0, 0, 0)]  # A triple of keycode, flags, wait_time
        self.length = 0
        self._macro_exists_on_device = False

    def to_ratbag(self):
        events = []
        for keycode, flag, wait_time in self.keys:
            try:
                evdev = ratbag.hid.Key(keycode).evdev
            except ValueError:
                try:
                    evdev = ratbag.hid.ConsumerControl(keycode).evdev
                except ValueError:
                    logger.error(f"Keycode {keycode} unsupported by ratbag")
                    evdev = 0
            type = (
                ratbag.ActionMacro.Event.KEY_PRESS
                if flag & 0x01
                else ratbag.ActionMacro.Event.KEY_RELEASE
            )
            events.append((type, evdev))
            # Always insert a wait period of 10ms (after press) or 50ms (after release)
            if wait_time == 0:
                if flag & 0x01:
                    wait_time = 10
                else:
                    wait_time = 50
            events.append((ratbag.ActionMacro.Event.WAIT_MS, wait_time))

        return self.name, events

    def update_from_ratbag(self, ratbag_macro):
        """
        Update self from the given ratbag macro
        """
        offset = 0
        keycode, flag, wait_time = 0, 0, 0
        for type, value in ratbag_macro.events:
            # The device stores the wait time with the keycode, so we only
            # push an event if we have one of the key events
            if type == ratbag.ActionMacro.Event.WAIT_MS:
                wait_time = value
                continue

            def map_key(evdev):
                keycode = ratbag.hid.Key.from_evdev(evdev)
                if keycode is None:
                    keycode = ratbag.hid.ConsumerControl.from_evdev(evdev)
                    if keycode is None:
                        logger.warning(f"Unsupported evdev keycode {evdev}")
                return keycode

            if keycode and type in [
                ratbag.ActionMacro.Event.KEY_PRESS,
                ratbag.ActionMacro.Event.KEY_RELEASE,
            ]:
                self.keys[offset] = (keycode, flag, wait_time)
                offset += 1
                keycode, flag = 0, 0

            if type == ratbag.ActionMacro.Event.KEY_PRESS:
                keycode = map_key(value)
                if keycode is not None:
                    keycode = keycode.value
                    flag = 0x01
                    wait_time = 0
            elif type == ratbag.ActionMacro.Event.KEY_RELEASE:
                keycode = map_key(value)
                if keycode is not None:
                    keycode = keycode.value
                    flag = 0x00
                    wait_time = 0
            else:
                logger.info(f"Unsupported macro event type {str(type)}")
                continue

        if keycode:
            self.keys[offset] = (keycode, flag, wait_time)
            offset += 1

        self.length = offset
        self.keys = self.keys[: self.length]
        self._macro_exists_on_device = True

    def from_data(self, data):
        if len(data) != RoccatMacro.SIZE:
            raise ratbag.ProtocolError(message=f"Invalid size {len(data)} for Macro")

        ratbag.util.attr_from_data(self, RoccatMacro.format, data, offset=0)

        # Shorten the keys array to the valid ones only
        self.keys = self._keys[: self.length]

        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(
                f"CRC validation failed for macro on button {self.button.profile.idx}.{self.button.idx}"
            )
        self.name = bytes(self._name).decode("utf-8")

        return self  # to allow for chaining

    def __bytes__(self):
        if not self._macro_exists_on_device:
            self.report_id = int(ReportID.MACRO)
            self.report_length = RoccatMacro.SIZE
            self.profile = self.button.profile.idx
            self.button_index = self.button_idx
            self.active = 0x01
            self.checksum = 0x00
            group = bytearray("g0".encode("utf-8"))
            if len(group) < 24:
                group.extend([0x00] * (24 - len(group)))
            self.group = bytes(group)

        name = bytearray(self.name[:24].encode("utf-8"))
        if len(name) < 24:
            name.extend([0x00] * (24 - len(name)))
        self._name = bytes(name)
        self._keys = self.keys + [(0, 0, 0)] * (500 - len(self.keys))
        return ratbag.util.attr_to_data(
            self, RoccatMacro.format, maps={"checksum": lambda x: crc(x)}
        )


class RoccatKeyMapping(object):
    """
    Represents the reply from the :attr:`ReportID.KEY_MAPPING` feature request.
    """

    SIZE = 77

    format = [
        ("B", "report_id"),
        ("B", "report_length"),
        ("B", "profile_id"),
        (f"{MAX_BUTTONS}*BBB", "actions"),  # action[button][0] is what we need
        ("<H", "checksum"),
    ]

    # firmware action value vs ratbag value
    specials = {
        9: ratbag.ActionSpecial.Special.WHEEL_LEFT,
        10: ratbag.ActionSpecial.Special.WHEEL_RIGHT,
        13: ratbag.ActionSpecial.Special.WHEEL_UP,
        14: ratbag.ActionSpecial.Special.WHEEL_DOWN,
        # 16 quicklaunch  -> hidraw report 03 00 60 07 01 00 00 00
        16: ratbag.ActionSpecial.Special.PROFILE_CYCLE_UP,
        17: ratbag.ActionSpecial.Special.PROFILE_UP,
        18: ratbag.ActionSpecial.Special.PROFILE_DOWN,
        20: ratbag.ActionSpecial.Special.RESOLUTION_CYCLE_UP,
        21: ratbag.ActionSpecial.Special.RESOLUTION_UP,
        22: ratbag.ActionSpecial.Special.RESOLUTION_DOWN,
        # 27 open driver  -> hidraw report 02 83 01 00 00 00 00 00
        65: ratbag.ActionSpecial.Special.SECOND_MODE,
    }

    # firmware key value vs ratbag value
    keycodes = {
        26: ratbag.hid.Key.KEY_LEFT_GUI,
        32: ratbag.hid.ConsumerControl.CC_AL_CONSUMER_CONTROL_CONFIG,
        33: ratbag.hid.ConsumerControl.CC_SCAN_PREVIOUS_TRACK,
        34: ratbag.hid.ConsumerControl.CC_SCAN_NEXT_TRACK,
        35: ratbag.hid.ConsumerControl.CC_PLAY_PAUSE,
        36: ratbag.hid.ConsumerControl.CC_STOP,
        37: ratbag.hid.ConsumerControl.CC_MUTE,
        38: ratbag.hid.ConsumerControl.CC_VOLUME_UP,
        39: ratbag.hid.ConsumerControl.CC_VOLUME_DOWN,
    }

    def __init__(self, profile):
        self.profile = profile
        self.macros = {}  # button index: RoccatMacro
        self.num_buttons = MAX_BUTTONS

    def from_data(self, data):
        if len(data) != RoccatKeyMapping.SIZE:
            raise ratbag.ProtocolError(
                message=f"Invalid size {len(data)} for KeyMapping"
            )

        self.bytes = data
        ratbag.util.attr_from_data(self, RoccatKeyMapping.format, data, offset=0)
        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(
                f"CRC validation failed for mapping on {self.profile.idx}"
            )
        return self  # to allow for chaining

    def button_is_macro(self, index):
        """
        :return: True if the mapping at ``index`` is a macro
        """
        return self.actions[index][0] == 48

    @property
    def buttons_with_macros(self):
        """
        :return: the list of button indices that are set to macro
        """
        return [idx for idx in range(MAX_BUTTONS) if self.button_is_macro(idx)]

    def button_to_ratbag(self, idx):
        ratbag_action = None
        action = self.actions[idx][0]
        macro = self.macros.get(idx, None)
        if action == 0:
            ratbag_action = ratbag.ActionNone(self)
        elif action in [1, 2, 3]:
            ratbag_action = ratbag.ActionButton(self, action)
        # 5 is shortcut (modifier + key)
        elif action == 6:
            ratbag_action = ratbag.ActionNone(self)
        elif action in [7, 8]:
            ratbag_action = ratbag.ActionButton(self, action - 3)
        elif action in RoccatKeyMapping.specials:
            ratbag_action = ratbag.ActionSpecial(
                self, RoccatKeyMapping.specials[action]
            )
        elif action == 48:
            assert macro is not None
            name, events = macro.to_ratbag()
            ratbag_action = ratbag.ActionMacro(self, name, events)
        else:
            # For keycodes we pretend it's a macro
            assert macro is None
            try:
                macro = RoccatMacro(self, idx)
                keycode = RoccatKeyMapping.keycodes[action]
                macro.name = "keycode"
                macro.keys = [
                    (keycode, 0x1, 1),
                    (keycode, 0x0, 1),
                ]
                macro.length = 2
                name, events = macro.to_ratbag()
                ratbag_action = ratbag.ActionMacro(self, name, events)
            except KeyError:
                logger.info(f"Unsupported action type {action}")
                ratbag_action = ratbag.Action(self)
        return ratbag_action

    def button_update_from_ratbag(self, idx, ratbag_action):
        """
        Convert this button back to a driver-specific action. This is the
        invers to :meth:`from_data`.

        :return: a tuple of ``(action, macro)`` where macro may be ``None``
        """
        action = None
        if ratbag_action.type == ratbag.Action.Type.NONE:
            action = 0
        elif ratbag_action.type == ratbag.Action.Type.BUTTON:
            action = ratbag_action.button
            if action > 3:
                action += 3  # buttons 4, 5 are 7, 8
        elif ratbag_action.type == ratbag.Action.Type.SPECIAL:
            inv_specials = {v: k for k, v in RoccatKeyMapping.specials.items()}
            try:
                action = inv_specials[ratbag_action.special]
            except KeyError:
                logger.error(
                    f"Unsupported special action {ratbag_action.special}. Setting to NONE"
                )
                action = 0
        elif ratbag_action.type == ratbag.Action.Type.MACRO:
            macro = self.macros.get(idx, RoccatMacro(self, idx))
            macro.update_from_ratbag(ratbag_action)
            if macro.length != 2:
                # This is definitely a macro, not a key sequence converted to
                # a macro
                action = 48
            else:
                # Events is [(keycode, flags, wait), ...]
                events = macro.keys[:2]
                keycode1, flags, wait = events[0]
                keycode2, _, _ = events[1]
                # 2 events with the same keycode?
                if keycode1 == keycode2:
                    lut = {v.value: k for k, v in RoccatKeyMapping.keycodes.items()}
                    action = lut.get(keycode1, 48)  # it not present, it's a macro
                else:
                    action = 48  # it's a macro
            self.macros[idx] = macro

    def __bytes__(self):
        # Weirdly enough, our first KeyMapping reply has a length of zero
        if self.report_length == 0:
            self.report_length = RoccatKeyMapping.SIZE
        return ratbag.util.attr_to_data(
            self, RoccatKeyMapping.format, maps={"checksum": lambda x: crc(x)}
        )


class RoccatDevice(GObject.Object):
    def __init__(self, driver, device):
        GObject.Object.__init__(self)
        self.driver = driver
        self.hidraw_device = device
        self.profiles = []
        self.ratbag_device = ratbag.Device(self.driver, self.path, self.name)
        self.ratbag_device.connect("commit", self.cb_commit)

    @property
    def name(self):
        return self.hidraw_device.name

    @property
    def path(self):
        return self.hidraw_device.path

    def start(self):
        rdesc = hidtools.hid.ReportDescriptor.from_bytes(
            self.hidraw_device.report_descriptor
        )
        if ReportID.KEY_MAPPING not in rdesc.feature_reports:
            raise ratbag.SomethingIsMissingError(
                self.name, self.path, "KeyMapping Report ID"
            )
        if ReportID.CONFIGURE_PROFILE not in rdesc.feature_reports:
            raise ratbag.SomethingIsMissingError(
                self.name, self.path, "ConfigureProfile Report ID"
            )

        # Featch current profile index
        logger.debug(f"ioctl {ReportID.PROFILE.name}")
        bs = self.hidraw_device.hid_get_feature(ReportID.PROFILE)
        current_profile_idx = bs[2]
        logger.debug(f"current profile is {current_profile_idx}")

        # To get the data out of this device, we need to set the feature
        # request to the profile we want to get first, then the subtype
        # for the profile (see ConfigureCommand)
        for idx in range(MAX_PROFILES):
            self.set_config_profile(idx, ConfigureCommand.SETTINGS)

            # Profile settings
            logger.debug(f"ioctl {ReportID.SETTINGS.name} for profile {idx}")
            bs = self.hidraw_device.hid_get_feature(ReportID.SETTINGS)
            profile = RoccatProfile(idx).from_data(bytes(bs))
            profile.active = idx == current_profile_idx

            # Key mappings for this profile
            self.set_config_profile(idx, ConfigureCommand.ZERO)
            self.set_config_profile(idx, ConfigureCommand.KEY_MAPPING)
            logger.debug(f"ioctl {ReportID.KEY_MAPPING.name} for profile {idx}")
            bs = self.hidraw_device.hid_get_feature(ReportID.KEY_MAPPING)
            mapping = RoccatKeyMapping(profile).from_data(bytes(bs))
            profile.key_mapping = mapping

            # Macros are in a separate HID Report, fetch those and store them
            # in the KeyMapping class
            for bidx in mapping.buttons_with_macros:
                self.set_config_profile(idx, ConfigureCommand.ZERO)
                self.set_config_profile(idx, bidx)

                logger.debug(f"ioctl {ReportID.MACRO.name} for button {idx}.{bidx}")
                bs = self.hidraw_device.hid_get_feature(ReportID.MACRO)
                macro = RoccatMacro(mapping, bidx).from_data(bytes(bs))
                mapping.macros[bidx] = macro

            self.profiles.append(profile)

        # We should all be nicely set up, let's init the ratbag side of it
        for p in self.profiles:
            ratbag_profile = p.init_ratbag_profile(self.ratbag_device)
            self.ratbag_device.add_profile(ratbag_profile)
        return self.ratbag_device

    def set_config_profile(self, profile, type):
        bs = struct.pack("BBB", ReportID.CONFIGURE_PROFILE, profile, type)
        logger.debug(
            f"ioctl {ReportID.CONFIGURE_PROFILE.name} for idx {profile} type {type}"
        )
        self.hidraw_device.hid_set_feature(ReportID.CONFIGURE_PROFILE, bs)
        self.wait()

    def wait(self):
        time.sleep(0.01)
        # Let's try up to 10 times
        for _ in range(10):
            if self.ready:
                break
            time.sleep(0.01)
        else:
            raise ratbag.ProtocolError(
                message="Timeout while waiting for device to be ready"
            )

    @property
    def ready(self):
        bs = self.hidraw_device.hid_get_feature(ReportID.CONFIGURE_PROFILE)
        if bs[1] == 0x3:
            time.sleep(0.1)
        elif bs[1] == 0x2:
            # FIXME: What is 0x2? libratbag returned this as-is but
            # (sometimes) treated it as error but not for reading profiles, so
            # let's assume this is a success
            return True

        return bs[1] == 0x1

    def cb_commit(self, ratbag_device):
        try:
            assert self.ratbag_device == ratbag_device
            logger.debug(f"Commiting to device {self.name}")
            for ratbag_profile in [
                p for p in ratbag_device.profiles.values() if p.dirty
            ]:
                profile = self.profiles[ratbag_profile.index]
                logger.debug(f"Profile {profile.idx} has changes")
                profile.update_report_rate(ratbag_profile.report_rate)

                for ratbag_resolution in [
                    r for r in ratbag_profile.resolutions.values() if r.dirty
                ]:
                    logger.debug(
                        f"Resolution {profile.idx}.{ratbag_resolution.index} has changed to {ratbag_resolution.dpi}"
                    )
                    profile.update_dpi(
                        ratbag_resolution.index,
                        ratbag_resolution.dpi,
                        ratbag_resolution.enabled,
                    )

                for ratbag_button in [
                    b for b in ratbag_profile.buttons.values() if b.dirty
                ]:
                    logger.debug(
                        f"Button {profile.idx}.{ratbag_button.index} has changed to {ratbag_button.action}"
                    )
                    profile.key_mapping.button_update_from_ratbag(
                        ratbag_button.index, ratbag_button.action
                    )
                    if profile.key_mapping.button_is_macro(ratbag_button.index):
                        macro_bytes = bytes(
                            profile.key_mapping.macros[ratbag_button.index]
                        )
                        logger.debug(f"Updating macro with {as_hex(macro_bytes)}")
                        self.write(ReportID.MACRO, macro_bytes)

                keymap_bytes = bytes(profile.key_mapping)
                logger.debug(f"Updating keymapping with {as_hex(keymap_bytes)}")
                self.write(ReportID.KEY_MAPPING, keymap_bytes)
                profile_bytes = bytes(profile)
                logger.debug(f"Updating profile with {as_hex(profile_bytes)}")
                self.write(ReportID.SETTINGS, profile_bytes)
        except Exception as e:
            logger.critical(f"::::::: ERROR: Exception during commit: {e}")
            traceback.print_exc()

    def write(self, report_id, bs):
        self.hidraw_device.hid_set_feature(int(report_id), bs)
        self.wait()


class RoccatDriver(ratbag.drivers.Driver):
    def __init__(self):
        super().__init__()
        self.device = None  # the roccat device

    def probe(self, device, info, config):
        hidraw_device = ratbag.drivers.Rodent.from_device(device)

        # This is the device that will handle everything for us
        roccat_device = RoccatDevice(self, hidraw_device)

        # The driver is in charge of connecting the recorders though, we only
        # have generic ones so far anyway. This needs to be done before
        # device.start() so we don't miss any communication.
        for rec in self.recorders:
            hidraw_device.connect_to_recorder(rec)
            rec.init(
                {
                    "name": self.device.name,
                    "driver": "roccat",
                    "path": self.device.path,
                    "report_descriptor": self.hidraw_device.report_descriptor,
                }
            )

        # Calling start() will make the device talk to the physical device
        try:
            ratbag_device = roccat_device.start()
            self.emit("device-added", ratbag_device)
        except ratbag.ProtocolError as e:
            e.name = roccat_device.name
            e.path = roccat_device.path


def load_driver(driver_name):
    assert driver_name == "roccat"
    return RoccatDriver()
