#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import attr
import logging
import pathlib
import yaml

from typing import Dict, List, Optional

import ratbag
import ratbag.driver

from ratbag.util import as_hex

logger = logging.getLogger(__name__)


class InsufficientDataError(Exception):
    """
    Indicates that insufficient data is available for the emulator to work.
    """

    pass


class Reply(object):
    """
    An emulated reply from the device. If the source recording always replied
    with the same value for the request, the reply always yields the same
    value.

    If the source recording has multiple replies for the same request, this reply
    yields those values, in order.
    """

    def __init__(self, tx: bytes, rx: bytes, name: Optional[str] = None):
        self.tx = tx
        self.values: List[bytes] = [rx]
        self.name = name

    def add_value(self, value: bytes):
        self.values.append(value)

    def _finalize(self) -> None:
        reduced = list(set(self.values))
        if len(reduced) == 1:
            self.values = reduced

            def same_value():
                yield reduced[0]

            self._it = iter(same_value())
        else:
            self._it = iter(self.values)

    def next(self) -> bytes:
        try:
            return next(self._it)
        except AttributeError:
            self._finalize()
            return next(self._it)

    def __str__(self) -> str:
        return f"{self.name + ': ' if self.name else ''} tx: {as_hex(self.tx)} rx: {[as_hex(v) for v in self.values]}"


class YamlDevice(ratbag.driver.Rodent):
    """
    Creates a :class:`ratbag.Rodent` instance based on a recording made by
    :class:`ratbag.recoder.YamlDeviceRecorder`.

    This device is a dictionary of all tx/rx pairs recorded earlier, a
    :meth:`send` call will look up the interaction and the next
    :meth:`recv_sync` invocation returns the matching data for that
    transmission.

    :param recording: the YAML file previously recorded
    """

    def __init__(self, recording: pathlib.Path):
        y = yaml.safe_load(open(recording).read())

        info = ratbag.driver.DeviceInfo(
            pathlib.Path("/nopath"), pathlib.Path("/sys/nopath")
        )

        for att in y["attributes"]:
            if att["type"] == "bytes":
                v = bytes(att["value"])  # type: ignore
            elif att["type"] == "int":
                v = int(att["value"])  # type: ignore
            elif att["type"] == "str":
                v = att["value"]  # type: ignore
            elif att["type"] == "bool":
                v = att["value"].lower() == "true"  # type: ignore
            try:
                setattr(info, att["name"], v)
            except AttributeError as e:
                logger.debug(f"Skipping {att['name']}: {e}")

        super().__init__(info)

        self.conversations: Dict[bytes, bytes] = {}
        self.ioctls: Dict[str, Dict[bytes, Reply]] = {}
        key = None
        value = None
        for data in y["data"]:
            if data["type"] == "fd":
                rx = data.get("tx")
                if rx is not None:
                    key = rx
                tx = data.get("rx")
                if tx is not None:
                    value = tx

                if key is not None and value is not None:
                    key = bytes(key)
                    value = bytes(value)
                    self.conversations[key] = value
                    key, value = None, None
            elif data["type"] == "ioctl":
                name = data["name"]
                tx = bytes(data["tx"])
                rx = data.get("rx")
                if rx:
                    rx = bytes(rx)
                if name not in self.ioctls:
                    self.ioctls[name] = {}
                try:
                    reply = self.ioctls[name][tx]
                    reply.add_value(rx)
                except KeyError:
                    reply = Reply(tx, rx, name=name)
                    self.ioctls[name][tx] = reply

    def open(self):
        pass

    def start(self) -> None:
        pass

    def send(self, data: bytes) -> None:
        """
        :raises InsufficientDataError: when the data is not in the recording and
            thus no matching reply can be identified.
        """
        try:
            self.recv_data = self.conversations[data]
            logger.debug(f"send: {as_hex(data)}")
        except KeyError:
            raise InsufficientDataError(
                f"Unable to find reply to request: {as_hex(data)}"
            )

    def recv(self) -> bytes:
        """Return the matching reply for the last :meth:`send` call"""
        logger.debug(f"recv: {as_hex(self.recv_data)}")
        return self.recv_data

    def hid_get_feature(self, report_id: int) -> bytes:
        for r in self.ioctls.get("HIDIOCGFEATURE", {}).values():
            # we know the first byte is the report ID
            if r.tx[0] == report_id:
                data = r.next()
                logger.debug(f"hid_get_feature: {report_id:02x} → {as_hex(data)}")
                return data
        else:
            raise InsufficientDataError(f"HIDIOCGFEATURE report_id {report_id}")

    def hid_set_feature(self, report_id: int, data: bytes) -> None:
        for r in self.ioctls.get("HIDIOCSFEATURE", {}).values():
            if r.tx == data:
                logger.debug(f"hid_set_feature: {as_hex(data)}")
                r.next()
                return
        else:
            raise InsufficientDataError(
                f"HIDIOCSFEATURE report_id {report_id}: {as_hex(data)}"
            )


@attr.s
class YamlEmulator:
    file: pathlib.Path = attr.ib()

    def setup(self):
        monitor = ratbag.driver.HidrawMonitor.instance()
        monitor.disable()  # FIXME: this should probably be configurable
        rodent = YamlDevice(self.file)
        monitor.add_rodent(rodent)
