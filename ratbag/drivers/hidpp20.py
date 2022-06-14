#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

from typing import Any, Dict, List, Optional, Tuple, Type

import attr
import enum
import logging
import pathlib

from gi.repository import GObject

import ratbag
import ratbag.hid
from ratbag.parser import Parser, Spec
from ratbag.driver import HidrawMonitor, ratbag_driver

logger = logging.getLogger(__name__)


RECEIVER_IDX = 0xFF


class ReportID(enum.IntEnum):
    SHORT = 0x10
    LONG = 0x11

    @property
    def size(self):
        return {ReportID.LONG: 20, ReportID.SHORT: 7}[self]


class FeatureName(enum.IntEnum):
    ROOT = 0x0000
    FEATURE_SET = 0x0001
    DEVICE_INFO = 0x0003
    DEVICE_NAME = 0x0005
    PAGE_RESET = 0x0020
    BATTERY_LEVEL_STATUS = 0x1000
    BATTERY_VOLTAGE = 0x1001
    LED_SW_CONTROL = 0x1300
    KBD_REPROGRAMMABLE_KEYS = 0x1B00
    SPECIAL_KEYS_BUTTONS = 0x1B04
    MOUSE_POINTER_BASIC = 0x2200
    ADJUSTIBLE_DPI = 0x2201
    ADJUSTIBLE_REPORT_RATE = 0x8060
    COLOR_LED_EFFECTS = 0x8070
    RGB_EFFECTS = 0x8071
    ONBOARD_PROFILES = 0x8100
    MOUSE_BUTTON_SPY = 0x8110


class OnboardProfile:
    class MemoryType(enum.IntEnum):
        G402 = 0x01

    class ProfileType(enum.IntEnum):
        G402 = 0x01
        G303 = 0x02
        G900 = 0x03
        G915 = 0x04

    class MacroType(enum.IntEnum):
        G402 = 0x01

    class Mode(enum.IntEnum):
        NO_CHANGE = 0x00
        ONBOARD = 0x01
        HOST = 0x02

    class Sector(enum.IntEnum):
        USER_PROFILES_G402 = 0x0000
        ROM_PROFILES_G402 = 0x0100

        END_OF_PROFILE_DIRECTORY = 0xFFFF
        ENABLED_INDEX = 2


class LogicalMapping(enum.IntEnum):
    NONE = 0
    VOLUME_UP = 1
    VOLUME_DOWN = 2
    MUTE = 3
    PLAY_PAUSE = 4
    NEXT = 5
    PREVIOUS = 6
    STOP = 7
    LEFT = 80
    RIGHT = 81
    MIDDLE = 82
    BACK = 83
    FORWARD = 86
    BUTTON6 = 89
    BUTTON7 = 90
    LEFT_SCROLL = 91
    BUTTON8 = 92
    RIGHT_SCROLL = 93
    BUTTON9 = 94
    BUTTON10 = 95
    BUTTON11 = 96
    BUTTON12 = 97
    BUTTON13 = 98
    BUTTON14 = 99
    BUTTON15 = 100
    BUTTON16 = 101
    BUTTON17 = 102
    BUTTON18 = 103
    BUTTON19 = 104
    BUTTON20 = 105
    BUTTON21 = 106
    BUTTON22 = 107
    BUTTON23 = 108
    BUTTON24 = 109
    SECOND_LEFT = 184
    APPSWITCHGESTURE = 195
    SMARTSHIFT = 196
    LEDTOGGLE = 315


class PhysicalMapping(enum.IntEnum):
    NONE = 0
    VOLUME_UP = 1
    VOLUME_DOWN = 2
    MUTE = 3
    PLAY_PAUSE = 4
    NEXT = 5
    PREVIOUS = 6
    STOP = 7
    LEFT_CLICK = 56
    RIGHT_CLICK = 57
    MIDDLE_CLICK = 58
    WHEEL_SIDE_CLICK_LEFT = 59
    BACK_CLICK = 60
    WHEEL_SIDE_CLICK_RIGHT = 61
    FORWARD_CLICK = 62
    LEFT_SCROLL = 63
    RIGHT_SCROLL = 64
    DO_NOTHING = 98
    GESTURE_BUTTON = 156
    SMARTSHIFT = 157
    GESTURE_BUTTON2 = (
        169  # should be GESTURE_BUTTON too but we can't do that with an enum
    )
    LEDTOGGLE = 221


# the following crc computation has been provided by Logitech
def crc(data: bytes) -> int:
    def clamp(v: int) -> int:
        return v & 0xFFFF  # because we can't force python to use 16bit

    crc = 0xFFFF  # seed
    for v in data:
        tmp = clamp((crc >> 8) ^ v)
        crc = clamp(crc << 8)
        quick = clamp(tmp ^ (tmp >> 4))
        crc = clamp(crc ^ quick)
        quick = clamp(quick << 5)
        crc = clamp(crc ^ quick)
        quick = clamp(quick << 7)
        crc = clamp(crc ^ quick)
    return crc


@attr.s
class Feature(object):
    name: FeatureName = attr.ib()
    index: int = attr.ib()
    type: int = attr.ib()
    version: int = attr.ib()


@attr.s
class Color:
    red: int = attr.ib()
    green: int = attr.ib()
    blue: int = attr.ib()

    def __str__(self):
        return f"rgb({self.red},{self.green},{self.blue})"

    def __iter__(self):
        yield self.red
        yield self.green
        yield self.blue


@attr.s
class Profile(object):
    address: int = attr.ib()
    """
    The memory address where this profile resides
    """
    enabled: bool = attr.ib(default=False)
    dpi_list: List[int] = attr.ib(default=attr.Factory(list))
    report_rates: List[int] = attr.ib(default=attr.Factory(list))
    initial_data: bytes = attr.ib(default=bytes())
    leds: List["Led"] = attr.ib(default=attr.Factory(list))
    buttons: List["Button"] = attr.ib(default=attr.Factory(list))
    """
    The initial data this profile was created from. This data is constant
    for the life of the profile and can be used to restore the profile to
    its original state.
    """

    @property
    def name(self) -> str:
        try:
            self._name.index(b"\xff")  # type: ignore
        except ValueError:
            # we're not using the default name, so let's decode this
            # On my device the name is utf-16, not utf-8, decoding it as
            # utf-8 will produce a string that's not compatible with DBus
            # I'm not sure if this is default or just happens to be the case
            # on this device
            return bytes(self._name).decode("utf-16").rstrip("\x00")  # type: ignore

        return f"Profile {self.address}"

    @classmethod
    def from_data(cls, address: int, enabled: bool, data: bytes):
        profile = cls(address, enabled, initial_data=data)
        spec = [
            Spec("B", "report_rate", convert_from_data=lambda x: 1000 // max(1, x)),
            Spec("B", "default_dpi"),
            Spec("B", "switched_dpi"),
            Spec("HHHHH", "dpi", endian="le"),
            Spec("BBB", "colors"),
            Spec("B", "power_mode"),
            Spec("B", "angle_snapping"),
            Spec("B" * 10, "_"),  # reserved
            Spec("H", "powersafe_timeout", endian="le"),
            Spec("H", "poweroff_timeout", endian="le"),
            Spec("BBBB", "_button_bindings", repeat=16),
            Spec("BBBB", "_alternate_button_bindings", repeat=16),
            Spec("B" * 16 * 3, "_name"),
            Spec("B" * 11, "_leds", repeat=2),
            Spec("B" * 11, "_alt_leds", repeat=2),
            Spec("BB", "_"),
        ]

        Parser.to_object(data, spec, profile)
        for leddata in profile._leds:  # type: ignore
            led = Led.from_data(bytes(leddata))
            logger.debug(led)
            profile.leds.append(led)

        for buttondata in profile._button_bindings:  # type: ignore
            b = Button.from_data(bytes(buttondata))
            logger.debug(b)
            profile.buttons.append(b)

        return profile

    def __str__(self):
        return (
            f"{self.name or '<unnamed>'}: {self.report_rate}Hz, "
            f"{self.default_dpi}/{self.switched_dpi}dpi "
            f"{[x for x in self.dpi]} "
            f"{self.colors} "
            f"timeouts:{self.powersafe_timeout}/{self.poweroff_timeout}"
        )


@attr.s
class ProfileAddress(object):
    address: int = attr.ib()
    enabled: bool = attr.ib()
    index: int = attr.ib()

    @classmethod
    def from_sector(cls, data: bytes, index: int):
        """
        Given data is a sector read from the device, return the profile
        address for the profile with the given index.
        """
        addr_offset = 4 * index
        spec = [Spec("H", "addr", endian="BE")]
        result = Parser.to_object(data[addr_offset:], spec).object
        if result.addr == OnboardProfile.Sector.END_OF_PROFILE_DIRECTORY:
            return None

        # profile address sanity check
        expected_addr = OnboardProfile.Sector.USER_PROFILES_G402 | (index + 1)
        if result.addr != expected_addr:
            logger.error(
                f"profile {index}: expected address 0x{expected_addr:04x}, have 0x{result.address:04x}"
            )

        enabled = data[addr_offset + OnboardProfile.Sector.ENABLED_INDEX] != 0

        return cls(address=result.addr, enabled=enabled, index=index)


@attr.s
class Button(object):
    """
    Parent class for all buttons. Buttons have a type which is used to
    instantiate the actual object parsed, see :meth:`Button.from_data`.

    Those subclasses have the specific parsing instructions then.
    """

    class Type(enum.IntEnum):
        MACRO = 0x00
        HID = 0x80
        SPECIAL = 0x90
        DISABLED = 0xFF

        @staticmethod
        def get_class(type: "Button.Type") -> Type["Button"]:
            return {
                Button.Type.MACRO: ButtonMacro,
                Button.Type.HID: ButtonHid,  # Should never be instantiated directly
                Button.Type.SPECIAL: ButtonMacro,
                Button.Type.DISABLED: ButtonDisabled,
            }[type]

        @staticmethod
        def from_class(obj: "Button") -> "Button.Type":
            mapping = {
                ButtonMacro: Button.Type.MACRO,
                ButtonHid: Button.Type.HID,
                ButtonSpecial: Button.Type.SPECIAL,
                ButtonDisabled: Button.Type.DISABLED,
            }
            return next(iter(v for k, v in mapping.items() if isinstance(obj, k)))

    class HidType(enum.IntEnum):
        NOOP = 0x00
        MOUSE = 0x01
        KEYBOARD = 0x02
        CONSUMER_CONTROL = 0x03

        @staticmethod
        def get_class(type: "Button.HidType") -> Type["ButtonHid"]:
            return {
                Button.HidType.NOOP: ButtonNoop,
                Button.HidType.MOUSE: ButtonButton,
                Button.HidType.KEYBOARD: ButtonKeyboard,
                Button.HidType.CONSUMER_CONTROL: ButtonConsumerControl,
            }[type]

        @staticmethod
        def from_class(obj: "ButtonHid") -> "Button.HidType":
            mapping = {
                ButtonNoop: Button.HidType.NOOP,
                ButtonButton: Button.HidType.MOUSE,
                ButtonKeyboard: Button.HidType.KEYBOARD,
                ButtonConsumerControl: Button.HidType.CONSUMER_CONTROL,
            }
            return next(iter(v for k, v in mapping.items() if isinstance(obj, k)))

    type: "Type" = attr.ib()

    @type.validator
    def type_validator(self, attribute, value):
        if value != Button.Type.from_class(self):
            raise ValueError(f"Invalid type {value} for {type(self)}")

    @classmethod
    def from_data(cls, data: bytes) -> "Button":
        type = Button.Type(data[0])
        if type == Button.Type.HID:
            hidtype = Button.HidType(data[1])
            if hidtype == Button.HidType.MOUSE:
                clstype: Type = ButtonButton
            elif hidtype == Button.HidType.KEYBOARD:
                clstype = ButtonKeyboard
            elif hidtype == Button.HidType.CONSUMER_CONTROL:
                clstype = ButtonConsumerControl
        elif type == Button.Type.SPECIAL:
            clstype = ButtonSpecial
        elif type == Button.Type.MACRO:
            clstype = ButtonMacro
        elif type == Button.Type.DISABLED:
            clstype = ButtonDisabled
        else:
            logger.error("Unable to handle button type {data[0]}")
            clstype = ButtonDisabled

        return Parser.to_object(data, clstype.specs, result_class=clstype).object


@attr.s
class ButtonHid(Button):
    type: Button.Type = attr.ib()
    hidtype: Button.HidType = attr.ib()

    @hidtype.validator
    def hidtype_validator(self, attribute, value):
        if value != Button.HidType.from_class(self):
            raise ValueError(f"Invalid type {value} for {type(self)}")


@attr.s
class ButtonNoop(ButtonHid):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "hidtype", convert_from_data=lambda x: Button.HidType(x)),
    ]
    type: Button.Type = attr.ib()
    hidtype: Button.HidType = attr.ib()


@attr.s
class ButtonButton(ButtonHid):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "hidtype", convert_from_data=lambda x: Button.HidType(x)),
        Spec("H", "button", convert_from_data=lambda x: ratbag.util.ffs(x)),
    ]
    type: Button.Type = attr.ib()
    hidtype: Button.HidType = attr.ib()
    button: int = attr.ib()


@attr.s
class ButtonKeyboard(Button):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "hidtype", convert_from_data=lambda x: Button.HidType(x)),
        Spec("B", "modifier_flags"),
        Spec("B", "key"),
    ]
    type: Button.Type = attr.ib()
    hidtype: Button.HidType = attr.ib()
    modifier_flags: int = attr.ib()
    key: int = attr.ib()


@attr.s
class ButtonConsumerControl(Button):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "hidtype", convert_from_data=lambda x: Button.HidType(x)),
        Spec("H", "consumer_control"),
    ]
    type: Button.Type = attr.ib()
    consumer_control: int = attr.ib()
    hidtype: Button.HidType = attr.ib(
        init=False, default=Button.HidType.CONSUMER_CONTROL
    )


@attr.s
class ButtonSpecial(Button):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "special"),
        Spec("B", "__reserved"),  # ignored
        Spec("B", "profile"),
    ]
    type: Button.Type = attr.ib()
    special: int = attr.ib()
    profile: int = attr.ib()

    @property
    def ratbag_special(self) -> ratbag.ActionSpecial.Special:
        mapping = {
            0x01: ratbag.ActionSpecial.Special.WHEEL_LEFT,
            0x02: ratbag.ActionSpecial.Special.WHEEL_RIGHT,
            0x03: ratbag.ActionSpecial.Special.RESOLUTION_UP,
            0x04: ratbag.ActionSpecial.Special.RESOLUTION_DOWN,
            0x05: ratbag.ActionSpecial.Special.RESOLUTION_CYCLE_UP,
            0x06: ratbag.ActionSpecial.Special.RESOLUTION_DEFAULT,
            0x07: ratbag.ActionSpecial.Special.RESOLUTION_ALTERNATE,
            0x08: ratbag.ActionSpecial.Special.PROFILE_UP,
            0x09: ratbag.ActionSpecial.Special.PROFILE_DOWN,
            0x0A: ratbag.ActionSpecial.Special.PROFILE_CYCLE_UP,
            0x0B: ratbag.ActionSpecial.Special.SECOND_MODE,
        }
        try:
            return mapping[self.special]
        except KeyError:
            return ratbag.ActionSpecial.Special.UNKNOWN


@attr.s
class ButtonMacro(Button):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
        Spec("B", "page"),
        Spec("B", "zero"),
        Spec("B", "offset"),
    ]
    page: int = attr.ib()
    zero: int = attr.ib()
    offset: int = attr.ib()
    type: Button.Type = attr.ib(init=False, default=Button.Type.MACRO)


@attr.s
class ButtonDisabled(Button):
    specs = [
        Spec("B", "type", convert_from_data=lambda x: Button.Type(x)),
    ]


@attr.s
class Led(object):
    class Mode(enum.IntEnum):
        OFF = 0x00
        ON = 0x01
        CYCLE = 0x03
        COLOR_WAVE = 0x04
        STARLIGHT = 0x05
        BREATHING = 0x0A
        RIPPLE = 0x0B
        CUSTOM = 0x0C

        def to_ratbag_mode(self) -> ratbag.Led.Mode:
            return {
                Led.Mode.OFF: ratbag.Led.Mode.OFF,
                Led.Mode.ON: ratbag.Led.Mode.ON,
                Led.Mode.CYCLE: ratbag.Led.Mode.CYCLE,
                # we pretend anything else is breathing
                Led.Mode.COLOR_WAVE: ratbag.Led.Mode.BREATHING,
                Led.Mode.STARLIGHT: ratbag.Led.Mode.BREATHING,
                Led.Mode.BREATHING: ratbag.Led.Mode.BREATHING,
                Led.Mode.RIPPLE: ratbag.Led.Mode.BREATHING,
                Led.Mode.CUSTOM: ratbag.Led.Mode.BREATHING,
            }.get(
                self, ratbag.Led.Mode.ON
            )  # unhandled mode is just ON

        @staticmethod
        def get_class(mode: "Led.Mode") -> Type["Led"]:
            """
            Map the :class:`Led.Mode` into the actual class expected to handle
            that particular mode.
            """
            return {
                Led.Mode.OFF: LedOff,
                Led.Mode.ON: LedOn,
                Led.Mode.CYCLE: LedCycle,
                Led.Mode.COLOR_WAVE: LedColorWave,
                Led.Mode.STARLIGHT: LedStarlight,
                Led.Mode.BREATHING: LedBreathing,
                Led.Mode.RIPPLE: LedRipple,
                Led.Mode.CUSTOM: LedCustom,
            }[mode]

        @staticmethod
        def from_obj(obj: "Led") -> int:
            """
            Map the Led subclass into the :class:`Led.Mode` it corresponds to.
            """
            mapping = {
                LedOff: Led.Mode.OFF,
                LedOn: Led.Mode.ON,
                LedCycle: Led.Mode.CYCLE,
                LedColorWave: Led.Mode.COLOR_WAVE,
                LedStarlight: Led.Mode.STARLIGHT,
                LedBreathing: Led.Mode.BREATHING,
                LedRipple: Led.Mode.RIPPLE,
                LedCustom: Led.Mode.CUSTOM,
            }
            return next(iter({v for k, v in mapping.items() if isinstance(obj, k)}))

    mode: Mode = attr.ib()

    @staticmethod
    def from_data(data: bytes) -> "Led":
        # input data are 11 bytes for this LED, first byte is the mode
        # We have a mapping of mode to class type, then instantiate that with
        # the class-specific parser spec
        mode = Led.Mode(data[0])
        cls: Type = Led.Mode.get_class(mode)
        result = Parser.to_object(bytes(data), cls.specs, result_class=cls)
        return result.object

    @mode.validator
    def mode_validator(self, attribute, value):
        if value != Led.Mode.from_obj(self):
            raise ValueError(f"Invalid mode {value} for {type(self)}")


@attr.s
class LedOn(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
        Spec("BBB", "color", convert_from_data=lambda x: Color(*x)),
    ]
    mode: Led.Mode = attr.ib()
    color: Color = attr.ib()

    @mode.validator
    def mode_validator(self, attribute, value):
        if value != Led.Mode.ON:
            raise ValueError(f"Invalid mode {value} for LedOn")


@attr.s
class LedOff(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
    ]
    mode: Led.Mode = attr.ib()


@attr.s
class LedCustom(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
    ]
    mode: Led.Mode = attr.ib()


@attr.s
class LedCycle(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
        Spec("BBBBB", "_"),
        Spec("H", "period"),
        Spec(
            "B",
            "intensity",
            convert_from_data=lambda x: x if x else 100,  # 1-100 percent, 0 means 100
        ),
    ]
    mode: Led.Mode = attr.ib()
    period: int = attr.ib(default=0)
    intensity: int = attr.ib(default=0)


@attr.s
class LedBreathing(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
        Spec("BBB", "color", convert_from_data=lambda x: Color(*x)),
        Spec("H", "period"),
        Spec("B", "waveform"),
        Spec(
            "B",
            "intensity",
            convert_from_data=lambda x: x if x else 100,  # 1-100 percent, 0 means 100
        ),
    ]
    mode: Led.Mode = attr.ib()
    color: Color = attr.ib()
    period: int = attr.ib()
    waveform: int = attr.ib()
    intensity: int = attr.ib()


@attr.s
class LedColorWave(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
    ]
    mode: Led.Mode = attr.ib()
    # Unclear what other fields are


@attr.s
class LedStarlight(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
        Spec("BBB", "color_sky", convert_from_data=lambda x: Color(*x)),
        Spec("BBB", "color_star", convert_from_data=lambda x: Color(*x)),
    ]
    mode: Led.Mode = attr.ib()
    color_sky: Color = attr.ib()
    color_star: Color = attr.ib()


@attr.s
class LedRipple(Led):
    specs = [
        Spec("B", "mode", convert_from_data=lambda x: Led.Mode(x)),
        Spec("BBB", "color", convert_from_data=lambda x: Color(*x)),
        Spec("B", "_"),
        Spec("H", "period"),
    ]
    mode: Led.Mode = attr.ib()
    color: Color = attr.ib()
    period: int = attr.ib()


class Hidpp20Device(GObject.Object):
    """
    A HID++2.0 device

    .. attribute:: index

        The device index for the Logitech receiver

    .. attribute:: supported_requests

        A list of supported requests (``ReportId.SHORT`, ``ReportId.LONG``)

    .. attribute:: protocol_version

        A (major, minor) tuple with the HID++ 2.0 protocol version

    .. attribute:: features

        A dict using :class:`FeatureName` as key and a :class:`Feature` as
        value. This dict includes only named features (listed in
        :class:`FeatureName`, other features may be supported by the device
        but are ignored.

    .. attribute:: profiles

        A list of :class:`Profile` instances
    """

    def __init__(self, hidraw_device: ratbag.driver.Rodent, device_index: int):
        GObject.Object.__init__(self)
        self.index = device_index
        self.hidraw_device = hidraw_device
        self.firmware_version = ""

    @property
    def name(self) -> str:
        return self.hidraw_device.name

    @property
    def path(self) -> pathlib.Path:
        return self.hidraw_device.path

    def start(self) -> None:
        # We require both the Long and Short report IDs for this driver
        supported = [
            id for id in self.hidraw_device.report_ids["input"] if id in tuple(ReportID)
        ]

        required = (ReportID.SHORT, ReportID.LONG)
        if not (set(supported) & set(required)):
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device, "HID++ short/long reports"
            )

        self.supported_requests = supported

        # Detect protocol version - merely for logging, we don't do anything
        # with it but it's a good first check to fail at.
        self._detect_protocol_version()
        # Find the features supported by this device (and this driver). The
        # only one we *really* require is the onboard profiles, we don't
        # bother with devices that don't have profiles
        features: Dict[FeatureName, Feature] = self._find_features()
        required_features = (FeatureName.ONBOARD_PROFILES,)
        missing_features = [f for f in required_features if f not in features]
        if missing_features:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device, f"HID++2.0 feature {missing_features}"
            )

        # Firmware version is exported to the ratbag device
        self.firmware_version = self._detect_firmware_version(features)

        # If we get here, we have profiles. Query for the various memory
        # formats first so we know what we're parsing here
        desc_query = QueryOnboardProfilesDesc.instance(features).run(self)
        logger.debug(desc_query)

        if desc_query.reply.memory_model_id != OnboardProfile.MemoryType.G402:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device,
                f"Unsupported memory model {desc_query.reply.memory_model_id}",
            )
        if desc_query.reply.macro_format_id != OnboardProfile.MacroType.G402:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device,
                f"Unsupported macro format {desc_query.reply.macro_format_id}",
            )
        try:
            OnboardProfile.ProfileType(desc_query.reply.profile_format_id)
        except ValueError:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device,
                f"Unsupported profile format {desc_query.reply.profile_format_id}",
            )

        # Check if the device uses onboard memory or software memories
        mode_query = QueryOnboardProfilesGetMode.instance(features).run(self)
        logger.debug(mode_query)
        if mode_query.reply.mode != OnboardProfile.Mode.ONBOARD:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device,
                f"Device not in Onboard mode ({mode_query.reply.mode})",
            )
            # FIXME: set the device to onboard mode here instead of throwing
            # an exception

        # if we get here, our device *should* be supported. Let's parse the
        # profiles on the device!
        self._init_profiles(
            features,
            sector_size=desc_query.reply.sector_size,
            profile_count=desc_query.reply.profile_count,
        )

    def _detect_protocol_version(self) -> Tuple[int, int]:
        # Get the protocol version and our feature set
        version = QueryProtocolVersion.instance().run(self)
        logger.debug(f"protocol version {version.reply.major}.{version.reply.minor}")
        # If this happens that's a driver misconfiguration, should be using
        # the hidpp10 driver instead
        if version.reply.major < 2:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.hidraw_device, "Protocol version 2.x"
            )
        return (version.reply.major, version.reply.minor)

    def _detect_firmware_version(self, feature_lut: Dict[FeatureName, Feature]) -> str:
        info = QueryDeviceInfoGetDeviceInfo.instance(feature_lut).run(self)
        logger.debug(info)
        for idx in range(info.reply.count):
            fwquery = QueryDeviceInfoGetFwInfo.instance(feature_lut, idx).run(self)
            logger.debug(fwquery)
            if fwquery.reply.type == QueryDeviceInfoGetFwInfo.Type.DFU:  # the DFU
                return fwquery.reply.firmware_version

        return ""

    def _find_features(self) -> Dict[FeatureName, Feature]:
        # Since we have a list of features we know how to handle, iterate
        # through those and query each. libratbag used a combination of
        # QueryGetFeature(ROOT) to get the FEATURE_SET feature, then
        # QueryFeatureSetCount and QueryFeatureSetId to list/iterate through them.
        # But since we cannot handle featuers we don't know about, we might as
        # well just query for each feature.
        features = []
        for f in [fn for fn in FeatureName if fn is not FeatureName.ROOT]:
            query = QueryGetFeature.instance(f).run(self)
            try:
                features.append(query.reply.feature)
                logger.debug(
                    f"Feature {f.name} is at index {query.reply.feature.index}"
                )
            except AttributeError:
                logger.debug(f"Feature {f.name} is not supported")
                pass
        return {f.name: f for f in features}

    def _init_profiles(
        self, features: Dict[FeatureName, Feature], sector_size: int, profile_count: int
    ) -> None:
        # Read the first sector, that has the addresses for the actual
        # profiles.
        mem_query = QueryOnboardProfilesMemReadSector.instance(
            features,
            OnboardProfile.Sector.USER_PROFILES_G402,
            sector_size=sector_size,
        ).run(self)
        logger.debug(mem_query)
        if mem_query.checksum != crc(mem_query.data):
            raise ratbag.driver.ProtocolError.from_rodent(
                self.hidraw_device, "Invalid checksum for onboard profiles"
            )

        profile_addresses = [
            ProfileAddress.from_sector(mem_query.data, idx)
            for idx in range(profile_count)
        ]

        # Do we have multiple report rates that we can select?
        # Enough to run this once per device, doesn't need to be per profile
        if FeatureName.ADJUSTIBLE_REPORT_RATE in features:
            rates_query = QueryAdjustibleReportRateGetList.instance(features).run(self)
            report_rates = rates_query.reply.report_rates
        else:
            report_rates = []

        # Do we have the special keys feature?
        # Enough to run this once per device, doesn't need to be per profile
        if FeatureName.SPECIAL_KEYS_BUTTONS in features:
            count_query = QuerySpecialKeyButtonsGetCount.instance(features).run(self)
            for idx in range(count_query.reply.count):
                info_query = QuerySpecialKeyButtonsGetInfo.instance(features, idx).run(
                    self
                )
                logger.debug(info_query)
                reporting_query = QuerySpecialKeyButtonsGetReporting.instance(
                    features, idx
                ).run(self)
                logger.debug(reporting_query)

        self.profiles = []

        # Profiles are stored in the various sectors, we need to read out each
        # sector and then parse it from the bytes we have.
        for profile_address in profile_addresses:
            if profile_address:
                profile = self._init_profile(
                    features, profile_address, sector_size=sector_size
                )
                profile.report_rates = report_rates
                logger.debug(profile)
                self.profiles.append(profile)

    def _init_profile(
        self, features, profile_address: ProfileAddress, sector_size: int
    ):
        # First sector on the device told us the address of the profile we
        # want, w can read that sector now.
        profile_query = QueryOnboardProfilesMemReadSector.instance(
            features,
            profile_address.address,
            sector_size=sector_size,
        ).run(self)
        logger.debug(profile_query)
        if profile_query.checksum != crc(profile_query.data):
            # FIXME: libratbag reads the ROM instead in this case
            logger.error(f"CRC validation failed for profile {profile_address.index}")
            return

        # If we have adjustible DPI, get the list of DPIs. That can be
        # either a fixed list or a min/max value with steps for us to
        # generate the list ourselves.
        if FeatureName.ADJUSTIBLE_DPI in features:
            scount_query = QueryAdjustibleDpiGetCount.instance(features).run(self)
            # FIXME: there's a G602 quirk for the two queries in
            # libratbag
            for idx in range(scount_query.reply.sensor_count):
                dpi_list_query = QueryAdjustibleDpiGetDpiList.instance(
                    features, idx
                ).run(self)
                logger.debug(dpi_list_query)
                if dpi_list_query.reply.dpi_steps:
                    steps = dpi_list_query.reply.dpi_steps
                    dpi_min = min(dpi_list_query.reply.dpis)
                    dpi_max = max(dpi_list_query.reply.dpis)
                    dpi_list = list(range(dpi_min, dpi_max + 1, steps))
                else:
                    dpi_list = dpi_list_query.reply.dpis

                dpi_query = QueryAdjustibleDpiGetDpi.instance(features, idx).run(self)
                logger.debug(dpi_query)
        else:
            dpi_list = []

        profile = Profile.from_data(
            address=profile_address.address,
            enabled=profile_address.enabled,
            data=profile_query.data,
        )
        profile.dpi_list = dpi_list
        # report_rate is set in the caller
        return profile

    def send(self, bytes: bytes) -> None:
        """
        Send the bytestream to the device
        """
        self.hidraw_device.send(bytes)

    def recv_sync(self) -> Optional[bytes]:
        """
        Wait until the device replies and return that bytestream
        """
        return self.hidraw_device.recv()

    def cb_commit(
        self, ratbag_device: ratbag.Device, transaction: ratbag.CommitTransaction
    ):
        transaction.complete(success=False)
        raise NotImplementedError


@ratbag_driver("hidpp20")
class Hidpp20Driver(ratbag.driver.HidrawDriver):
    """
    Implementation of the Logitech HID++ 2.0 protocol.

    Driver options supported:

        - ``Buttons``: the number of buttons exported by the device
        - ``DeviceIndex``: the HID++ device index
        - ``Leds``: the number of LEDs exported by device
        - ``ReportRate``: fixed report rate
        - ``Quirk``: the quirk to apply to this device, one of ``G305``, ``G602``

    :param config: A dict of the (lowercase) driver options
    :param quirk: ``None`` or one of :class:`Quirk`
    """

    NAME = "Logitech HID++2.0"

    class Quirk(enum.Enum):
        """Available quirks for devices"""

        G305 = "G305"
        G602 = "G602"

    def probe(self, rodent, config):
        try:
            quirk = config.quirk
            quirk = [x for x in Hidpp20Driver.Quirk if x.value == quirk][0]
        except AttributeError:
            quirk = None
        except IndexError:
            raise ratbag.ConfigError(f"Invalid quirk value '{quirk}'")

        # Usually we default to the receiver IDX and let the kernel sort it
        # out, but some devices need to have the index hardcoded in the data
        # files
        index = getattr(config, "device_index", RECEIVER_IDX)
        device = Hidpp20Device(rodent, index)

        device.start()
        ratbag_device = ratbag.Device.create(
            self,
            path=device.path,
            name=device.name,
            model=rodent.model,
            firmware_version=device.firmware_version,
        )
        ratbag_device.connect("commit", device.cb_commit)
        # Device start was successful if no exception occurs. Now fill in the
        # ratbag device.
        for idx, profile in enumerate(device.profiles):
            p = ratbag.Profile.create(
                device=ratbag_device,
                index=idx,
                name=profile.name,
                report_rate=profile.report_rate,
                report_rates=profile.report_rates,
                active=idx == 0,  # FIXME
            )

            for dpi_idx, dpi in enumerate(profile.dpi):
                ratbag.Resolution.create(
                    profile=p, index=dpi_idx, dpi=(dpi, dpi), dpi_list=profile.dpi_list
                )

            for led_idx, led in enumerate(profile.leds):
                kwargs = {
                    "mode": led.mode.to_ratbag_mode(),
                    "modes": tuple(set(m.to_ratbag_mode() for m in Led.Mode)),
                    "colordepth": ratbag.Led.Colordepth.RGB_888,  # FIXME
                }
                if led.mode == Led.Mode.ON:
                    kwargs["color"] = tuple(led.color)
                    kwargs["brightness"] = 100
                elif led.mode == Led.Mode.OFF:
                    pass
                elif led.mode == Led.Mode.CYCLE:
                    kwargs["effect_duration"] = led.period
                    kwargs["brightness"] = led.intensity
                elif led.mode == Led.Mode.BREATHING:
                    kwargs["color"] = tuple(led.color)
                    kwargs["brightness"] = led.intensity
                    kwargs["effect_duration"] = led.period
                else:
                    # should never happen anyway, see to_ratbag_mode
                    pass

                ratbag.Led.create(profile=p, index=led_idx, **kwargs)

            for btn_idx, button in enumerate(profile.buttons):
                actiontypes = (
                    ratbag.Action.Type.NONE,
                    ratbag.Action.Type.BUTTON,
                    ratbag.Action.Type.SPECIAL,
                    ratbag.Action.Type.MACRO,
                )
                b = ratbag.Button.create(
                    profile=p, index=btn_idx, types=actiontypes, action=None
                )
                if button.type == Button.Type.DISABLED:
                    action = ratbag.ActionNone.create()
                elif button.type == Button.Type.HID:
                    if button.hidtype == Button.HidType.MOUSE:
                        action = ratbag.ActionButton.create(button=button.button)
                    else:
                        # FIXME: macro for keybaoard, special for consumer
                        # control
                        action = ratbag.ActionNone.create()
                elif button.type == Button.Type.SPECIAL:
                    action = ratbag.ActionSpecial.create(special=button.ratbag_special)
                elif button.type == Button.Type.MACRO:
                    # FIXME: needs parsing
                    action = ratbag.ActionMacro.create()

                b.set_action(action)

        self.emit("device-added", ratbag_device)


################################################################################
#
# Below is the implementation of the HID++2.0 protocol
#
# We have a set of Query objects that the device calls, each sends a request
# to the device and waits for the reply. To simplify the implementation, the
# Query class implements most of the functionality, each individual query just
# needs to change the bitst out and parse the bits that came back.
#
# The instance then sets self.whatever for each whatever in the reply, so the
# caller looks like this:
#
#    query = QuerySomeThing(args).run(self).
#    if query.some_field != 3:
#        ...
#


@attr.s
class Query(object):
    """
    A query against the device, consisting of a request and a reply from the
    device.

    .. attribute: query

        The bytes sent to the device

    .. attribute: reply

        The bytes received from  the device

    :param device: The device to query

    """

    report_id: ReportID = attr.ib(
        validator=attr.validators.in_(list(ReportID)),
    )
    page: int = attr.ib()
    command: int = attr.ib()
    query_spec: List[Spec] = attr.ib()
    reply_spec: List[Spec] = attr.ib()

    @page.validator
    def _check_page(self, attribute, value):
        if value < 0 or value > 0xFF:
            raise ValueError("page must be within 0..0xff")

    @command.validator
    def _check_command(self, attribute, value):
        if value < 0 or value > 0xFF:
            raise ValueError("command must be within 0..0xff")

    def run(self, device: Hidpp20Device):
        self.command |= 0x8
        self._device_index = device.index

        query_len = self.report_id.size

        # header is always the same
        spec = [
            Spec("B", "report_id"),
            Spec("B", "_device_index"),
            Spec("B", "page"),
            Spec("B", "command"),
        ] + self.query_spec
        query = Parser.from_object(self, spec, pad_to=query_len)
        self.command &= ~0x8

        self._repeat = True
        while self._repeat:
            self._repeat = False
            device.send(bytes(query))
            reply = device.recv_sync()

            if reply is not None and reply[2] == 0x8F:
                raise QueryError(device, reply)

            self.reply = self._autoparse(reply)
            self.parse_reply(self.reply)
        return self

    def _autoparse(self, bytes):
        if not self.reply_spec:
            return

        spec = [
            Spec("B", "report_id"),
            Spec("B", "_device_index"),
            Spec("B", "page"),
            Spec("B", "command"),
        ] + self.reply_spec

        # QueryFooBar should return a ResultFooBar class
        replyname = type(self).__name__.replace("Query", "Result")
        result = Parser.to_object(bytes, spec, result_class=replyname)
        return result.object

    def parse_reply(self, reply):
        """
        Override this in the subclass if :attr:`reply_format` autoparsing is
        insufficient. Parse the given bytes and set the required instance
        attributes. :attr:`reply` is set with the bytes from the reply.

        If the caller calls :meth:`schedule_repeat` during ``parse_reply``,
        same command is issued again once ``parse_reply`` completes and
        ``parse_reply`` is called with the new reply data.
        """
        pass


class QueryError(Exception):
    """
    An exception raised when a :class:`Query` failed with a HID++ error.

    .. attribute: device

        The device the error occured on

    .. attribute: bytes

        The raw bytes of the error message

    .. attribute: page

        The command page

    .. attribute: command

        The command id
    """

    def __init__(self, device, bytes):
        self.device = device
        self.bytes = bytes
        self.page = bytes[3]
        self.command = bytes[4]


# --------------------------------------------------------------------------------------
# 0x0000: Root
# --------------------------------------------------------------------------------------


class CmdRoot(enum.IntEnum):
    GET_FEATURE = 0x00
    GET_PROTOCOL_VERSION = 0x10


@attr.s
class QueryProtocolVersion(Query):
    @classmethod
    def instance(cls):
        return cls(
            report_id=ReportID.SHORT,
            page=FeatureName.ROOT,
            command=CmdRoot.GET_PROTOCOL_VERSION,
            query_spec=[],
            reply_spec=[Spec("B", "major"), Spec("B", "minor")],
        )


@attr.s
class QueryGetFeature(Query):
    """
    Query the device for the given feature by name, see :class:`FeatureName`.
    If successful, the reply ``feature`` attribute (:class:`Feature`) which
    contains the index and feature type. The index is to be used to query
    more information about this feature, see :class:`QueryFeatureSetCount`
    and :class:`QueryFeatureSetId`.
    """

    feature_name: FeatureName = attr.ib()

    @classmethod
    def instance(cls, feature_name: FeatureName):
        return cls(
            report_id=ReportID.SHORT,
            feature_name=feature_name,
            page=FeatureName.ROOT,
            command=CmdRoot.GET_FEATURE,
            query_spec=[
                Spec("H", "feature_name"),
            ],
            reply_spec=[
                Spec("B", "feature_index"),
                Spec("B", "feature_type"),
                Spec("B", "feature_version"),
            ],
        )

    def parse_reply(self, reply):
        if reply.feature_index != 0:
            reply.feature = Feature(
                name=self.feature_name,
                index=reply.feature_index,
                type=reply.feature_type,
                version=reply.feature_version,
            )

    def __str__(self):
        return (
            f"{type(self).__name__}: {self.feature_name.name} (0x{self.feature_name:04x}) at index {self.reply.feature_index}, "
            f"type {self.reply.feature_type} "
            f"version {self.reply.feature_version}"
        )


# --------------------------------------------------------------------------------------
# 0x0001: Feature Set
# --------------------------------------------------------------------------------------


class CmdFeatureSet(enum.IntEnum):
    GET_COUNT = 0x00
    GET_FEATURE_ID = 0x10


@attr.s
class QueryFeatureSetCount(Query):
    feature: Feature = attr.ib()

    @classmethod
    def instance(cls, feature: Feature):
        return cls(
            report_id=ReportID.SHORT,
            page=feature.index,
            command=CmdFeatureSet.GET_COUNT,
            feature=feature,
            query_spec=[],
            reply_spec=[Spec("B", "count")],
        )

    def parse_reply(self, reply):
        # feature set count does not include the root feature as documented
        # here:
        # https://6xq.net/git/lars/lshidpp.git/plain/doc/logitech_hidpp_2.0_specification_draft_2012-06-04.pdf
        if self.feature == FeatureName.FEATURE_SET:
            reply.count += 1

    def __str__(self):
        return f"{type(self).__name__}: {self.feature.name} (0x{self.feature.name:04x}) count {self.reply.count}"


@attr.s
class QueryFeatureSetId(Query):
    feature_index: int = attr.ib()

    @classmethod
    def instance(cls, feature, index):
        return cls(
            report_id=ReportID.SHORT,
            page=feature.index,
            command=CmdFeatureSet.GET_FEATURE_ID,
            feature_index=index,
            query_spec=[Spec("B", "feature_index")],
            reply_spec=[
                Spec("H", "feature_id"),
                Spec("B", "feature_type"),
            ],
        )


# --------------------------------------------------------------------------------------
# 0x0003: Device Info
# --------------------------------------------------------------------------------------


class CmdDeviceInfo(enum.IntEnum):
    GET_DEVICE_INFO = 0x00
    GET_FW_INFO = 0x10


@attr.s
class QueryDeviceInfoGetDeviceInfo(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.DEVICE_INFO].index,
            command=CmdDeviceInfo.GET_DEVICE_INFO,
            query_spec=[],
            reply_spec=[
                Spec("B", "count"),
                # don't care about the rest here
            ],
        )

    def __str__(self):
        return f"{type(self).__name__}: count: {self.reply.count}"


@attr.s
class QueryDeviceInfoGetFwInfo(Query):
    class Type(enum.IntEnum):
        MAIN = 0x00
        DFU = 0x01
        HW = 0x02

    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.DEVICE_INFO].index,
            command=CmdDeviceInfo.GET_FW_INFO,
            index=index,
            query_spec=[Spec("B", "index")],
            reply_spec=[
                Spec(
                    "B",
                    "type",
                    convert_from_data=lambda x: QueryDeviceInfoGetFwInfo.Type(x),
                ),
                Spec(
                    "BBB",
                    "prefix",
                    convert_from_data=lambda x: bytes(x).decode("utf-8"),
                ),
                Spec("B", "number", convert_from_data=lambda x: f"{x:02x}"),
                Spec("B", "revision", convert_from_data=lambda x: f"{x:02x}"),
                Spec("H", "build", convert_from_data=lambda x: f"{x:04x}"),
                # don't care about the rest
            ],
        )

    def parse_reply(self, reply):
        reply.firmware_version = (
            f"{reply.prefix}{reply.number}.{reply.revision}.{reply.build}"
        )

    def __str__(self):
        return (
            f"{type(self).__name__}: type: {self.reply.type} "
            f"version: {self.reply.firmware_version}"
        )


# --------------------------------------------------------------------------------------
# 0x8100: Onboard Profiles
# --------------------------------------------------------------------------------------


class CmdOnboardProfiles(enum.IntEnum):
    GET_PROFILES_DESC = 0x00
    SET_ONBOARD_MODE = 0x10
    GET_ONBOARD_MODE = 0x20
    SET_CURRENT_PROFILE = 0x30
    GET_CURRENT_PROFILE = 0x40
    MEMORY_READ = 0x50
    MEMORY_ADDR_WRITE = 0x60
    MEMORY_WRITE = 0x70
    MEMORY_WRITE_END = 0x80
    GET_CURRENT_DPI_INDEX = 0xB0
    SET_CURRENT_DPI_INDEX = 0xC0


@attr.s
class QueryOnboardProfilesDesc(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ONBOARD_PROFILES].index,
            command=CmdOnboardProfiles.GET_PROFILES_DESC,
            query_spec=[],
            reply_spec=[
                Spec("B", "memory_model_id"),
                Spec("B", "profile_format_id"),
                Spec("B", "macro_format_id"),
                Spec("B", "profile_count"),
                Spec("B", "profile_count_oob"),
                Spec("B", "button_count"),
                Spec("B", "sector_count"),
                Spec("H", "sector_size"),
                Spec("B", "mechanical_layout"),
                Spec("B", "various_info"),
                Spec("ccccc", "_"),
            ],
        )

    def parse_reply(self, reply):
        reply.has_g_shift = (reply.mechanical_layout & 0x03) == 0x02
        reply.has_dpi_shift = ((reply.mechanical_layout & 0x0C) >> 2) == 0x02
        reply.is_corded = (reply.various_info & 0x07) in [1, 4]
        reply.is_wireless = (reply.various_info & 0x07) in [2, 4]

    def __str__(self):
        return (
            f"{type(self).__name__}: memmodel {self.reply.memory_model_id}, "
            f"profilefmt {self.reply.profile_format_id}, macrofmt {self.reply.macro_format_id}, "
            f"profilecount {self.reply.profile_count} oob {self.reply.profile_count_oob}, "
            f"buttons {self.reply.button_count}, "
            f"sectors {self.reply.sector_count}@{self.reply.sector_size} bytes, "
            f"mechlayout {self.reply.mechanical_layout}, various {self.reply.various_info}, "
            f"gshift {self.reply.has_g_shift} dpishift {self.reply.has_dpi_shift}, "
            f"corded {self.reply.is_corded} wireless {self.reply.is_wireless}"
        )


@attr.s
class QueryOnboardProfilesGetMode(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ONBOARD_PROFILES].index,
            command=CmdOnboardProfiles.GET_ONBOARD_MODE,
            query_spec=[],
            reply_spec=[Spec("B", "mode")],
        )


@attr.s
class QueryOnboardProfilesMemRead(Query):
    sector: int = attr.ib(default=0)
    offset: int = attr.ib(default=0)

    @sector.validator
    def _check_sector(self, attribute, value):
        if value < 0 or value > 0xFFFF:
            raise ValueError("sector must be within 0..0xffff")

    @offset.validator
    def _check_offset(self, attribute, value):
        if value < 0:
            raise ValueError("offset must be within 0..0xffff")

    @classmethod
    def instance(
        cls,
        feature_lut: Dict[FeatureName, Feature],
        sector: int,
        sector_size: int,
        offset: int,
    ):
        # The firmware replies with an ERR_INVALID_ARGUMENT if we try to
        # read past sector_size, so when we are left with less than 16
        # bytes to read we start reading from sector_size - 16
        #
        # 16 == ReportID.LONG.size minus 4 byte header
        if offset > sector_size - 16:
            raise ValueError(f"Invalid offset {offset} for sector size {sector_size}")
        return cls(
            report_id=ReportID.LONG,
            page=feature_lut[FeatureName.ONBOARD_PROFILES].index,
            command=CmdOnboardProfiles.MEMORY_READ,
            query_spec=[
                Spec("H", "sector"),
                Spec("H", "offset"),
            ],
            reply_spec=[Spec("B" * 16, "data")],
            sector=sector,
            offset=offset,
        )


@attr.s
class QueryOnboardProfilesMemReadSector:
    queries = attr.ib(default=attr.Factory(list))

    @classmethod
    def instance(
        cls, feature_lut: Dict[FeatureName, Feature], sector: int, sector_size: int
    ):
        # Note: this class is a helper around the need for sending multiple
        # queries to the device to get the full sector. Our instance() method
        # returns a wrapper class that contains all actual queries, when
        # calling run() those queries are executed and their data is combined
        # into a single object again.

        # 16 == ReportID.LONG.size minus 4 byte header
        offset_range = list(range(0, sector_size, 16))
        # The firmware replies with an ERR_INVALID_ARGUMENT if we try to
        # read past sector_size, so when we are left with less than 16
        # bytes to read we start reading from sector_size - 16
        offset_range[-1] = min(offset_range[-1], sector_size - 16)
        queries = [
            QueryOnboardProfilesMemRead.instance(
                feature_lut=feature_lut,
                sector=sector,
                sector_size=sector_size,
                offset=off,
            )
            for off in offset_range
        ]
        return QueryOnboardProfilesMemReadSector(
            queries=queries,
        )

    def run(self, device: Hidpp20Device):
        queries = map(
            lambda x: x.run(device), sorted(self.queries, key=lambda x: x.offset)  # type: ignore
        )
        data: List[int] = []
        for query in queries:
            # The special offset handling at the end
            skip_index = len(data) - query.offset
            data.extend(query.reply.data[skip_index:])

        @attr.s
        class SectorData:
            data: bytes = attr.ib(default=bytes())
            checksum: int = attr.ib(default=0)

        sector_data = SectorData()
        Parser.to_object(
            bytes(data),
            specs=[
                Spec(
                    "B" * (len(data) - 2), "data", convert_from_data=lambda x: bytes(x)
                ),
                Spec("H", "checksum"),
            ],
            obj=sector_data,
        )

        return sector_data


# --------------------------------------------------------------------------------------
# 0x2201: Adjustible DPI
# --------------------------------------------------------------------------------------


class CmdAdjustibleDpi(enum.IntEnum):
    GET_SENSOR_COUNT = 0x00
    GET_SENSOR_DPI_LIST = 0x10
    GET_SENSOR_DPI = 0x20
    SET_SENSOR_DPI = 0x30


@attr.s
class QueryAdjustibleDpiGetCount(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ADJUSTIBLE_DPI].index,
            command=CmdAdjustibleDpi.GET_SENSOR_COUNT,
            query_spec=[],
            reply_spec=[Spec("B", "sensor_count")],
        )

    def __str__(self):
        return f"{type(self).__name__}: sensor-count {self.reply.sensor_count}"


@attr.s
class QueryAdjustibleDpiGetDpiList(Query):
    sensor_index: int = attr.ib(default=0)

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], sensor_index):
        # FIXME: check
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ADJUSTIBLE_DPI].index,
            command=CmdAdjustibleDpi.GET_SENSOR_DPI_LIST,
            query_spec=[Spec("B", "sensor_index")],
            reply_spec=[
                Spec("B", "sensor_index"),
                Spec("H" * 7, "values", endian="BE"),
            ],
        )

    def parse_reply(self, reply):
        # FIXME: libratbag has a G602 quirk here for the handling
        try:
            reply.dpi_steps = [v - 0xE000 for v in reply.values if v > 0xE000][0]
        except IndexError:
            reply.dpi_steps = 0
        reply.dpis = sorted([v for v in reply.values if 0 < v < 0xE000])

    def __str__(self):
        return f"{type(self).__name__}: sensor-index {self.reply.sensor_index} dpis {self.reply.dpis} steps {self.reply.dpi_steps}"


@attr.s
class QueryAdjustibleDpiGetDpi(Query):
    sensor_index: int = attr.ib(default=0)

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], sensor_index):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ADJUSTIBLE_DPI].index,
            command=CmdAdjustibleDpi.GET_SENSOR_DPI,
            query_spec=[Spec("B", "sensor_index")],
            reply_spec=[
                Spec("B", "sensor_index"),
                Spec("H", "dpi", endian="BE"),
                Spec("H", "default_dpi", endian="BE"),
            ],
        )

    def __str__(self):
        return f"{type(self).__name__}: sensor-index {self.reply.sensor_index} dpi {self.reply.dpi} default_dpi {self.reply.default_dpi}"


# --------------------------------------------------------------------------------------
# 0x8060: Adjustible Report Rate
# --------------------------------------------------------------------------------------


class CmdAdjustibleReporRate(enum.IntEnum):
    GET_REPORT_RATE_LIST = 0x00
    GET_REPORT_RATE = 0x10
    SET_REPORT_RATE = 0x20


@attr.s
class QueryAdjustibleReportRateGetList(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.ADJUSTIBLE_REPORT_RATE].index,
            command=CmdAdjustibleReporRate.GET_REPORT_RATE_LIST,
            query_spec=[],
            reply_spec=[
                Spec("B", "flags"),
            ],
        )

    def parse_reply(self, reply):
        # we only care about 'standard' rates
        rates = []
        if self.reply.flags & 0x80:
            rates.append(125)
        if self.reply.flags & 0x8:
            rates.append(250)
        if self.reply.flags & 0x2:
            rates.append(500)
        if self.reply.flags & 0x1:
            rates.append(1000)
        self.reply.report_rates = rates

    def __str__(self):
        return f"{type(self).__name__}: report-rates {self.reply.report_rates}"


# --------------------------------------------------------------------------------------
# 0x1b04: Special keys and mouse buttons
# --------------------------------------------------------------------------------------


class CmdSpecialKeyButtons(enum.IntEnum):
    GET_COUNT = 0x00
    GET_INFO = 0x10
    GET_REPORTING = 0x20
    SET_REPORTING = 0x30


@attr.s
class QuerySpecialKeyButtonsGetCount(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.SPECIAL_KEYS_BUTTONS].index,
            command=CmdSpecialKeyButtons.GET_COUNT,
            query_spec=[],
            reply_spec=[
                Spec("B", "count"),
            ],
        )


@attr.s
class QuerySpecialKeyButtonsGetInfo(Query):
    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.SPECIAL_KEYS_BUTTONS].index,
            command=CmdSpecialKeyButtons.GET_INFO,
            index=index,
            query_spec=[
                Spec("B", "index"),
            ],
            reply_spec=[
                Spec("H", "control_id"),
                Spec("H", "task_id"),
                Spec("B", "flags"),
                Spec("B", "position"),
                Spec("B", "group"),
                Spec("B", "group_mask"),
                Spec("raw_xy", "group_mask", convert_from_data=lambda x: x & 0x01),
            ],
        )

    def parse_reply(self, reply):
        reply.logical_mapping = LogicalMapping(self.reply.control_id)
        reply.physical_mapping = LogicalMapping(self.reply.task_id)


@attr.s
class QuerySpecialKeyButtonsGetReporting(Query):
    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.SPECIAL_KEYS_BUTTONS].index,
            command=CmdSpecialKeyButtons.GET_REPORTING,
            index=index,
            query_spec=[
                Spec("B", "index"),
            ],
            reply_spec=[
                Spec("BB", "_"),
                Spec("H", "remapped"),
                Spec("B", "flags"),
            ],
        )

    def parse_reply(self, reply):
        reply.raw_xy = not not (self.flags & 0x10)
        reply.persist = not not (self.flags & 0x04)
        reply.divert = not not (self.flags & 0x01)
        reply.logical_mapping = LogicalMapping(reply.remapped)


# --------------------------------------------------------------------------------------
# 0x1000: Battery level status
# --------------------------------------------------------------------------------------


class CmdBatteryLevel(enum.IntEnum):
    GET_LEVEL_STATUS = 0x00
    GET_BATTERY_CAPABILITY = 0x10


@attr.s
class QueryBatteryLevelGetLevel(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.BATTERY_LEVEL_STATUS].index,
            command=CmdBatteryLevel.GET_LEVEL_STATUS,
            query_spec=[],
            reply_spec=[
                Spec("B", "level"),
                Spec("B", "next_level"),
            ],
        )


# --------------------------------------------------------------------------------------
# 0x1001: Battery voltage
# --------------------------------------------------------------------------------------


class CmdBatteryVoltage(enum.IntEnum):
    GET_BATTERY_VOLTAGE = 0x00
    GET_SHOW_BATTERY_STATUS = 0x10


@attr.s
class QueryBatteryVoltageGetVoltage(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.BATTERY_VOLTAGE].index,
            command=CmdBatteryVoltage.GET_BATTERY_VOLTAGE,
            query_spec=[],
            reply_spec=[
                Spec("H", "voltage"),
            ],
        )


# --------------------------------------------------------------------------------------
# 0x1300: Non-RGB LED support
# --------------------------------------------------------------------------------------


class CmdLedSwControl(enum.IntEnum):
    GET_LED_COUNT = 0x00
    GET_LED_INFO = 0x10
    GET_SW_CTRL = 0x20
    SET_SW_CTRL = 0x30
    GET_LED_STATE = 0x40
    SET_LED_STATE = 0x50
    GET_NV_CONFIG = 0x60


@attr.s
class QueryLedSwControlGetLedCount(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.LED_SW_CONTROL].index,
            command=CmdLedSwControl.GET_LED_COUNT,
            query_spec=[],
            reply_spec=[
                Spec("B", "count"),
            ],
        )


@attr.s
class QueryLedSwControlGetLedInfo(Query):
    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.LED_SW_CONTROL].index,
            command=CmdLedSwControl.GET_LED_INFO,
            index=index,
            query_spec=[
                Spec("B", "index"),
            ],
            reply_spec=[
                Spec("B", "index"),
                Spec("B", "type"),
                Spec("B", "physical_count"),
                Spec("H", "caps"),
                Spec("B", "nvconfig_caps"),
            ],
        )


@attr.s
class QueryLedSwControlGetSwCtrl(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.LED_SW_CONTROL].index,
            command=CmdLedSwControl.GET_SW_CTRL,
            query_spec=[],
            reply_spec=[
                Spec("B", "is_sw_control", convert_from_data=lambda x: bool(x)),
            ],
        )


# FIXME: need some sort of mapping to Led.Mode
class SwLedMode(enum.IntEnum):
    OFF = 0x1
    ON = 0x2
    BLINK = 0x4
    TRAVEL = 0x8
    RAMP_UP = 0x10
    RAMP_DOWN = 0x20
    HEARTBEAT = 0x40
    BREATHING = 0x80


@attr.s
class QueryLedSwControlGetLedState(Query):
    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.LED_SW_CONTROL].index,
            command=CmdLedSwControl.GET_LED_STATE,
            index=index,
            query_spec=[
                Spec("B", "index"),
            ],
            reply_spec=[Spec("B", "index"), Spec("H", "mode"), Spec("BBBBBB", "data")],
        )

    def parse_reply(self, reply):
        reply.mode = SwLedMode(self.mode)
        specs = []
        if reply.mode == SwLedMode.ON:
            specs = [
                Spec(
                    "H", "info"
                ),  # FIXME: "index" in libratbag but pretty sure this is wrong
            ]
        elif reply.mode == SwLedMode.BLINK:
            specs = [
                Spec(
                    "H", "info"
                ),  # FIXME: "index" in libratbag but pretty sure this is wrong
                Spec("H", "on_time"),
                Spec("H", "off_time"),
            ]
        elif reply.mode == SwLedMode.BREATHING:
            specs = [
                Spec("H", "brightness"),
                Spec("H", "period"),
                Spec("H", "timeout"),
            ]
        elif reply.mode == SwLedMode.TRAVEL:
            specs = [
                Spec("H", "_"),
                Spec("H", "delay"),
            ]

        if specs:
            Parser.to_object(bytes(self.data), specs, obj=reply)


# --------------------------------------------------------------------------------------
# 0x1b00: KBD reprogrammable keys and mouse buttons
# --------------------------------------------------------------------------------------


class CmdReprogrammableKeys(enum.IntEnum):
    GET_COUNT = 0x00
    GET_CTRL_ID_INFO = 0x10


@attr.s
class QueryReprogrammableKeysGetCount(Query):
    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature]):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.KBD_REPROGRAMMABLE_KEYS].index,
            command=CmdReprogrammableKeys.GET_COUNT,
            query_spec=[],
            reply_spec=[
                Spec("B", "count"),
            ],
        )


@attr.s
class QueryReprogrammableKeysGetInfo(Query):
    index: int = attr.ib()

    @classmethod
    def instance(cls, feature_lut: Dict[FeatureName, Feature], index: int):
        return cls(
            report_id=ReportID.SHORT,
            page=feature_lut[FeatureName.KBD_REPROGRAMMABLE_KEYS].index,
            command=CmdReprogrammableKeys.GET_CTRL_ID_INFO,
            index=index,
            query_spec=[
                Spec("b", "index"),
            ],
            reply_spec=[
                Spec("H", "control_id"),
                Spec("H", "task_id"),
                Spec("B", "flags"),
            ],
        )

    def parse_reply(self, reply):
        reply.logical_mapping = LogicalMapping(reply.control_id)
        reply.physical_mapping = LogicalMapping(reply.task_id)
