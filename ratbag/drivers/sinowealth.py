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


CONFIG_SIZE_USED_MIN = 131
CONFIG_SIZE_USED_MAX = 167

CONFIG_FLAGS_XY_RESOLUTION = 0x80


class ReportID(enum.IntEnum):
    CONFIG = 0x4
    CMD = 0x5
    CONFIG_LONG = 0x6

    @property
    def size(self) -> int:
        return {
            ReportID.CONFIG: 512,
            ReportID.CONFIG_LONG: 512,
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
            Spec("B", "config"),
            Spec("B", "dpi_count"),  # two nibbles!
            Spec("B", "dpi_enabled"),
            Spec("B", "dpi", repeat=16),
            Spec("BBB", "dpi_color", repeat=8),
            Spec("B", "rgb_effect"),
            Spec("B", "glorious_mode"),
            Spec("B", "glorious_direction"),
            Spec("B", "single_mode"),
            Spec("BBB", "single_color"),
            # FIXME: there's a bunch of other fields here
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
            }[obj.config & 0b111]
        except KeyError:
            logger.error(f"Invalid report rate {obj.config & 0b111}")
            report_rate = 0

        xy_independent = bool(obj.config & CONFIG_FLAGS_XY_RESOLUTION)

        def raw2dpi(raw: int) -> int:
            return (raw + 1) * 100

        converted = [raw2dpi(r) for r in obj.dpi]
        if xy_independent:
            dpis = list(zip(converted[::2], converted[1::2]))
        else:
            dpis = [(x, x) for x in converted[:8]]

        # Now create the Config object with all the data we have converted
        # already
        return cls(
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

        # GetFeature on the reply report ID
        reply_data = rodent.hid_get_feature(reply_report_id)
        if reply_report_id in (ReportID.CONFIG, ReportID.CONFIG_LONG) and not (
            CONFIG_SIZE_USED_MIN <= len(reply_data) <= CONFIG_SIZE_USED_MAX
        ):
            raise ratbag.driver.ProtocolError.from_rodent(
                rodent, f"Unexpected reply data size {len(reply_data)}"
            )

        # Parse to the properties
        rspec = [
            Spec("B", "report_id"),
            Spec("B", "cmd"),
        ] + self.reply_spec

        reply = Reply()
        Parser.to_object(reply_data, rspec, obj=reply)
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

        if config.independent_xy_resolution:
            caps = [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]
        else:
            caps = []
        dpi_list = tuple(range(200, 8200 + 1, 50))
        for ridx, dpi in enumerate(config.dpis):
            ratbag.Resolution(
                p,
                index=ridx,
                capabilities=caps,
                dpi_list=dpi_list,
                dpi=dpi,
                enabled=dpi[0] != 0,  # should use dpi_enabled?
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
