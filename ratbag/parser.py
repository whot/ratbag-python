#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

"""
A Parser helper function to convert a byte array to a Python object and the
other way around. The conversion is specified in a list of :class:`Spec`
instances, for example::

    data = bytes(range(16))
    spec = [
        Spec("B", "zero"),
        Spec("B", "first"),
        Spec("H", "second", endian="BE"),
        Spec("H", "third", endian="le"),
        Spec("BB", "tuples", repeat=5)
    ]
    result = Parser.to_object(data, spec)
    assert result.size == len(data)
    assert result.object.zero == 0
    assert result.object.one == 0x1
    assert result.object.second == 0x0203
    assert result.object.third == 0x0504 # little endian
    assert result.object.tuples == [(6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]

And likewise, an object can be turned into a bytearray. ::

    new_data = Parser.from_object(result.object, spec)
    assert new_data == data

See the :class:`Spec` documentation for details on the format.
"""

import attr
import logging
import struct

from ratbag.util import as_hex

from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


class _ResultObject(object):
    """
    A generic object that has its attribute is set, used if :meth:`Parser.to_object`
    has an ``obj`` argument of ``None``.
    """

    pass


@attr.s
class Spec(object):
    @attr.s
    class ConverterArg:
        bytes: bytes = attr.ib()
        value: Any = attr.ib()
        index: int = attr.ib()

    """
    The format specification for a single **logical** in a data set.
    """
    format: str = attr.ib()
    """
    The format, must be compatible to Python's ``struct`` format specifiers,
    excluding the endian prefixes. If the format contains more than one
    element, the respective object attribute is a tuple.
    """
    name: str = attr.ib()
    """
    The name to assign to the resulting object attribute.
    """
    endian: str = attr.ib(default="BE", validator=attr.validators.in_(["BE", "le"]))
    """
    Endianess of the field, one of ``"BE"`` or ``"le"``.
    """
    repeat: int = attr.ib(default=1, validator=attr.validators.instance_of(int))
    """
    The number of times this field repeats in struct. Where repeat is greater
    than 1, the resulting attribute is a list with ``repeat`` elements (each
    element may be tuple, see ``format``).
    """
    convert_to_data: Optional[Callable[[ConverterArg], Any]] = attr.ib(default=None)
    """
    Conversion function of this attribute to data. This function takes the
    data bytes produced so far by :meth:`Parser.from_object` and the current
    value and index (if applicable). It must return a value compatible to the
    format specifier. Specifically:

    - if ``format`` specifies more than one type, the return value must be a
      tuple
    - if ``repeat`` is greater than 1, the return value must be a list of
      ``repeat`` elements. Note that this function is called once per element
      the list, with the data argument updated accordingly.

    An example for producing a checksum with ``some_crc()``: ::

        specs = []  # other fields
        checksum_spec("H", "checksum", convert_to_data=lambda bs, v, idx: some_crc(bs))
        data = Parser.from_object(myobj, specs + checksum_spec)
        assert data[-2:] == some_crc(data[:-2])
    """

    _size: int = attr.ib(init=False)
    _count: int = attr.ib(init=False)

    def __attrs_post_init__(self):
        self._size = struct.calcsize(self.format)
        self._count = len(self.format)

    @repeat.validator
    def _check_repeat(self, attribute, value):
        if value <= 0:
            raise ValueError("repeat must be greater than zero")


@attr.s
class Result(object):
    """
    The return value from :meth:`Parser.to_object`
    """

    object: Any = attr.ib()
    """
    The object passed to :meth:`Parser.to_object` or otherwise an unspecified
    instance with all attribute names as requested by the parser spec.
    """
    size: int = attr.ib()
    """
    The number of bytes used to create this object
    """


@attr.s
class Parser(object):
    @classmethod
    def to_object(cls, data: bytes, specs: List[Spec], obj: object = None) -> Result:
        """
        Convert the given data into an object according to the specs. If
        ``obj`` is not ``None``, the attributes are set on that
        object (resetting any attributes of the same name already set on the
        object). Otherwise, a new generic object is created with all
        attributes as specified in the parser specs.
        """
        if obj is None:
            obj = _ResultObject()

        offset = 0
        for spec in specs:
            endian = {"BE": ">", "le": "<"}[spec.endian]
            for idx in range(spec.repeat):
                val = struct.unpack_from(endian + spec.format, data, offset=offset)
                if spec.name == "_":
                    debugstr = "<pad bytes>"
                elif spec.name == "?":
                    debugstr = "<unknown>"
                else:
                    if spec._count == 1:
                        val = val[0]
                    if spec.repeat > 1:
                        debugstr = f"self.{spec.name:24s} += {val}"
                        if idx == 0:
                            setattr(obj, spec.name, [])
                        getattr(obj, spec.name).append(val)
                    else:
                        debugstr = f"self.{spec.name:24s} = {val}"
                        setattr(obj, spec.name, val)
                logger.debug(
                    f"offset {offset:02d}: {as_hex(data[offset:offset+spec._size]):5s} → {debugstr}"
                )
                offset += spec._size
        return Result(obj, offset)

    @classmethod
    def from_object(cls, obj: Any, specs: List[Spec], pad_to: int = 0) -> bytes:
        """
        Convert the attributes on the given objects to a byte array, given the
        specifications (in-order). This is the inverse of :meth:`Parser.to_object`.

        Note that each attribute must exist on the object and have the format
        compatible by its respective spec. For example, a :class:`Spec` with

        - a format ``"BB"`` must be a tuple of 2 bytes
        - a format ``"H"`` with a ``repeat`` of 5 must be a list of five 16-bit integers,
        - a format ``"HB"`` with a ``repeat`` of 3 must be a list of three
          tuples with a 16-bit integer and byte each
        """
        data = bytearray(4096)
        offset = 0

        for spec in specs:
            endian = {"BE": ">", "le": "<"}[spec.endian]
            for idx in range(spec.repeat):
                val: Any = None  # just to shut up mypy
                if spec.name in ["_", "?"]:
                    val = [0] * spec._count if spec._count > 1 else 0
                    if spec.repeat > 1:
                        val = spec.repeat * [val]
                else:
                    val = getattr(obj, spec.name)
                    if spec.convert_to_data is not None:
                        val = spec.convert_to_data(
                            Spec.ConverterArg(data[:offset], val, idx)
                        )

                if spec.repeat > 1:
                    val = val[idx]
                if offset + spec._size >= len(data):
                    data.extend([0] * 4096)

                if spec._count > 1:
                    struct.pack_into(endian + spec.format, data, offset, *val)
                else:
                    struct.pack_into(endian + spec.format, data, offset, val)

                if spec.name == "_":
                    debugstr = "<pad bytes>"
                elif spec.name == "?":
                    debugstr = "<unknown>"
                else:
                    debugstr = f"self.{spec.name}"
                valstr = f"{val}"
                logger.debug(
                    f"offset {offset:02d}: {debugstr:30s} is {valstr:8s} → {as_hex(data[offset:offset+spec._size]):5s}"
                )
                offset += spec._size
        return bytes(data[:offset]).ljust(pad_to, b"\x00")
