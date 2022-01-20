#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import attr
import enum
import logging

from typing import List

from gi.repository import GObject

import ratbag
import ratbag.hid
import ratbag.driver
import ratbag.util
from ratbag.parser import Spec, Parser

logger = logging.getLogger(__name__)


class OIPage(enum.IntEnum):
    INFO = 0x00
    GIMMICKS = 0xFD
    DEBUG = 0xFE
    ERROR = 0xFF


class OIFunction(enum.IntEnum):
    VERSION = 0x00
    FW_INFO = 0x01
    SUPPORTED_FUNCTION_PAGES = 0x02
    SUPPORTED_FUNCTIONS = 0x03


class OIFWField(enum.IntEnum):
    VENDOR = 0x00
    VERSION = 0x01
    NAME = 0x02


class OIError(enum.IntEnum):
    INVALID_VALUE = 0x01
    UNSUPPORTED_FUNCTION = 0x02
    CUSTOM = 0xFE


class ReportID(enum.IntEnum):
    SHORT = 0x20
    LONG = 0x21

    @property
    def size(self):
        return {
            ReportID.SHORT: 8,
            ReportID.LONG: 32,
        }[self]


REPORT_RATES = (125, 250, 500, 750, 1000)


@attr.s
class Query(object):
    device: ratbag.driver.Rodent = attr.ib()
    report_id: ReportID = attr.ib(
        default=ReportID.SHORT, validator=attr.validators.in_(ReportID)
    )
    query_spec: List[Spec] = attr.ib(default=attr.Factory(list))
    reply_spec: List[Spec] = attr.ib(default=attr.Factory(list))

    def run(self):
        # header is always the same
        spec = [
            Spec("B", "report_id"),
            Spec("B", "function_page"),
            Spec("B", "function"),
        ] + self.query_spec
        query = Parser.from_object(self, spec, pad_to=self.report_id.size)

        self.device.send(bytes(query))
        reply = self.device.recv()
        self.reply = self._autoparse(reply)
        self.parse_reply(reply)
        return self

    def _autoparse(self, bytes):
        if not self.reply_spec:

            class ReplyObject(object):
                pass

            return ReplyObject()

        spec = [
            Spec("B", "report_id"),
            Spec("B", "function_page"),
            Spec("B", "function"),
        ] + self.reply_spec

        result = Parser.to_object(bytes, spec)
        return result.object

    def parse_reply(self, data: bytes):
        """
        Override this in the subclass if :attr:`reply_spec` autoparsing is
        insufficient. Parse the given bytes and set the required instance
        attributes. :attr:`reply` is set with the bytes from the reply.
        """
        pass


@attr.s
class QueryFWVersion(Query):
    report_id = attr.ib(default=ReportID.SHORT)
    function_page = attr.ib(default=OIPage.INFO)
    function = attr.ib(default=OIFunction.VERSION)
    query_spec = attr.ib(default=attr.Factory(list))
    reply_spec = attr.ib(
        default=[
            Spec("B", "major"),
            Spec("B", "minor"),
            Spec("B", "patch"),
        ]
    )

    @classmethod
    def instance(cls, device):
        return cls(device=device)


@attr.s
class QueryFWInfo(Query):
    report_id = attr.ib(default=ReportID.SHORT)
    function_page = attr.ib(default=OIPage.INFO)
    function = attr.ib(default=OIFunction.FW_INFO)
    field_id: OIFWField = attr.ib(default=OIFWField.VERSION)
    query_spec = attr.ib(
        default=[
            Spec("B", "field_id"),
        ]
    )
    reply_spec = attr.ib(
        default=[
            Spec(
                "B",
                "string",
                greedy=True,
                convert_from_data=lambda s: bytes(s).decode("utf-8"),
            )
        ]
    )

    @classmethod
    def instance(cls, device, field_id: OIFWField):
        return cls(device=device, field_id=field_id)


@attr.s
class QuerySupportedPages(Query):
    report_id = attr.ib(default=ReportID.SHORT)
    function_page = attr.ib(default=OIPage.INFO)
    function = attr.ib(default=OIFunction.SUPPORTED_FUNCTION_PAGES)
    start_index = attr.ib(default=0)
    query_spec = attr.ib(
        default=[
            Spec("B", "start_index"),
        ]
    )
    reply_spec = attr.ib(
        default=[
            Spec("B", "count"),
            Spec("B", "remaining"),
            Spec("B", "pages", greedy=True),
        ]
    )

    @classmethod
    def instance(cls, device, start_index: int):
        return cls(device=device, start_index=start_index)


@attr.s
class QuerySupportedFunctions(Query):
    report_id = attr.ib(default=ReportID.SHORT)
    function_page = attr.ib(default=OIPage.INFO)
    function = attr.ib(default=OIFunction.SUPPORTED_FUNCTIONS)
    page = attr.ib(default=0)
    start_index = attr.ib(default=0)
    query_spec = attr.ib(
        default=[
            Spec("B", "page"),
            Spec("B", "start_index"),
        ]
    )
    reply_spec = attr.ib(
        default=[
            Spec("B", "count"),
            Spec("B", "remaining"),
            Spec("B", "functions", greedy=True),
        ]
    )

    @classmethod
    def instance(cls, device, page: int, start_index: int):
        return cls(device=device, page=page, start_index=start_index)


class OpenInputDevice(GObject.Object):
    def __init__(self, driver, rodent):
        GObject.Object.__init__(self)
        self.driver = driver
        self.rodent = rodent

    def start(self):
        output_reports = self.rodent.report_ids["output"]
        input_reports = self.rodent.report_ids["input"]
        if ReportID.SHORT not in output_reports or ReportID.SHORT not in input_reports:
            raise ratbag.driver.SomethingIsMissingError.from_rodent(
                self.rodent, "Missing Report ID {ReportID.SHORT.value:0x}"
            )

        query = QueryFWVersion.instance(self.rodent).run()
        logger.debug(
            f"protocol version {query.reply.major}.{query.reply.minor}.{query.reply.patch}"
        )

        vendor = QueryFWInfo.instance(self.rodent, OIFWField.VENDOR).run().reply.string
        version = (
            QueryFWInfo.instance(self.rodent, OIFWField.VERSION).run().reply.string
        )
        name = QueryFWInfo.instance(self.rodent, OIFWField.NAME).run().reply.string

        logger.debug(f"FW vendor: {vendor}, version: {version}, name: {name}")

        pages = []
        offset = 0
        while True:
            query = QuerySupportedPages.instance(self.rodent, offset).run()
            pages.extend(query.reply.pages[: query.reply.count])
            if query.reply.remaining <= 0:
                break

        logger.debug(f"Pages: {[OIPage(p) for p in pages]}")

        for p in pages:
            functions = []
            offset = 0
            while True:
                query = QuerySupportedFunctions.instance(self.rodent, p, offset).run()
                functions.extend(query.reply.functions[: query.reply.count])
                if query.reply.remaining <= 0:
                    break
            logger.debug(f"Page {p}: {[OIFunction(f) for f in functions]}")

        # This code is a port from the libratbag openinput driver. Which
        # does... nothing. It inits some profiles with hardcode values but
        # other than that - nothing.
        raise ratbag.driver.SomethingIsMissingError.from_rodent(
            self.rodent, "This driver doesn't do anything else...oops "
        )


@ratbag.driver.ratbag_driver("openinput")
class OpenInputDriver(ratbag.driver.HidrawDriver):
    def probe(
        self,
        rodent: ratbag.driver.Rodent,
        config: ratbag.driver.DeviceConfig,
    ) -> None:
        # This is the device that will handle everything for us
        roccat_device = OpenInputDevice(self, rodent)

        # Calling start() will make the device talk to the physical device
        ratbag_device = roccat_device.start()
        self.emit("device-added", ratbag_device)
