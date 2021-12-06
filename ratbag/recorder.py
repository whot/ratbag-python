#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import datetime
import yaml

import gi
from gi.repository import GObject

import ratbag


class YamlDeviceRecorder(ratbag.Recorder):
    """
    A simple recoder that logs the data to/from the device as a series of YAML
    objects. All elements in `config` are logged as attributes.

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

    def __init__(self, config):
        super().__init__(self)
        assert "logfile" in config
        self.logfile = open(config["logfile"], "w")
        self.attributes = {}

    def init(self, config):
        now = datetime.datetime.now().strftime("%y-%m-%d %H:%M")
        self.logfile.write(
            f"# generated {now}\n"
            f"logger: {type(self).__name__}\n"
            f"version: 1\n"
            f"attributes:\n"
        )
        for key, value in config.items():
            if type(value) == int:
                tstr = "int"
            elif type(value) == str:
                tstr = "str"
            elif type(value) == bytes:
                tstr = "bytes"
                value = list(value)
            self.logfile.write(f"  - {{name: {key}, type: {tstr}, value: {value}}}\n")

        self.logfile.write("data:\n")
        self.logfile.flush()

    def _log_data(self, direction, data):
        grouping = 8

        prefix = f"  - {direction}: ["
        prefix_len = len(prefix)
        group_width = prefix_len + len(" ,".join(["   " for _ in range(grouping)])) + 2
        idx = 0
        while idx < len(data):
            slice = data[idx : idx + grouping]

            datastr = prefix + ", ".join([f"{v:3d}" for v in slice])
            humanstr = "  # " + " ".join([f"{v:02x}" for v in slice])
            if idx + grouping > len(data):
                datastr += "]"
            else:
                datastr += ","

            self.logfile.write(f"{datastr:{group_width}s}")
            self.logfile.write(humanstr + "\n")
            idx += grouping
            prefix = " " * prefix_len
        self.logfile.flush()

    def log_rx(self, data):
        self._log_data("rx", data)

    def log_tx(self, data):
        self._log_data("tx", data)
