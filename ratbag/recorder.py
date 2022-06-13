#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import attr
import datetime

from pathlib import Path
from typing import Any, Dict

import ratbag


@attr.s
class YamlDeviceRecorder(ratbag.Recorder):
    """
    A simple recorder that logs the data to/from the device as a series of
    YAML objects. All elements in `config` are logged as attributes.

    The output of this logger can be consumed by
    :class:`ratbag.emulator.YamlDevice`.

    Example output: ::

        logger: YAMLDeviceRecorder
        attributes:
          - { name: name, type: str, value: the device name }
          - { name: path, type: str: value: /dev/hidraw0 }
          - { name: report_descriptor, type: bytes, value: [1, 2, 3] }
        data:
          - tx: [ 16, 255,   0,  24,   0,   0,   0]        # 10 ff 00 18 00 00 00
          - rx: [ 17, 255,   0,  24,   4,   2,   0,   0,   # 11 ff 00 18 04 02 00 00
                   0,   0,   0,   0,   0,   0,   0,   0,   # 00 00 00 00 00 00 00 00
                   0,   0,   0,   0]                       # 00 00 00 00

    :param config: a dictionary with attributes to log

    """

    _filename: Path = attr.ib()
    info: Dict = attr.ib()
    last_timestamp: datetime.datetime = attr.ib(init=False)

    @last_timestamp.default
    def last_ts_default(self):
        return datetime.datetime.now()

    @classmethod
    def create_in_blackbox(
        cls, blackbox: ratbag.Blackbox, filename: str, info=dict()
    ) -> "YamlDeviceRecorder":
        recorder = YamlDeviceRecorder(
            filename=blackbox.make_path(filename),
            info=info,
        )
        return recorder

    def start(self) -> None:
        self.logfile = open(self._filename, "w")
        now = self.last_timestamp.strftime("%y-%m-%d %H:%M")
        self.logfile.write(
            f"# generated {now}\n"
            f"logger: {type(self).__name__}\n"
            f"version: 1\n"
            f"attributes:\n"
        )
        for key, value in self.info.items():
            comment = ""
            if type(value) == int:
                tstr = "int"
                comment = f"  # {value:04x}"
            elif type(value) == str:
                tstr = "str"
            elif type(value) == bytes:
                tstr = "bytes"
                value = list(value)
            self.logfile.write(
                f"  - {{name: {key}, type: {tstr}, value: {value}}}{comment}\n"
            )

        # So we definitely write out the first current time
        self.last_timestamp = datetime.datetime.fromtimestamp(0)
        self.logfile.write("data:\n")
        self._log_timestamp()
        self.logfile.flush()

    def _log_timestamp(self) -> None:
        ts = datetime.datetime.now()
        td = ts - self.last_timestamp
        if td > datetime.timedelta(minutes=5):
            self.last_timestamp = ts
            now = ts.strftime("%H:%M")
            self.logfile.write(f"# Current time: {now}\n")

    def _log_bytes(self, data: bytes, prefix: str = "") -> None:
        GROUPING = 8

        prefix += "["
        prefix_len = len(prefix)
        group_width = prefix_len + len(" ,".join(["   "] * GROUPING)) + 2

        idx = 0
        while idx < len(data):
            slice = data[idx : idx + GROUPING]

            datastr = prefix + ", ".join([f"{v:3d}" for v in slice])
            humanstr = "  # " + " ".join([f"{v:02x}" for v in slice])
            if idx + GROUPING > len(data):
                datastr += "]"
            else:
                datastr += ","

            self.logfile.write(f"{datastr:{group_width}s}{humanstr}\n")
            idx += GROUPING
            prefix = " " * prefix_len

    def _log_data(
        self,
        direction: str,
        data: bytes,
        extra: Dict[str, Any] = {"type": "fd"},
    ):
        self._log_timestamp()

        it = iter(extra.items())
        k, v = next(it)
        self.logfile.write(f"  - {k}: {v}\n")
        for k, v in it:
            self.logfile.write(f"    {k}: {v}\n")

        prefix = f"    {direction}: "
        self._log_bytes(data, prefix)
        self.logfile.flush()

    def log_rx(self, data: bytes) -> None:
        self._log_data("rx", data)

    def log_tx(self, data: bytes) -> None:
        self._log_data("tx", data)

    def log_ioctl_tx(self, ioctl_name: str, data: bytes) -> None:
        self._log_data("tx", data, extra={"type": "ioctl", "name": ioctl_name})

    def log_ioctl_rx(self, ioctl_name: str, data: bytes) -> None:
        self._log_bytes(data, prefix=f"    rx: ")
        self.logfile.flush()
