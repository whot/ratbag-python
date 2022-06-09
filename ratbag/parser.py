#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

"""
A Parser helper function to convert a byte array to a Python object and the
other way around. The conversion is specified in a list of :class:`Spec`
instances, for example:

    >>> data = bytes(range(16))
    >>> spec = [
    ...     Spec("B", "zero"),
    ...     Spec("B", "first"),
    ...     Spec("H", "second", endian="BE"),
    ...     Spec("H", "third", endian="le"),
    ...     Spec("BB", "tuples", repeat=5)
    ... ]
    ...
    >>> result = Parser.to_object(data, spec)
    >>> assert result.size == len(data)
    >>> assert result.object.zero == 0
    >>> assert result.object.first == 0x1
    >>> assert result.object.second == 0x0203
    >>> assert result.object.third == 0x0504 # little endian
    >>> assert result.object.tuples == [(6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]

And likewise, an object can be turned into a bytearray: ::

    >>> new_data = Parser.from_object(result.object, spec)
    >>> assert new_data == data

See the :class:`Spec` documentation for details on the format.
"""

import attr
import logging
import re
import struct

from ratbag.util import as_hex

from typing import Any, Callable, Dict, List, Optional, Type, Union

logger = logging.getLogger(__name__)


@attr.s
class Spec(object):
    """
    The format specification for a single **logical** in a data set. This is
    used in :meth:`Parser.to_object` or :meth:`Parser.from_object` to convert
    from or to a byte stream. For example:

    - ``Spec("B", "myattr")`` is a single byte from/to an object's ``myattr``
      property
    - ``Spec("BB", "point")`` is a tuple of two bytes from/to an object's ``myattr``
      property

    See :meth:`Parser.to_object` and :meth:`Parser.from_object` for details.
    """

    @attr.s
    class ConverterArg:
        """
        The argument passed to :attr:`convert_to_data`
        """

        bytes: bytes = attr.ib()
        value: Any = attr.ib()
        index: int = attr.ib()

    format: str = attr.ib()
    """
    The format, must be compatible to Python's ``struct`` format specifiers,
    excluding the endian prefixes. If the format contains more than one
    element, the respective object attribute is a tuple.

    With the exception of fixed-length strings (``4s`` for a 4-byte string)
    this format must not contain any repeat specifiers. Use the ``repeat``
    attribute instead. IOW:

        >>> Spec("3s", "string")  # One 3-byte string
        >>> Spec("s", "string", repeat=3)  # Three 1-byte strings
        >>> Spec("3H", "foo")  # Not permitted

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
    greedy: bool = attr.ib(default=False)
    """
    If true, ``repeat`` is ignored and the current field repeats until the
    remainder of the available data. This takes the current format spec into
    account. For example, a `HH` tuple has 4 bytes and will repeat 5 times in
    a data size 20.

    If the data size is not a multiple of the current format size, the
    remainder is silently skipped:

        >>> spec = Spec("H", "foo", greedy=True)
        >>> data = Parser.to_object(bytes(5), spec)
        >>> assert data.object.size == 4


    """
    convert_from_data: Optional[Callable[[Any], Any]] = attr.ib(default=None)
    """
    Conversion function for the data. An example for converting a sequence of
    bytes to a string:

        >>> spec = Spec("B", "foo", repeat=3, convert_from_data=lambda s: bytes(s).decode("utf-8"))
        # Or alternatively use the string length format:
        >>> spec = Spec("3s", "foo", convert_from_data=lambda s: s.decode("utf-8"))
        >>> data = Parser.to_object("bar".encode("utf-8"), spec)
        >>> assert data.object.foo == "bar"

    Note that the conversion happens once all ``repeat`` have been completed,
    i.e. the input value for ``repeat > 1`` is a list.
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

        >>> specs = []  # other fields
        >>> checksum_spec("H", "checksum", convert_to_data=lambda bs, v, idx: some_crc(bs))
        >>> data = Parser.from_object(myobj, specs + checksum_spec)
        >>> assert data[-2:] == some_crc(data[:-2])
    """

    _size: int = attr.ib(init=False)
    _count: int = attr.ib(init=False)

    def __attrs_post_init__(self):
        self._size = struct.calcsize(self.format)
        invalid = re.findall(r"\d+[^s\d]+", self.format)
        assert not invalid, f"Invalid use of repeat found in pattern(s): {invalid}"

        # struct allows repeats which are useful for strings in particular.
        # Where they're used, make the count a function of the struct format
        # specifiers only, not the repeats, i.e. a format like "3s" is one
        # string, not a tuple of two.
        self._count = len(re.sub(r"[0-9]", "", self.format))

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
    def to_object(
        cls,
        data: bytes,
        specs: List[Spec],
        obj: object = None,
        result_class: Union[str, Type] = "Result",
    ) -> Any:
        """
        Convert the given data into an object according to the specs. If
        ``obj`` is not ``None``, the attributes are set on that
        object (resetting any attributes of the same name already set on the
        object). Otherwise, a new generic object is created with all
        attributes as specified in the parser specs.

        The ``result_class`` specifies either the type of class to
        instantiate, or the name of the created class for this object.

            >>> specs = [Spec("B", "field")]
            >>> r = Parser.to_object(bytes(16), specs, result_class = "Foo")
            >>> print(type(r.object).__name__)
            Foo
            >>> class Bar:
            ...     def __init__(self, field):
            ...         pass
            >>> r = Parser.to_object(bytes(16), specs, result_class = Bar)
            >>> assert isinstance(r.object, Bar)

        Where an existing type is used, that type must take all Spec fields as
        keyword arguments in the constructor, except:

        - Spec names with a single leading underscore are expected to drop that
          underscore in the constructor.
        - Spec names with a double leading underscore are ignored
        """
        # Only the last element can be greedy
        assert all([spec.greedy is False for spec in list(reversed(specs))[1:]])

        # This parser is quite noisy but if the input is a zero-byte array
        # (used by some drivers to init an object with all spec fields) we
        # disable the logger. This should be handled better (specifically: the
        # driver shouldn't need to do this) but for now it'll do.
        disable_logger = data == bytes(len(data))
        if disable_logger:
            logger.debug("Parsing zero byte array, detailed output is skipped")

        # All parsing data is temporarily stored in this dictionary which is
        # simply: { spec.name: parsed_value }
        # Once we're done parsing we move all these to the object passed in
        values: Dict[str, Any] = {}

        offset = 0
        for spec in specs:
            endian = {"BE": ">", "le": "<"}[spec.endian]
            if spec.greedy:
                repeat = len(data[offset:]) // struct.calcsize(spec.format)
            else:
                repeat = spec.repeat
            for idx in range(repeat):
                try:
                    val = struct.unpack_from(endian + spec.format, data, offset=offset)
                except struct.error as e:
                    logger.error(
                        f"Parser error while parsing spec {spec} at offset {offset}: {e}"
                    )
                    raise e

                if spec.name == "_":
                    debugstr = "<pad bytes>"
                elif spec.name == "?":
                    debugstr = "<unknown>"
                else:
                    if spec._count == 1:
                        val = val[0]
                    if repeat > 1:
                        debugstr = f"self.{spec.name:24s} += {val}"
                        if idx == 0:
                            values[spec.name] = []
                        values[spec.name].append(val)
                    else:
                        debugstr = f"self.{spec.name:24s} = {val}"
                        values[spec.name] = val

                if not disable_logger:
                    logger.debug(
                        f"offset {offset:02d}: {as_hex(data[offset:offset+spec._size]):5s} → {debugstr}"
                    )
                offset += spec._size

            if spec.convert_from_data is not None:
                values[spec.name] = spec.convert_from_data(values[spec.name])

        # if we don't have an object, construct an attr class with the spec
        # names (skipping padding/unknown). This makes printing and inspecting
        # results a lot saner.
        if obj is None:
            # names with a single underscore are kept (but drop the underscore
            # for the constructor)
            # names with a double underscore are ignored
            public_names = list(filter(lambda k: not k.startswith("__"), values.keys()))
            vals = {n.lstrip("_"): values[n] for n in public_names}

            if isinstance(result_class, str):
                c = attr.make_class(result_class, attrs=public_names)
                # private fields in attr drop the leading underscore in the
                # constructor
                obj = c(**vals)
            else:
                # Instantiate the given directly
                obj = result_class(**vals)
        else:
            for name, value in values.items():
                setattr(obj, name, value)

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
