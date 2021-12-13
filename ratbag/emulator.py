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
import ratbag.drivers


class InsufficientData(Exception):
    """
    Indicates that insufficient data is available for the emulator to work.
    """

    pass


class YamlDevice(ratbag.drivers.Rodent):
    """
    Creates a :class:`ratbag.Rodent` instance based on a recording made by
    :class:`ratbag.recoder.YamlDeviceRecorder`.

    This device is a dictionary of all tx/rx pairs recorded earlier, a
    :meth:`send` call will look up the interaction and the next
    :meth:`recv_sync` invocation returns the matching data for that
    transmission.

    :param recording: the YAML file previously recorded
    """

    def __init__(self, recording):
        y = yaml.safe_load(open(recording).read())

        for attr in y["attributes"]:
            if attr["type"] == "bytes":
                value = bytes(attr["value"])
            elif attr["type"] == "int":
                value = int(attr["value"])
            elif attr["type"] == "str":
                value = attr["value"]
            elif attr["type"] == "bool":
                value = attr["value"].lower() == "true"
            setattr(self, attr["name"], value)

        self.conversations = {}
        key = None
        value = None
        for data in y["data"]:
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

    def start(self):
        pass

    def send(self, data):
        """
        :raises InsufficientData: when the data is not in the recording and
            thus no matching reply can be identified.
        """
        try:
            self.recv_data = self.conversations[data]
        except KeyError:
            raise InsufficientData(f"Unable to find reply to request: {data}")

    def recv(self):
        """Return the matching reply for the last :meth:`send` call"""
        return self.recv_data
