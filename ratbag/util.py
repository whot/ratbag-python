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


def ffs(x: int) -> int:
    if x == 0:
        return 0
    elif x & 0x1:
        return 1
    else:
        return ffs(x >> 1) + 1


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


def to_tuple(x) -> Tuple:
    try:
        return tuple(set(x))
    except TypeError as e:
        raise ValueError("Invalid value: {e}")


def to_sorted_tuple(x) -> Tuple:
    try:
        return tuple(sorted(set(x)))
    except TypeError as e:
        raise ValueError("Invalid value: {e}")
