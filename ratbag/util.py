#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
"""
.. module:: util
   :synopsis: A collection of utility functions

"""

import attr
import binascii
import configparser
import logging
import pkg_resources
import pyudev
import struct

from typing import Any, Dict, List, Optional, Tuple, Union

FormatSpec = List[Tuple[str, str]]

from pathlib import Path

logger = logging.getLogger(__name__)
logger_autoparse = logging.getLogger("ratbag.autoparse")


def as_hex(bs: bytes) -> str:
    """
    Convert the bytes ``bs`` to a ``"ab 12 cd 34"`` string. ::

        >>> as_hex(bytes([1, 2, 3]))
        '01 02 03'
    """
    if not bs:
        return "<none>"
    hx = binascii.hexlify(bs).decode("ascii")
    return " ".join(["".join(s) for s in zip(hx[::2], hx[1::2])])


def add_to_sparse_tuple(tpl: Tuple, index: int, new_value) -> Tuple:
    """
    Return a new tuple based on tpl with new_value added at the given index.
    The tuple is either expanded with ``None`` values to match the new size
    required or the value is replaced. ::

        >>> t = add_to_sparse_tuple(('a', 'b'), 5, 'f')
        >>> print(t)
        ('a', 'b', None, None, None, 'f')
        >>> t = add_to_sparse_tuple(t, 3, 'd')
        >>> print(t)
        ('a', 'b', None, 'd', None, 'f')

     This function does not replace existing values in the tuple. ::

        >>> t = add_to_sparse_tuple(('a', 'b'), 0, 'A')
        Traceback (most recent call last):
            ...
        AssertionError
    """
    l = [None] * max(len(tpl), index + 1)
    for i, v in enumerate(tpl):
        l[i] = v

    assert l[index] is None
    l[index] = new_value
    return tuple(l)


def find_hidraw_devices() -> List[str]:
    """
    :return: a list of local hidraw device paths ``["/dev/hidraw0", "/dev/hidraw1"]``
    """
    devices = []

    context = pyudev.Context()
    for device in context.list_devices(subsystem="hidraw"):
        devices.append(device.device_node)
        # logger.debug(f"Found {device.device_node}")

    return devices


@attr.s
class DataFile:
    name: str = attr.ib()
    matches: List[str] = attr.ib()
    driver: str = attr.ib()
    driver_options: Dict[str, str] = attr.ib(default=attr.Factory(dict))

    @classmethod
    def from_config_parser(cls, parser: configparser.ConfigParser):
        name = parser["Device"]["Name"]
        matchstr = parser["Device"]["DeviceMatch"]
        matches = [x.strip() for x in matchstr.split(";") if x.strip()]
        driver = parser["Device"]["Driver"]

        try:
            driver_options = dict(parser.items(f"Driver/{driver}"))
        except configparser.NoSectionError:
            driver_options = {}

        return cls(
            name=name, matches=matches, driver=driver, driver_options=driver_options
        )


def load_data_files() -> List[DataFile]:
    """
    :return: a list of ``configparser.ConfigParser`` objects
    """

    files = []
    for f in filter(
        lambda n: n.endswith(".device"),
        pkg_resources.resource_listdir("ratbag", "devices"),
    ):
        parser = configparser.ConfigParser()
        # don't convert keys to lowercase
        parser.optionxform = lambda option: option  # type: ignore
        stream = (
            pkg_resources.resource_stream("ratbag", f"devices/{f}")
            .read()
            .decode("utf-8")
        )
        parser.read_string(stream)
        try:
            files.append(DataFile.from_config_parser(parser))
        except Exception as e:
            logger.error(f"Failed to parse {f}: {str(e)}")

    if not files:
        raise FileNotFoundError("Unable to find data files")

    return files


def attr_from_data(
    obj: object,
    fmt_tuples: List[Tuple[str, str]],
    data: bytes,
    offset: int = 0,
    quiet: bool = False,
) -> int:
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

        >>> class MyObject(object):
        ...     pass
        >>> mybytes = bytes(range(16))
        >>> format = [("B", "nprofiles"), (">H", "checksum"), ("<H", "resolution")]
        >>> obj = MyObject()
        >>> offset = attr_from_data(obj, format, mybytes, offset=0)
        >>> print(obj.nprofiles)
        0
        >>> hex(obj.checksum)
        '0x102'
        >>> hex(obj.resolution)
        '0x403'

    Repeating is possible by prefixing the format string with ``N*`` where
    ``N`` is an integer greater than 1.

    :param obj: the object to set the attributes for
    :param fmt_tuples: a list of tuples with the first element a struct format
        and the second element the attribute name
    :param data: the data to parse
    :param offset: the offset to start parsing from

    :returns: the new offset after parsing all tuples
    """

    if not quiet:
        logger_autoparse.debug(f"parsing {type(obj).__name__}: {as_hex(data)}")

    endian = ">"  # default to BE

    for fmt, name in fmt_tuples:
        # endianess is handled as a toggle, one field with different
        # endianness changes the rest
        if fmt[0] in [">", "<"]:
            endian = fmt[0]
            fmt = fmt[1:]

        repeat = 1
        if fmt[0].isdigit():
            rpt, fmt = fmt.split("*")
            repeat = int(rpt)
            assert repeat > 1

        count = len(fmt)
        for repeat_index in range(repeat):
            val = struct.unpack_from(endian + fmt, data, offset=offset)
            sz = struct.calcsize(fmt)
            if name == "_":
                debugstr = "<pad bytes>"
            elif name == "?":
                debugstr = "<unknown>"
            else:
                if count == 1:
                    val = val[0]
                if repeat > 1:
                    debugstr = f"self.{name:24s} += {val}"
                    if repeat_index == 0:
                        setattr(obj, name, [])
                    attr = getattr(obj, name)
                    attr.append(val)
                else:
                    debugstr = f"self.{name:24s} = {val}"
                    setattr(obj, name, val)
            if not quiet:
                logger_autoparse.debug(
                    f"offset {offset:02d}: {as_hex(data[offset:offset+sz]):5s} → {debugstr}"
                )
            offset += sz

    return offset


def attr_to_data(obj: object, fmt_tuples: FormatSpec, maps={}) -> bytes:
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

    logger_autoparse.debug(f"deparsing {type(obj).__name__}")

    for fmt, name in fmt_tuples:
        # endianess is handled as a toggle, one field with different
        # endianness changes the rest
        if fmt[0] in [">", "<"]:
            endian = fmt[0]
            fmt = fmt[1:]

        repeat = 1
        if fmt[0].isdigit():
            rpt, fmt = fmt.split("*")
            repeat = int(rpt)
            assert repeat > 1

        count = len(fmt)
        for idx in range(repeat):
            val: Any = None  # just to shut up mypy
            # Padding bytes and unknown are always zero
            # If the device doesn't support writing unknown bytes to zero, map
            # it to a property
            if name in ["_", "?"]:
                if len(fmt) > 1:
                    val = [0] * len(fmt)
                    if repeat > 1:
                        val = repeat * [val]
                else:
                    val = 0
                    if repeat > 1:
                        val = repeat * [val]
            else:
                # If this element has a mapping, use that.
                if name in maps:
                    val = maps[name](data[:offset])
                else:
                    val = getattr(obj, name)
            if repeat > 1:
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
