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

from typing import Any, Dict, List, Tuple

from gi.repository import GObject

import ratbag
import ratbag.hid
import ratbag.driver
import ratbag.util
from ratbag.parser import Spec, Parser

from ratbag.util import as_hex

logger = logging.getLogger(__name__)

MAX_PROFILES: int = 5
MAX_BUTTONS: int = 24


def crc(data: bytes):
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

    SELECT_PROFILE = 0x4
    CURRENT_PROFILE = 0x5
    PROFILE_SETTINGS = 0x6
    KEY_MAPPING = 0x7
    MACRO = 8


class RoccatProfile(object):
    """
    Represents the reply from the :attr:`ReportID.PROFILE_SETTINGS` feature request.
    In ratbag parlance this is called a profile, so let's use that name here
    too.

    .. attribute:: name

        The profile name. This is software-generated, the device doesn't have
        profile names.

    .. attribute:: data

        The raw bytes represeting this profile

    """

    SIZE: int = 43

    format: List[Spec] = [
        Spec("B", "report_id"),
        Spec("B", "report_length"),
        Spec("B", "profile_id"),
        Spec("B", "xy_linked"),
        Spec("B", "x_sensitivity"),
        Spec("B", "y_sensitivity"),
        Spec("B", "dpi_mask"),
        Spec("BBBBB", "xres"),
        Spec("B", "current_dpi"),
        Spec("BBBBB", "yres"),
        Spec("B", "_"),
        Spec("B", "_report_rate_idx"),
        Spec("B" * 21, "_"),  # 21 bytes padding
        Spec("H", "checksum", endian="le", convert_to_data=lambda x: crc(x.bytes)),
    ]

    report_rates = [125, 250, 500, 1000]

    def __init__(self, idx: int):
        self.idx = idx
        self.name = f"Profile {idx}"
        self.active = False
        self.ratbag_profile = None
        self.key_mapping = None
        self.dpi_mask = 0
        Parser.to_object(
            data=bytes([0] * RoccatProfile.SIZE),
            specs=RoccatProfile.format,
            obj=self,
        )
        self.report_id = ReportID.PROFILE_SETTINGS.value
        self.report_length = RoccatProfile.SIZE

    @property
    def dpi(self) -> Tuple[Tuple[int, int], ...]:
        # the x/y dpi is in multiples of 50 but if it's disabled we force it
        # to 0 instead
        return tuple(
            (x * 50, y * 50) if self.dpi_mask & (1 << idx) else (0, 0)
            for idx, (x, y) in enumerate(zip(self.xres, self.yres))
        )

    @property
    def report_rate(self) -> int:
        return RoccatProfile.report_rates[self._report_rate_idx]

    def from_data(self, data):
        if len(data) != RoccatProfile.SIZE:
            raise ratbag.ProtocolError(f"Invalid size {len(data)} for Profile")

        Parser.to_object(
            data=data,
            specs=RoccatProfile.format,
            obj=self,
        )

        # Checksum first because if we have garbage, don't touch anything
        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(f"CRC validation failed for profile {self.idx}")

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
            active=self.active,
        )
        for (dpi_idx, dpi) in enumerate(self.dpi):
            dpi_list = tuple(range(200, 8200 + 1, 50))
            caps = [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]
            ratbag.Resolution.create(
                p,
                dpi_idx,
                dpi,
                enabled=self.dpi_is_enabled(dpi_idx),
                capabilities=caps,
                dpi_list=dpi_list,
            )

        for btn_idx in range(self.key_mapping.num_buttons):
            caps = [
                ratbag.Action.Type.BUTTON,
                ratbag.Action.Type.SPECIAL,
                ratbag.Action.Type.MACRO,
            ]
            action = self.key_mapping.button_to_ratbag(btn_idx)
            ratbag.Button.create(p, btn_idx, types=caps, action=action)

        self.ratbag_profile = p
        return p

    def update_dpi(self, index, values, is_enabled):
        assert len(values) == 2
        self.xres = self.xres[:index] + (values[0] // 50,) + self.xres[index + 1 :]
        self.yres = self.yres[:index] + (values[1] // 50,) + self.yres[index + 1 :]
        self.xy_linked = all([x == y for x, y in zip(self.xres, self.yres)])
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
        return Parser.from_object(
            specs=RoccatProfile.format,
            obj=self,
        )


class RoccatMacro(object):
    """
    Represents the reply from the :attr:`ReportID.MACRO` feature request.
    """

    SIZE = 2082
    NKEYS = 500
    NAMELEN = 24

    format = [
        Spec("B", "report_id"),
        Spec("H", "report_length", endian="le"),
        Spec("B", "profile"),
        Spec("B", "button_idx"),
        Spec("B", "active"),
        Spec("B" * 24, "_"),
        Spec("B" * NAMELEN, "_group"),
        Spec("B" * NAMELEN, "_name"),
        Spec("H", "length", endian="le"),
        Spec(f"BBH", "_keys", endian="le", repeat=NKEYS),  # keycode, flag, time
        Spec("H", "checksum", endian="le", convert_to_data=lambda x: crc(x.bytes)),
    ]

    def __init__(self, profile_idx, button_idx):
        # Init everything with zeroes so we have all attributes we need
        Parser.to_object(
            data=bytes([0x00] * RoccatMacro.SIZE),
            specs=RoccatMacro.format,
            obj=self,
        )
        self.report_id = ReportID.MACRO.value
        self.report_length = RoccatMacro.SIZE
        self.profile = profile_idx
        self.button_idx = button_idx
        self.name = f"macro on {profile_idx}.{button_idx}"
        self.group = "g0"
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
                self.update_key(offset, (keycode, flag, wait_time))
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
            self.update_key(offset, (keycode, flag, wait_time))
            offset += 1

        self.length = offset
        self._macro_exists_on_device = True

    @property
    def keys(self):
        return self._keys[: self.length]

    @keys.setter
    def keys(self, keys):
        for idx, k in enumerate(keys):
            self._keys[idx] = k
        self.length = len(keys)

    def update_key(self, index, key):
        # This only extends the length, but doesn't shorten it
        assert index < RoccatMacro.NKEYS
        self._keys[index] = key
        self.length = max(self.length, index + 1)

    @property
    def name(self):
        return bytes(self._name).decode("utf-8").rstrip("\x00")

    @name.setter
    def name(self, name):
        name = bytearray(name[: RoccatMacro.NAMELEN].encode("utf-8"))
        self._name = tuple(bytes(name).ljust(RoccatMacro.NAMELEN, b"\x00"))

    @property
    def group(self):
        return bytes(self._group).decode("utf-8").rstrip("\x00")

    @group.setter
    def group(self, group):
        group = bytearray(group[: RoccatMacro.NAMELEN].encode("utf-8"))
        self._group = tuple(bytes(group).ljust(RoccatMacro.NAMELEN, b"\x00"))

    def from_data(self, data):
        if len(data) != RoccatMacro.SIZE:
            raise ratbag.ProtocolError(message=f"Invalid size {len(data)} for Macro")

        Parser.to_object(
            data=data,
            specs=RoccatMacro.format,
            obj=self,
        )

        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(
                f"CRC validation failed for macro on button {self.profile}.{self.button_idx}"
            )

        return self  # to allow for chaining

    def __bytes__(self):
        if not self._macro_exists_on_device:
            self.active = 0x01

        return Parser.from_object(
            specs=RoccatMacro.format,
            obj=self,
        )


class RoccatKeyMapping(object):
    """
    Represents the reply from the :attr:`ReportID.KEY_MAPPING` feature request.
    """

    SIZE = 77

    format = [
        Spec("B", "report_id"),
        Spec("B", "report_length"),
        Spec("B", "profile_id"),
        Spec("BBB", "actions", repeat=MAX_BUTTONS),  # action[button][0] is what we need
        Spec("H", "checksum", endian="le", convert_to_data=lambda x: crc(x.bytes)),
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

    def __init__(self, profile_idx):
        Parser.to_object(
            data=bytes([0x00] * RoccatKeyMapping.SIZE),
            specs=RoccatKeyMapping.format,
            obj=self,
        )
        self.profile_id = profile_idx
        self.macros = {}  # button index: RoccatMacro
        self.num_buttons = MAX_BUTTONS
        self.report_id = ReportID.KEY_MAPPING.value
        self.report_length = RoccatKeyMapping.SIZE

    def from_data(self, data):
        if len(data) != RoccatKeyMapping.SIZE:
            raise ratbag.ProtocolError(
                message=f"Invalid size {len(data)} for KeyMapping"
            )

        self.bytes = data
        Parser.to_object(
            data=data,
            specs=RoccatKeyMapping.format,
            obj=self,
        )

        if crc(data) != self.checksum:
            raise ratbag.ProtocolError(
                f"CRC validation failed for mapping on {self.profile_id}"
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
            ratbag_action = ratbag.ActionNone.create()
        elif action in [1, 2, 3]:
            ratbag_action = ratbag.ActionButton.create(action)
        # 5 is shortcut (modifier + key)
        elif action == 6:
            ratbag_action = ratbag.ActionNone.create()
        elif action in [7, 8]:
            ratbag_action = ratbag.ActionButton.create(action - 3)
        elif action in RoccatKeyMapping.specials:
            ratbag_action = ratbag.ActionSpecial.create(
                RoccatKeyMapping.specials[action]
            )
        elif action == 48:
            assert macro is not None
            name, events = macro.to_ratbag()
            ratbag_action = ratbag.ActionMacro.create(name=name, events=events)
        else:
            # For keycodes we pretend it's a macro
            assert macro is None
            try:
                macro = RoccatMacro(self.profile_id, idx)
                keycode = RoccatKeyMapping.keycodes[action]
                macro.name = "keycode"
                macro.keys = [
                    (keycode, 0x1, 1),
                    (keycode, 0x0, 1),
                ]
                macro.length = 2
                name, events = macro.to_ratbag()
                ratbag_action = ratbag.ActionMacro.create(name=name, events=events)
            except KeyError:
                logger.info(f"Unsupported action type {action}")
                ratbag_action = ratbag.ActionUnknown.create()
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
            if action > 5:
                raise ratbag.ConfigError(
                    f"Unable to map to button {action} on this device"
                )
            if action > 3:
                action += 3  # buttons 4, 5 are 7, 8
        elif ratbag_action.type == ratbag.Action.Type.SPECIAL:
            inv_specials = {v: k for k, v in RoccatKeyMapping.specials.items()}
            try:
                action = inv_specials[ratbag_action.special]
            except KeyError:
                raise ratbag.ConfigError(
                    "Unsupported special action {ratbag_action.special}"
                )
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
        else:
            raise ratbag.ConfigError(
                "Unable to map action type {ratbag_action.type.name} on this device"
            )
        self.actions[idx] = (action, 0, 0)

    def __bytes__(self):
        # Weirdly enough, our first KeyMapping reply has a length of zero
        if self.report_length == 0:
            self.report_length = RoccatKeyMapping.SIZE
        return Parser.from_object(
            specs=RoccatKeyMapping.format,
            obj=self,
        )


class RoccatDevice(GObject.Object):
    def __init__(self, driver, rodent):
        GObject.Object.__init__(self)
        self.driver = driver
        self.hidraw_device = rodent
        self.profiles = []
        self.ratbag_device = ratbag.Device.create(
            self.driver, self.path, self.name, model=rodent.model
        )
        self.ratbag_device.connect("commit", self.cb_commit)

    @property
    def name(self):
        return self.hidraw_device.name

    @property
    def path(self):
        return self.hidraw_device.path

    def start(self):
        feature_reports = self.hidraw_device.report_ids["feature"]
        if ReportID.KEY_MAPPING not in feature_reports:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device, "KeyMapping Report ID"
            )
        if ReportID.SELECT_PROFILE not in feature_reports:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device, "ConfigureProfile Report ID"
            )

        # Fetch current profile index
        logger.debug(f"ioctl {ReportID.CURRENT_PROFILE.name}")
        bs = self.hidraw_device.hid_get_feature(ReportID.CURRENT_PROFILE)
        current_profile_idx = bs[2]
        logger.debug(f"current profile is {current_profile_idx}")

        # To get the data out of this device, we need to set the feature
        # request to the profile we want to get first, then the subtype
        # for the profile (see ConfigureCommand)
        for idx in range(MAX_PROFILES):
            self.set_config_profile(idx, ConfigureCommand.SETTINGS)

            # Profile settings
            logger.debug(f"ioctl {ReportID.PROFILE_SETTINGS.name} for profile {idx}")
            bs = self.hidraw_device.hid_get_feature(ReportID.PROFILE_SETTINGS)
            profile = RoccatProfile(idx).from_data(bytes(bs))
            profile.active = idx == current_profile_idx

            # Key mappings for this profile
            self.set_config_profile(idx, ConfigureCommand.ZERO)
            self.set_config_profile(idx, ConfigureCommand.KEY_MAPPING)
            logger.debug(f"ioctl {ReportID.KEY_MAPPING.name} for profile {idx}")
            bs = self.hidraw_device.hid_get_feature(ReportID.KEY_MAPPING)
            mapping = RoccatKeyMapping(profile.idx).from_data(bytes(bs))
            profile.key_mapping = mapping

            # Macros are in a separate HID Report, fetch those and store them
            # in the KeyMapping class
            for bidx in mapping.buttons_with_macros:
                self.set_config_profile(idx, ConfigureCommand.ZERO)
                self.set_config_profile(idx, bidx)

                logger.debug(f"ioctl {ReportID.MACRO.name} for button {idx}.{bidx}")
                bs = self.hidraw_device.hid_get_feature(ReportID.MACRO)
                macro = RoccatMacro(idx, bidx).from_data(bytes(bs))
                mapping.macros[bidx] = macro

            self.profiles.append(profile)

        # We should all be nicely set up, let's init the ratbag side of it
        for p in self.profiles:
            p.init_ratbag_profile(self.ratbag_device)
        return self.ratbag_device

    def set_config_profile(self, profile, type):
        bs = struct.pack("BBB", ReportID.SELECT_PROFILE, profile, type)
        logger.debug(
            f"ioctl {ReportID.SELECT_PROFILE.name} for idx {profile} type {type}"
        )
        self.hidraw_device.hid_set_feature(ReportID.SELECT_PROFILE, bs)
        self.wait()

    def wait(self):
        time.sleep(0.01)
        # Let's try up to 10 times
        for _ in range(10):
            if self.ready:
                break
            time.sleep(0.01)
        else:
            raise ratbag.driver.ProtocolError.from_rodent(
                rodent=self.hidraw_device,
                message="Timeout while waiting for device to be ready",
            )

    @property
    def ready(self):
        bs = self.hidraw_device.hid_get_feature(ReportID.SELECT_PROFILE)
        if bs[1] == 0x3:
            time.sleep(0.1)
        elif bs[1] == 0x2:
            # FIXME: What is 0x2? libratbag returned this as-is but
            # (sometimes) treated it as error but not for reading profiles, so
            # let's assume this is a success
            return True

        return bs[1] == 0x1

    def cb_commit(
        self, ratbag_device: ratbag.Device, transaction: ratbag.CommitTransaction
    ):
        def is_dirty(feature):
            return feature.dirty

        success = True
        try:
            assert self.ratbag_device == ratbag_device
            logger.debug(f"Commiting to device {self.name}")
            for ratbag_profile in filter(is_dirty, ratbag_device.profiles):
                profile = self.profiles[ratbag_profile.index]
                logger.debug(f"Profile {profile.idx} has changes")
                profile.update_report_rate(ratbag_profile.report_rate)

                for ratbag_resolution in filter(is_dirty, ratbag_profile.resolutions):
                    logger.debug(
                        f"Resolution {profile.idx}.{ratbag_resolution.index} has changed to {ratbag_resolution.dpi}"
                    )
                    profile.update_dpi(
                        ratbag_resolution.index,
                        ratbag_resolution.dpi,
                        ratbag_resolution.enabled,
                    )

                for ratbag_button in filter(is_dirty, ratbag_profile.buttons):
                    logger.debug(
                        f"Button {profile.idx}.{ratbag_button.index} has changed to {ratbag_button.action}"
                    )
                    try:
                        profile.key_mapping.button_update_from_ratbag(
                            ratbag_button.index, ratbag_button.action
                        )
                        if profile.key_mapping.button_is_macro(ratbag_button.index):
                            macro_bytes = bytes(
                                profile.key_mapping.macros[ratbag_button.index]
                            )
                            logger.debug(f"Updating macro with {as_hex(macro_bytes)}")
                            self.write(ReportID.MACRO, macro_bytes)
                    except ratbag.ConfigError as e:
                        logger.error(f"{e}")
                        success = False

                keymap_bytes = bytes(profile.key_mapping)
                logger.debug(f"Updating keymapping with {as_hex(keymap_bytes)}")
                self.write(ReportID.KEY_MAPPING, keymap_bytes)
                profile_bytes = bytes(profile)
                logger.debug(f"Updating profile with {as_hex(profile_bytes)}")
                self.write(ReportID.PROFILE_SETTINGS, profile_bytes)
        except Exception as e:
            logger.critical(f"::::::: ERROR: Exception during commit: {e}")
            traceback.print_exc()
            success = False

        transaction.complete(success=success)

    def write(self, report_id, bs):
        self.hidraw_device.hid_set_feature(int(report_id), bs)
        self.wait()


@ratbag.driver.ratbag_driver("roccat")
class RoccatDriver(ratbag.driver.HidrawDriver):
    def probe(
        self,
        rodent: ratbag.driver.Rodent,
        config: ratbag.driver.DeviceConfig,
    ) -> None:
        # This is the device that will handle everything for us
        roccat_device = RoccatDevice(self, rodent)

        # Calling start() will make the device talk to the physical device
        ratbag_device = roccat_device.start()
        self.emit("device-added", ratbag_device)
