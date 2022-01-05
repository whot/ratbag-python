#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

from typing import Any, Dict, List, Optional, Tuple

import attr
import enum
import logging
import pathlib
import struct

import gi
from gi.repository import GObject

import ratbag
import ratbag.hid
from ratbag.util import as_hex
from ratbag.parser import Parser, Spec

logger = logging.getLogger(__name__)


RECEIVER_IDX = 0xFF
REPORT_ID_SHORT = 0x10
REPORT_ID_LONG = 0x11


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
    class MemoryType(enum.Enum):
        G402 = 0x01

    class ProfileType(enum.Enum):
        G402 = 0x01
        G303 = 0x02
        G900 = 0x03
        G915 = 0x04

    class MacroType(enum.Enum):
        G402 = 0x01

    class Mode(enum.Enum):
        NO_CHANGE = 0x00
        ONBOARD = 0x01
        HOST = 0x02

    class Sector(enum.Enum):
        USER_PROFILES_G402 = 0x0000
        ROM_PROFILES_G402 = 0x0100

        END_OF_PROFILE_DIRECTORY = 0xFFFF
        ENABLED_INDEX = 2


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


@attr.s
class Color:
    red: int = attr.ib()
    green: int = attr.ib()
    blue: int = attr.ib()

    def __str__(self):
        return f"rgb({self.red},{self.green},{self.blue})"


@attr.s
class Profile(object):
    address: int = attr.ib()
    """
    The memory address where this profile resides
    """
    enabled: bool = attr.ib(default=False)
    dpi_list: List[int] = attr.ib(default=attr.Factory(list))
    report_rates: List[int] = attr.ib(default=attr.Factory(list))
    data: bytes = attr.ib(default=bytes())
    """
    The initial data this profile was created from. This data is constant
    for the life of the profile and can be used to restore the profile to
    its original state.
    """

    @property
    def report_rate(self) -> int:
        return 1000 // max(1, self._report_rate)  # type: ignore

    @property
    def name(self) -> str:
        try:
            self._name.index(b"\xff")  # type: ignore
        except ValueError:
            # we're not using the default name, so let's decode this
            return bytes(self._name).decode("utf-8").rstrip("\x00")  # type: ignore

        return f"Profile {self.address}"

    @classmethod
    def from_data(cls, address: int, enabled: bool, data: bytes):
        profile = cls(address, enabled, data=data)
        spec = [
            Spec("B", "_report_rate"),
            Spec("B", "default_dpi"),
            Spec("B", "switched_dpi"),
            Spec("HHHHH", "dpi", endian="le"),
            Spec("BBB", "colors"),
            Spec("B", "power_mode"),
            Spec("B", "angle_snapping"),
            Spec("B", "_", repeat=10),  # reserved
            Spec("H", "powersafe_timeout", endian="le"),
            Spec("H", "poweroff_timeout", endian="le"),
            Spec("II", "_button_bindings", repeat=16),  # FIXME: check this again
            Spec("H", "_name", repeat=16, endian="le"),
            # next are 11 bytes per leds, times 2 leds, times 2
            # next are 2 unused bytes
            # last 2 bytes are the 16-bit crc
        ]

        Parser.to_object(data, spec, profile)
        return profile

    def __str__(self):
        return (
            f"{self.name}: {self.report_rate}Hz, "
            f"{self.default_dpi}/{self.switched_dpi}dpi "
            f"{[x for x in self.dpi]} "
            f"{self.colors} "
            f"timeouts:{self.powersafe_timeout}/{self.poweroff_timeout}"
        )


@attr.s
class ProfileAddress(object):
    address: int = attr.ib()
    enabled: bool = attr.ib()

    @classmethod
    def from_sector(cls, data: bytes, index: int):
        addr_offset = 4 * index
        spec = [Spec("H", "addr", endian="BE")]
        result = Parser.to_object(data[addr_offset:], spec).object
        if result.addr == OnboardProfile.Sector.END_OF_PROFILE_DIRECTORY.value:
            return None

        # profile address sanity check
        expected_addr = OnboardProfile.Sector.USER_PROFILES_G402.value | (index + 1)
        if result.addr != expected_addr:
            logger.error(
                f"profile {index}: expected address 0x{expected_addr:04x}, have 0x{result.address:04x}"
            )

        enabled = data[addr_offset + OnboardProfile.Sector.ENABLED_INDEX.value] != 0

        return cls(result.addr, enabled)


class Hidpp20Device(GObject.Object):
    """
    A HID++2.0 device

    .. attribute:: index

        The device index for the Logitech receiver

    .. attribute:: supported_requests

        A list of supported requests (``REPORT_ID_SHORT`, ``REPORT_ID_LONG``)

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

    def __init__(self, hidraw_device: ratbag.drivers.Rodent, device_index: int):
        GObject.Object.__init__(self)
        self.index = device_index
        self.hidraw_device = hidraw_device

    @property
    def name(self) -> str:
        return self.hidraw_device.name

    @property
    def path(self) -> pathlib.Path:
        return self.hidraw_device.path

    def start(self) -> None:
        supported = [
            id
            for id in self.hidraw_device.report_ids["input"]
            if id in (REPORT_ID_SHORT, REPORT_ID_LONG)
        ]

        required = (REPORT_ID_SHORT, REPORT_ID_LONG)
        if not (set(supported) & set(required)):
            raise ratbag.SomethingIsMissingError(
                self.name, self.path, "HID++ short/long reports"
            )

        self.supported_requests = supported

        self._init_protocol_version()
        self._init_features()
        self._init_profiles()

    def _init_protocol_version(self) -> None:
        # Get the protocol version and our feature set
        version = QueryProtocolVersion.instance(self).run()
        logger.debug(f"protocol version {version.reply.major}.{version.reply.minor}")
        if version.reply.major < 2:
            raise ratbag.SomethingIsMissingError(
                self.name, self.path, "Protocol version 2.x"
            )
        self.protocol_version = (version.major, version.minor)

    def _init_features(self) -> None:
        feature_set = QueryRootGetFeature.instance(
            self, FeatureName.FEATURE_SET
        ).run()  # PAGE_FEATURE_SET
        logger.debug(feature_set)
        feature_count = QueryFeatureSetCount.instance(self, feature_set).run()
        logger.debug(feature_count)

        features = []
        for idx in range(feature_count.reply.count):
            query = QueryFeatureSetId.instance(self, feature_set, idx).run()
            logger.debug(query)

            fid = query.reply.feature_id
            ftype = query.reply.feature_type

            try:
                name = FeatureName(fid)
                features.append(Feature(name, idx, ftype))
                logger.debug(f"device has feature {name.name}")
            except ValueError:
                # We're intentionally skipping unknown features here, if we can't
                # name them we don't know how to handle them
                pass

        self.features = dict(zip([f.name for f in features], features))

    def _init_profiles(self) -> None:
        if FeatureName.ONBOARD_PROFILES not in self.features:
            raise ratbag.SomethingIsMissingError(
                self.name, self.path, "HID++2.0 feature ONBOARD_PROFILES"
            )

        desc_query = QueryOnboardProfilesDesc.instance(self).run()
        logger.debug(desc_query)
        if desc_query.reply.memory_model_id != OnboardProfile.MemoryType.G402.value:
            raise ratbag.SomethingIsMissingError(
                self.name,
                self.path,
                f"Unsupported memory model {desc_query.memory_model_id}",
            )
        if desc_query.reply.macro_format_id != OnboardProfile.MacroType.G402.value:
            raise ratbag.SomethingIsMissingError(
                self.name,
                self.path,
                f"Unsupported macro format {desc_query.macro_format_id}",
            )
        try:
            OnboardProfile.ProfileType(desc_query.reply.profile_format_id)
        except ValueError:
            raise ratbag.SomethingIsMissingError(
                self.name,
                self.path,
                f"Unsupported profile format {desc_query.profile_format_id}",
            )

        sector_size = desc_query.reply.sector_size

        mode_query = QueryOnboardProfilesGetMode.instance(self).run()
        logger.debug(mode_query)
        if mode_query.reply.mode != OnboardProfile.Mode.ONBOARD.value:
            raise ratbag.SomethingIsMissingError(
                self.name,
                self.path,
                f"Device not in Onboard mode ({mode_query.reply.mode})",
            )
            # FIXME: set the device to onboard mode here instead of throwing
            # an exception

        mem_query = QueryOnboardProfilesMemReadSector.instance(
            self,
            OnboardProfile.Sector.USER_PROFILES_G402.value,
            sector_size=sector_size,
        ).run()
        logger.debug(mem_query)
        self.profiles = []

        if mem_query.checksum == crc(mem_query.data):
            for idx in range(desc_query.reply.profile_count):
                profile_address = ProfileAddress.from_sector(mem_query.data, idx)
                if not profile_address:
                    continue

                profile_query = QueryOnboardProfilesMemReadSector.instance(
                    self, profile_address.address, sector_size=sector_size
                ).run()
                logger.debug(profile_query)
                if profile_query.checksum != crc(profile_query.data):
                    # FIXME: libratbag reads the ROM instead in this case
                    logger.error(f"CRC validation failed for profile {idx}")
                    continue

                if FeatureName.ADJUSTIBLE_DPI in self.features:
                    scount_query = QueryAdjustibleDpiGetCount.instance(self).run()
                    # FIXME: there's a G602 quirk for the two queries in
                    # libratbag
                    for idx in range(scount_query.reply.sensor_count):
                        dpi_list_query = QueryAdjustibleDpiGetDpiList.instance(
                            self, idx
                        ).run()
                        logger.debug(dpi_list_query)
                        if dpi_list_query.reply.dpi_steps:
                            steps = dpi_list_query.reply.dpi_steps
                            dpi_min = min(dpi_list_query.reply.dpis)
                            dpi_max = max(dpi_list_query.reply.dpis)
                            dpi_list = list(range(dpi_min, dpi_max + 1, steps))
                        else:
                            dpi_list = dpi_list_query.reply.dpis

                        dpi_query = QueryAdjustibleDpiGetDpi.instance(self, idx).run()
                        logger.debug(dpi_query)
                else:
                    dpi_list = []

                # FIXME: this should only be run once per device, no need to
                # run this per-profile
                if FeatureName.ADJUSTIBLE_REPORT_RATE in self.features:
                    rates_query = QueryAdjustibleReportRateGetList.instance(self).run()
                    report_rates = rates_query.reply.report_rates
                else:
                    report_rates = []

                profile = Profile.from_data(
                    address=profile_address.address,
                    enabled=profile_address.enabled,
                    data=profile_query.data,
                )
                profile.dpi_list = dpi_list
                profile.report_rates = report_rates
                logger.debug(profile)
                self.profiles.append(profile)
        else:
            logger.error("CRC validation failed for sector")

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
        self, ratbag_device: ratbag.Device, callback: ratbag.CommitCallback, cookie: str
    ):
        raise NotImplementedError


class Hidpp20Driver(ratbag.drivers.Driver):
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

    def __init__(self):
        super().__init__()

    def probe(self, device, info, config):
        for key in ("Buttons", "DeviceIndex", "Leds", "ReportRate"):
            try:
                val = config[key]
                config[key.lower()] = val
            except KeyError:
                pass

        quirk = config.get("Quirk", None)
        if quirk is not None:
            try:
                quirk = [x for x in Hidpp20Driver.Quirk if x.value == quirk][0]
            except IndexError:
                raise ratbag.ConfigError(f"Invalid quirk value '{quirk}'")

        # Usually we default to the receiver IDX and let the kernel sort it
        # out, but some devices need to have the index hardcoded in the data
        # files
        index = config.get("deviceindex", RECEIVER_IDX)
        hidraw_device = ratbag.drivers.Rodent.from_device(device)
        device = Hidpp20Device(hidraw_device, index)

        for rec in self.recorders:
            hidraw_device.connect_to_recorder(rec)
            rec.init(
                {
                    "name": device.name,
                    "driver": "hidpp20",
                    "path": device.path,
                    "syspath": info.path,
                    "vid": info.vid,
                    "pid": info.pid,
                    "report_descriptor": hidraw_device.report_descriptor,
                }
            )

        ratbag_device = ratbag.Device(self, device.path, device.name)
        ratbag_device.connect("commit", device.cb_commit)
        device.start()
        # Device probe/start was successful if no exception occurs. Now fill in the
        # ratbag device.
        for idx, profile in enumerate(device.profiles):
            p = ratbag.Profile(
                ratbag_device,
                idx,
                name=profile.name,
                report_rate=profile.report_rate,
                report_rates=profile.report_rates,
            )
            for dpi_idx, dpi in enumerate(profile.dpi):
                ratbag.Resolution(p, dpi_idx, (dpi, dpi), dpi_list=profile.dpi_list)
        self.emit("device-added", ratbag_device)


def load_driver(driver_name: str) -> ratbag.drivers.Driver:
    """
    :meta private:
    """
    assert driver_name == "hidpp20"
    return Hidpp20Driver()


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
#    query = QuerySomeThing(device).run().
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

    LONG_MESSAGE_LENGTH = 20
    SHORT_MESSAGE_LENGTH = 7

    device: Hidpp20Device = attr.ib()
    report_id: int = attr.ib(
        default=REPORT_ID_SHORT,
        validator=attr.validators.in_([REPORT_ID_SHORT, REPORT_ID_LONG]),
    )
    page: int = attr.ib(default=0x00)
    command: int = attr.ib(default=0x00)
    query_spec: List[Spec] = attr.ib(default=attr.Factory(list))
    reply_spec: List[Spec] = attr.ib(default=attr.Factory(list))

    @page.validator
    def _check_page(self, attribute, value):
        if value < 0 or value > 0xFF:
            raise ValueError("page must be within 0..0xff")

    @command.validator
    def _check_command(self, attribute, value):
        if value < 0 or value > 0xFF:
            raise ValueError("command must be within 0..0xff")

    def run(self):
        self.command |= 0x8
        self._device_index = self.device.index

        query_len = {
            REPORT_ID_LONG: Query.LONG_MESSAGE_LENGTH,
            REPORT_ID_SHORT: Query.SHORT_MESSAGE_LENGTH,
        }[self.report_id]

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
            self.device.send(bytes(query))
            reply = self.device.recv_sync()

            if reply[2] == 0x8F:
                raise QueryError(self.device, self.bytes)

            self.reply = self._autoparse(reply)
            self.parse_reply()
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

        result = Parser.to_object(bytes, spec)
        return result.object

    def parse_reply(self):
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


@attr.s
class QueryProtocolVersion(Query):
    major: int = attr.ib(default=0)
    minor: int = attr.ib(default=0)

    @classmethod
    def instance(cls, device):
        return cls(
            device=device,
            page=FeatureName.ROOT.value,
            command=0x10,
            # no query spec
            reply_spec=[Spec("B", "major"), Spec("B", "minor")],
        )


@attr.s
class QueryRootGetFeature(Query):
    feature: FeatureName = attr.ib(default=FeatureName.ROOT)

    @classmethod
    def instance(cls, device, feature):
        return cls(
            device=device,
            feature=feature,
            page=FeatureName.ROOT.value,
            command=0x00,  # GET_FEATURE
            query_spec=[
                Spec("H", "feature", convert_to_data=lambda arg: int(arg.value)),
            ],
            reply_spec=[
                Spec("B", "feature_index"),
                Spec("B", "feature_type"),
                Spec("B", "feature_version"),
            ],
        )

    def __str__(self):
        return (
            f"{type(self).__name__}: {self.feature.name} (0x{self.feature.value:04x}) at index {self.feature_index}, "
            f"type {self.reply.feature_type} "
            f"version {self.reply.feature_version}"
        )


@attr.s
class QueryFeatureSetCount(Query):
    feature: FeatureName = attr.ib(default=FeatureName.ROOT)

    @classmethod
    def instance(cls, device, root_feature_query):
        return cls(
            device=device,
            page=root_feature_query.reply.feature_index,
            command=0x00,  # GET_COUNT
            feature=root_feature_query.feature,
            # no query spec
            reply_spec=[Spec("B", "count")],
        )

    def parse_reply(self):
        # feature set count does not include the root feature as documented
        # here:
        # https://6xq.net/git/lars/lshidpp.git/plain/doc/logitech_hidpp_2.0_specificati
        if self.feature == FeatureName.FEATURE_SET:
            self.reply.count += 1

    def __str__(self):
        return f"{type(self).__name__}: {self.feature.name} (0x{self.feature.value:04x}) count {self.reply.count}"


@attr.s
class QueryFeatureSetId(Query):
    feature_index: int = attr.ib(default=0x00)

    @classmethod
    def instance(cls, device, root_feature_query, index):
        return cls(
            device=device,
            page=root_feature_query.reply.feature_index,
            command=0x10,  # GET_FEATURE_ID
            feature_index=index,
            query_spec=[Spec("B", "feature_index")],
            reply_spec=[
                Spec("H", "feature_id"),
                Spec("B", "feature_type"),
            ],
        )


@attr.s
class QueryOnboardProfilesDesc(Query):
    @classmethod
    def instance(cls, device):
        return cls(
            device=device,
            page=device.features[FeatureName.ONBOARD_PROFILES].index,
            command=0x00,
            # no query spec
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

    def parse_reply(self):
        self.reply.has_g_shift = (self.reply.mechanical_layout & 0x03) == 0x02
        self.reply.has_dpi_shift = ((self.reply.mechanical_layout & 0x0C) >> 2) == 0x02
        self.reply.is_corded = (self.reply.various_info & 0x07) in [1, 4]
        self.reply.is_wireless = (self.reply.various_info & 0x07) in [2, 4]

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
    def instance(cls, device):
        return cls(
            device=device,
            page=device.features[FeatureName.ONBOARD_PROFILES].index,
            command=0x20,
            # no query spec
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
    def instance(cls, device, sector: int, sector_size: int, offset: int):
        # The firmware replies with an ERR_INVALID_ARGUMENT if we try to
        # read past sector_size, so when we are left with less than 16
        # bytes to read we start reading from sector_size - 16
        #
        # 16 == LONG_MESSAGE_LENGTH minus 4 byte header
        if offset > sector_size - 16:
            raise ValueError(f"Invalid offset {offset} for sector size {sector_size}")
        return cls(
            device=device,
            report_id=REPORT_ID_LONG,
            page=device.features[FeatureName.ONBOARD_PROFILES].index,
            command=0x50,
            query_spec=[
                Spec("H", "sector"),
                Spec("H", "offset"),
            ],
            reply_spec=[Spec("B", "data", repeat=16)],
            sector=sector,
            offset=offset,
        )


@attr.s
class QueryOnboardProfilesMemReadSector(Query):
    _queries = attr.ib(default=attr.Factory(list))

    @classmethod
    def instance(cls, device, sector: int, sector_size: int):
        # Note: this class is a helper around the need for sending multiple
        # queries to the device to get the full sector. Our instance() method
        # returns a wrapper class that contains all actual queries, when
        # calling run() those queries are executed and their data is combined
        # into a single object again.

        # 16 == LONG_MESSAGE_LENGTH minus 4 byte header
        offset_range = list(range(0, sector_size, 16))
        # The firmware replies with an ERR_INVALID_ARGUMENT if we try to
        # read past sector_size, so when we are left with less than 16
        # bytes to read we start reading from sector_size - 16
        offset_range[-1] = min(offset_range[-1], sector_size - 16)
        queries = [
            QueryOnboardProfilesMemRead.instance(
                device, sector=sector, sector_size=sector_size, offset=off
            )
            for off in offset_range
        ]
        return QueryOnboardProfilesMemReadSector(
            device=device,
            queries=queries,
        )

    def run(self):
        queries = map(lambda x: x.run(), sorted(self._queries, key=lambda x: x.offset))
        data = []
        for query in queries:
            # The special offset handling at the end
            skip_index = len(data) - query.offset
            data.extend(query.reply.data[skip_index:])

        obj = Parser.to_object(
            bytes(data),
            specs=[Spec("B" * (len(data) - 2), "data"), Spec("H", "checksum")],
        ).object

        obj.data = bytes(obj.data)
        return obj


@attr.s
class QueryAdjustibleDpiGetCount(Query):
    @classmethod
    def instance(cls, device):
        return cls(
            device=device,
            page=device.features[FeatureName.ADJUSTIBLE_DPI].index,
            command=0x00,  # GET_SENSOR_COUNT
            # no query spec
            reply_spec=[Spec("B", "sensor_count")],
        )

    def __str__(self):
        return f"{type(self).__name__}: sensor-count {self.reply.sensor_count}"


@attr.s
class QueryAdjustibleDpiGetDpiList(Query):
    sensor_index: int = attr.ib(default=0)

    @classmethod
    def instance(cls, device, sensor_index):
        # FIXME: check
        return cls(
            device=device,
            page=device.features[FeatureName.ADJUSTIBLE_DPI].index,
            command=0x10,  # GET_SENSOR_DPI_LIST
            query_spec=[Spec("B", "sensor_index")],
            reply_spec=[
                Spec("B", "sensor_index"),
                Spec("H" * 7, "values", endian="BE"),
            ],
        )

    def parse_reply(self):
        # FIXME: libratbag has a G602 quirk here for the handling
        try:
            self.reply.dpi_steps = [
                v - 0xE000 for v in self.reply.values if v > 0xE000
            ][0]
        except IndexError:
            self.reply.dpi_steps = 0
        self.reply.dpis = sorted([v for v in self.reply.values if 0 < v < 0xE000])

    def __str__(self):
        return f"{type(self).__name__}: sensor-index {self.reply.sensor_index} dpis {self.reply.dpis} steps {self.reply.dpi_steps}"


@attr.s
class QueryAdjustibleDpiGetDpi(Query):
    sensor_index: int = attr.ib(default=0)

    @classmethod
    def instance(cls, device, sensor_index):
        return cls(
            device=device,
            page=device.features[FeatureName.ADJUSTIBLE_DPI].index,
            command=0x20,  # GET_SENSOR_DPI
            query_spec=[Spec("B", "sensor_index")],
            reply_spec=[
                Spec("B", "sensor_index"),
                Spec("H", "dpi", endian="BE"),
                Spec("H", "default_dpi", endian="BE"),
            ],
        )

    def __str__(self):
        return f"{type(self).__name__}: sensor-index {self.reply.sensor_index} dpi {self.reply.dpi} default_dpi {self.reply.default_dpi}"


@attr.s
class QueryAdjustibleReportRateGetList(Query):
    @classmethod
    def instance(cls, device):
        return cls(
            device=device,
            page=device.features[FeatureName.ADJUSTIBLE_REPORT_RATE].index,
            command=0x00,  # LIST
            # no query spec
            reply_spec=[
                Spec("B", "flags"),
            ],
        )

    def parse_reply(self):
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
