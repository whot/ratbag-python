#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import attr
import enum
import logging

from typing import List, Tuple

import ratbag
import ratbag.hid
import ratbag.driver
import ratbag.util
from ratbag.parser import Spec, Parser

logger = logging.getLogger(__name__)


CONFIG_FLAGS_XY_RESOLUTION = 0x80
CONFIG_FLAGS_REPORT_RATE_MASK = 0x0F


class ReportID(enum.IntEnum):
    CONFIG = 0x4
    CMD = 0x5
    CONFIG_LONG = 0x6

    @property
    def size(self) -> int:
        return {
            ReportID.CONFIG: 520,
            ReportID.CONFIG_LONG: 520,
            ReportID.CMD: 6,
        }[self]


class Command(enum.IntEnum):
    FW_VERSION = 0x01
    GET_CONFIG = 0x11


@attr.s
class Config(object):
    """
    The configuration as read from the device and parsed into sanity. This
    object is intended to carry the state that we actually use before
    converting it back into whatever bytes the device needs.
    """

    dpi_disabled_slots: int = attr.ib()
    report_rate: int = attr.ib()
    independent_xy_resolution: bool = attr.ib()
    dpis: List[Tuple[int, int]] = attr.ib()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Config":
        """
        This function does the actual parsing, any conversion from bytes to
        something human-usable should be done here.
        """
        spec = [
            Spec("B", "report_id"),
            Spec("B", "cmd"),
            Spec("B", "?"),
            Spec("B", "config_write"),
            Spec("BBBBBB", "?"),
            Spec("B", "config"),  # Second nibble is the eport rate.
            # Two nibbles: active DPI (out of enabled ones) and DPI count.
            Spec("B", "dpi"),
            Spec("B", "dpi_disabled_slots"),  # bit mask
            Spec("B", "dpis", repeat=16),
            Spec("BBB", "dpi_color", repeat=8),
            Spec("B", "rgb_effect"),
            Spec("B", "glorious_mode"),
            Spec("B", "glorious_direction"),
            Spec("B", "single_mode"),
            Spec("BBB", "single_color"),
            Spec("B", "breathing7_mode"),
            Spec("B", "breathing7_colorcount"),
            Spec("BBB", "breathing7_color", repeat=7),
            Spec("B", "tail_mode"),
            Spec("B", "breathing_mode"),
            Spec("B", "constant_color_mode"),
            Spec("BBB", "constant_color_colors", repeat=6),
            Spec("B", "?", repeat=13),
            Spec("B", "rave_mode"),
            Spec("BBB", "rave_colors", repeat=2),
            Spec("B", "wave_mode"),
            Spec("B", "breathing1_mode"),
            Spec("BBB", "breathing1_color"),
            # 0x1 - 2 mm.
            # 0x2 - 3 mm.
            # 0xff - indicates that lift off distance is changed with a dedicated command. Not constant, so do **NOT** overwrite it.
            Spec("B", "lift_off_distance"),
            Spec("B", "?"),
            Spec("B", "_", greedy=True),
        ]

        result = Parser.to_object(data, spec)
        obj = result.object

        try:
            report_rate = {
                1: 125,
                2: 250,
                3: 500,
                4: 1000,
            }[obj.config & CONFIG_FLAGS_REPORT_RATE_MASK]
        except KeyError:
            logger.error(
                f"Invalid report rate {obj.config & CONFIG_FLAGS_REPORT_RATE_MASK}"
            )
            report_rate = 0

        xy_independent = bool(obj.config & CONFIG_FLAGS_XY_RESOLUTION)

        def raw2dpi(raw: int) -> int:
            # TODO: support different sensors. This is for PWM3360.
            return (raw + 1) * 100

        converted = [raw2dpi(r) for r in obj.dpis]
        if xy_independent:
            dpis = list(zip(converted[::2], converted[1::2]))
        else:
            dpis = [(x, x) for x in converted[:8]]

        # Now create the Config object with all the data we have converted
        # already
        return cls(
            dpi_disabled_slots=obj.dpi_disabled_slots,
            report_rate=report_rate,
            independent_xy_resolution=xy_independent,
            dpis=dpis,
        )


@attr.s
class Reply(object):
    """
    Object returned from :meth:`Query.run`. This object will have custom
    attributes depending on the query's reply spec.
    """

    pass


@attr.s
class Query:
    report_id: ReportID = attr.ib()
    reply_report_id: ReportID = attr.ib()
    cmd: Command = attr.ib()
    query_spec: List[Spec] = attr.ib()
    reply_spec: List[Spec] = attr.ib()

    def run(self, rodent: ratbag.driver.Rodent) -> Reply:
        qspec = [
            Spec("B", "report_id"),
            Spec("B", "cmd"),
        ] + self.query_spec

        query = Parser.from_object(self, qspec, pad_to=self.report_id.size)
        rodent.hid_set_feature(self.report_id, bytes(query))

        # Use the long config if available, otherwise the short config
        if (
            self.reply_report_id == ReportID.CONFIG
            and ReportID.CONFIG_LONG in rodent.report_ids["feature"]
        ):
            reply_report_id = ReportID.CONFIG_LONG
        else:
            reply_report_id = ReportID.CONFIG

        reply_data = rodent.hid_get_feature(self.reply_report_id)
        # Special handling for config queries:
        if self.reply_report_id in (ReportID.CONFIG, ReportID.CONFIG_LONG):
            if len(reply_data) != self.reply_report_id.size:
                raise ratbag.driver.ProtocolError.from_rodent(
                    rodent, f"Unexpected reply data size {len(reply_data)}"
                )
        # Real error check
        elif len(reply_data) != len(query):
            raise ratbag.driver.ProtocolError.from_rodent(
                rodent, f"Unexpected reply data size {len(reply_data)}"
            )

        if self.reply_report_id != reply_data[0]:
            raise ratbag.driver.ProtocolError.from_rodent(
                rodent,
                f"Got reply for a different command {reply_data[1]} instead of {self.reply_report_id}",
            )

        reply = Reply()
        Parser.to_object(reply_data, self.reply_spec, obj=reply)
        self.parse_reply(reply)
        return reply

    def parse_reply(self, reply):
        """
        Override this in the subclass if the autoparsing of the Spec fields
        is insufficient.
        """

        pass


@attr.s
class QueryFWVersion(Query):
    @classmethod
    def create(cls) -> "QueryFWVersion":
        return cls(
            report_id=ReportID.CMD,
            cmd=Command.FW_VERSION,
            reply_report_id=ReportID.CMD,
            query_spec=[],
            reply_spec=[
                Spec("B", "report_id"),
                Spec("B", "cmd"),
                Spec(
                    "BBBB",
                    "version",
                    convert_from_data=lambda s: bytes(s).decode("utf-8"),
                ),
            ],
        )


@attr.s
class QueryRawConfig(Query):
    @classmethod
    def create(cls) -> "QueryRawConfig":
        return cls(
            report_id=ReportID.CMD,
            cmd=Command.GET_CONFIG,
            reply_report_id=ReportID.CONFIG,
            query_spec=[],
            reply_spec=[
                Spec("B", "data", greedy=True, convert_from_data=lambda x: bytes(x))
            ],
        )


@attr.s
class SinowealthDevice:
    rodent: ratbag.driver.Rodent = attr.ib()
    ratbag_device: ratbag.Device = attr.ib()

    def start(self):
        if ReportID.CMD not in self.rodent.report_ids["feature"]:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.rodent, "CMD Report ID"
            )

        # query firmware version
        fwquery = QueryFWVersion.create()
        fw = fwquery.run(self.rodent)
        logger.info(f"firmware version: {fw.version}")

        # read the config from the device
        cquery = QueryRawConfig.create()
        creply = cquery.run(self.rodent)
        config = Config.from_bytes(creply.data)

        # now set up the ratbag device
        p = ratbag.Profile(
            device=self.ratbag_device,
            index=0,
            name="Unnamed profile",
            capabilities=[],
            report_rates=(125, 250, 500, 1000),
            report_rate=config.report_rate,
            active=True,  # we only have one profile
        )

        caps = [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]
        # TODO: set the DPI range according to found sensor.
        # NOTE: 10200 is the biggest commonly supported resolution, it's used by PWM3327.
        dpi_list = tuple(range(100, 10200 + 1, 100))
        for ridx, dpi in enumerate(config.dpis):
            ratbag.Resolution(
                p,
                index=ridx,
                capabilities=caps,
                dpi_list=dpi_list,
                dpi=dpi,
                enabled=not (config.dpi_disabled_slots & 1 << ridx),
            )

        self.ratbag_device.connect("commit", self.cb_commit)

    def cb_commit(
        self, ratbag_device: ratbag.Device, transaction: ratbag.CommitTransaction
    ):
        # FIXME: implement this
        transaction.complete(success=False)


@ratbag.driver.ratbag_driver("sinowealth")
class SinowealthDriver(ratbag.driver.HidrawDriver):
    def probe(
        self,
        rodent: ratbag.driver.Rodent,
        config: ratbag.driver.DeviceConfig,
    ) -> None:
        # We can create a ratbag device here, it won't exist until we emit
        # "device-added"
        ratbag_device = ratbag.Device(self, str(rodent.path), rodent.name, rodent.model)

        # This is the driver-specific device that will handle everything for us
        sinowealth_device = SinowealthDevice(rodent, ratbag_device)

        # Calling start() will make the device talk to the physical device
        sinowealth_device.start()

        # If we didn't throw an exception, we can now pretend the device
        # exists
        self.emit("device-added", ratbag_device)
