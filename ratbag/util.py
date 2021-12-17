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
import struct

from pathlib import Path

logger = logging.getLogger(__name__)
logger_autoparse = logging.getLogger("ratbag.autoparse")


def as_hex(bs):
    """
    Convert the bytes ``bs`` to a ``"ab 12 cd 34"`` string
    """
    if not bs:
        return "<none>"
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


def attr_from_data(obj, fmt_tuples, data, offset=0):
    """
    ``fmt_tuples`` is a list of tuples that are converted into attributes on
    ``obj``. Each entry is a tuple in the form ``(format, fieldname)`` where
    ``format`` is a `struct`` parsing format and fieldname is the
    attribute name. e.g.

     - ``("H", "report_rate")`` is a 16-bit ``obj.report_rate``
     - ``(">H", "report_rate")`` is a 16-bit BigEndian ``obj.report_rate``
     - ``("BBB", "color")`` is a ``(x, y, z)`` tuple of 8 bits
     - ``("BB", "_")`` are two bytes padding
     - ``("HH", "?")`` are two unknown 16-bit fields
     - ``("5*HH", "?")`` is a list of five tuples with 2 16 bit entries each

    Endianess defaults to BE. Prefix format with ``<`` or
    ``>`` and all **subsequent** fields use that endianess. ::

        format = [("B", "nprofiles"), (">H", "checksum"), ("<H", "resolution)]
        obj = MyObject()
        offset = attr_from_data(obj, format, mybytes, offset=0)
        print(obj.nprofiles)

    Grouping is possible by prefixing the format string with ``N*`` where
    ``N`` is an integer greater than 1.

    :param obj: the object to set the attributes for
    :param fmt_tuples: a list of tuples with the first element a struct format
        and the second element the attribute name
    :param data: the data to parse
    :param offset: the offset to start parsing from

    :returns: the new offset after parsing all tuples
    """

    logger_autoparse.debug(f"parsing: {as_hex(data)}")

    endian = ">"  # default to BE

    for fmt, name in fmt_tuples:
        # endianess is handled as a toggle, one field with different
        # endianness changes the rest
        if fmt[0] in [">", "<"]:
            endian = fmt[0]
            fmt = fmt[1:]

        groupcount = 1
        if fmt[0].isdigit():
            groupcount, fmt = fmt.split("*")
            groupcount = int(groupcount)
            assert groupcount > 1

        count = len(fmt)
        for _ in range(groupcount):
            val = struct.unpack_from(endian + fmt, data, offset=offset)
            sz = struct.calcsize(fmt)
            if name == "_":
                debugstr = "<pad bytes>"
            elif name == "?":
                debugstr = "<unknown>"
            else:
                if count == 1:
                    val = val[0]
                if groupcount > 1:
                    debugstr = f"self.{name:24s} += {val}"
                    attr = getattr(obj, name, [])
                    attr.append(val)
                    setattr(obj, name, attr)
                else:
                    debugstr = f"self.{name:24s} = {val}"
                    setattr(obj, name, val)
            logger_autoparse.debug(
                f"offset {offset:02d}: {as_hex(data[offset:offset+sz]):5s} → {debugstr}"
            )
            offset += sz

    return offset


def attr_to_data(obj, fmt_tuples, maps={}):
    """
    The inverse of :func:`attr_from_data`.
    ``fmt_tuples`` is a list of tuples that represent attributes on
    ``obj``. Each entry is a tuple in the form ``(format, fieldname)`` where
    ``format`` is a `struct`` parsing format and fieldname is the
    attribute name. Each attribute is packed into a binary struct according to
    the format specification.

    :param maps: a dictionary of ``{ name: func(bytes) }`` where for each attribute with the
        name, the matching function is called to produce that value instead. The argument to the
        function is the list of already written bytes, the return value must match the attribute it
        would otherwise have.

    :return: the bytes representing the objects, given the format tuples
    """
    data = bytearray(4096)
    offset = 0
    endian = ">"  # default to BE

    for fmt, name in fmt_tuples:
        # endianess is handled as a toggle, one field with different
        # endianness changes the rest
        if fmt[0] in [">", "<"]:
            endian = fmt[0]
            fmt = fmt[1:]

        groupcount = 1
        if fmt[0].isdigit():
            groupcount, fmt = fmt.split("*")
            groupcount = int(groupcount)
            assert groupcount > 1

        count = len(fmt)
        for idx in range(groupcount):
            # Padding bytes and unknown are always zero
            # If the device doesn't support writing unknown bytes to zero, map
            # it to a property
            if name in ["_", "?"]:
                if len(fmt) > 1:
                    val = [0] * len(fmt)
                    if groupcount > 1:
                        val = groupcount * [val]
                else:
                    val = 0
                    if groupcount > 1:
                        val = groupcount * [val]
            else:
                # If this element has a mapping, use that.
                if name in maps:
                    val = maps[name](data[:offset])
                else:
                    val = getattr(obj, name)
            if groupcount > 1:
                val = val[idx]
            sz = struct.calcsize(fmt)
            if offset + sz >= len(data):
                data.extend([0] * 4096)

            if count > 1:
                struct.pack_into(endian + fmt, data, offset, *val)
            else:
                struct.pack_into(endian + fmt, data, offset, val)
            if name == "_":
                debugstr = "<pad bytes>"
            elif name == "?":
                debugstr = "<unknown>"
            else:
                debugstr = f"self.{name}"
            valstr = f"{val}"
            logger_autoparse.debug(
                f"offset {offset:02d}: {debugstr:30s} is {valstr:8s} → {as_hex(data[offset:offset+sz]):5s}"
            )
            offset += sz

    return bytes(data[:offset])
