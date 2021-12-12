#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
"""
.. module:: util
   :synopsis: A collection of utility functions

"""

import binascii
import configparser
import logging
import pyudev

from pathlib import Path

logger = logging.getLogger(__name__)


def as_hex(bs):
    """
    Convert the bytes ``bs`` to a ``"ab 12 cd 34"`` string
    """
    hx = binascii.hexlify(bs).decode("ascii")
    return " ".join(["".join(s) for s in zip(hx[::2], hx[1::2])])


def find_hidraw_devices():
    """
    :return: a list of local hidraw device paths ``["/dev/hidraw0", "/dev/hidraw1"]``
    """
    devices = []

    context = pyudev.Context()
    for device in context.list_devices(subsystem="hidraw"):
        devices.append(device.device_node)
        # logger.debug(f"Found {device.device_node}")

    return devices


def load_data_files(path):
    """
    :return: a list of ``configparser.ConfigParser`` objects
    """
    assert path is not None

    files = {}
    for f in Path(path).glob("**/*.device"):
        parser = configparser.ConfigParser()
        # don't convert keys to lowercase
        parser.optionxform = lambda option: option
        parser.read(f)
        match = parser["Device"]["DeviceMatch"]
        for key in match.split(";"):
            files[key] = parser
            # logger.debug(f"Found data file for {key}")

    if not files:
        raise FileNotFoundException("Unable to find data files")

    return files


def load_device_info(devnode):
    """
    :return: a dictionary with information about the device at `devnode`
    """
    context = pyudev.Context()
    device = pyudev.Devices.from_device_file(context, devnode)

    def find_prop(device, prop):
        try:
            return device.properties[prop]
        except KeyError:
            try:
                return find_prop(next(device.ancestors), prop)
            except StopIteration:
                return None

    info = {}
    info["name"] = find_prop(device, "HID_NAME")
    info["vid"] = int(find_prop(device, "ID_VENDOR_ID") or 0, 16)
    info["pid"] = int(find_prop(device, "ID_MODEL_ID") or 0, 16)
    info["bus"] = find_prop(device, "ID_BUS")
    info["syspath"] = device.sys_path

    def find_report_descriptor(device):
        try:
            with open(Path(device.sys_path) / "report_descriptor", "rb") as fd:
                return fd.read()
        except FileNotFoundError:
            try:
                return find_report_descriptor(next(device.ancestors))
            except StopIteration:
                return None

    info["report_descriptor"] = find_report_descriptor(device)

    return info
