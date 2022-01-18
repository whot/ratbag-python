#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import attr
import enum
import fcntl
import logging
import pathlib
import pyudev
import os
import select
import struct

from typing import Any, Dict, List, Optional, Tuple, Union

from gi.repository import GObject

import ratbag

logger = logging.getLogger(__name__)


class Message(GObject.Object):
    """
    A message sent to the device or received from the device. This object
    exists to standardize logging attempts. Drivers should, where possible,
    re-use the existing messages.

    Messages are usually logged as ``type subtype direction data``
    """

    SUBTYPE = ""
    """
    The subtype of this message. Used e.g. by ioctls to specify which ioctl
    was invoked.
    """

    class Direction(enum.Enum):
        """Message direction"""

        RX = enum.auto()
        """Message received from the device"""
        TX = enum.auto()
        """Message sent to the device"""
        IOC = enum.auto()
        """An ioctl invocation on the device"""

    def __init__(self, bytes: bytes, direction: Direction = Direction.TX):
        self.direction = direction
        self.bytes = bytes
        self.msgtype = type(self).NAME
        self.subtype = type(self).SUBTYPE

    def __str__(self) -> str:
        bytestr = " ".join(f"{b:02x}" for b in self.bytes)
        if self.subtype:
            subtype = f" {self.subtype}"
        else:
            subtype = ""
        return f"{self.msgtype}{subtype} {self.direction.name} ({len(self.bytes)}): {bytestr}"


@attr.s
class DeviceInfo:
    """
    Information about a device. This is information collected about a device
    that can help in picking which driver to load, listing the device for the
    user, etc.

    Information collected is (usually) done without opening the device.
    """

    path: pathlib.Path = attr.ib()
    syspath: pathlib.Path = attr.ib()
    name: str = attr.ib(default="Unnamed device")
    bus: str = attr.ib(
        default="usb", validator=attr.validators.in_(("bluetooth", "usb"))
    )
    vid: int = attr.ib(default=0)
    pid: int = attr.ib(default=0)
    report_descriptor: Optional[bytes] = attr.ib(default=None)

    @property
    def model(self):
        #  change this when we have a need for it, i.e. when we start
        #  supporting devices where the USB ID gets reused. Until then we can
        #  just hardcode the version to 0
        version = 0
        return f"{self.bus}:{self.vid:04x}:{self.pid:04x}:{version}"

    @staticmethod
    def from_path(path: pathlib.Path) -> "DeviceInfo":
        context = pyudev.Context()
        device = pyudev.Devices.from_device_file(context, path)

        def find_prop(device, prop: str) -> Optional[str]:
            try:
                return device.properties[prop]
            except KeyError:
                try:
                    return find_prop(next(device.ancestors), prop)
                except StopIteration:
                    return None

        vid = int(find_prop(device, "ID_VENDOR_ID") or 0, 16)  # type: ignore
        pid = int(find_prop(device, "ID_MODEL_ID") or 0, 16)  # type: ignore
        name = (
            find_prop(device, "HID_NAME") or f"Unnamed HID device {vid:04x}:{pid:04x}"
        )
        bus = find_prop(device, "ID_BUS")
        assert bus
        syspath = device.sys_path

        def find_report_descriptor(device) -> Optional[bytes]:
            try:
                with open(
                    pathlib.Path(device.sys_path) / "report_descriptor", "rb"
                ) as fd:
                    return fd.read()
            except FileNotFoundError:
                try:
                    return find_report_descriptor(next(device.ancestors))
                except StopIteration:
                    return None

        report_descriptor = find_report_descriptor(device)

        return DeviceInfo(
            path=path,
            syspath=syspath,
            name=name,
            bus=bus,
            vid=vid,
            pid=pid,
            report_descriptor=report_descriptor,
        )


class Rodent(GObject.Object):
    """
    An class abstracting a physical device, connected via a non-blocking
    file descriptor. This class exists so we have a default interface for
    communicating with the device that we can hook into for logging and
    others.

    See :meth:`from_device` for the most convenient way to create a new Rodent
    object.

    :param path: the path to the physical device

    .. note:: The name Rodent was chosen to avoid confusion with :class:`ratbag.Device`.

    GObject Signals:
        - ``data-to-device``, ``data-from-device``: the ``bytes`` that have
          been written to or read from the device.
        - ``ioctl-command``: an ioctl has been called on the device with the
          given ioctl name and the data in ``bytes``
        - ``ioctl-reply``: an ioctl has returned data in ``bytes``

    These signals are primarily used by recorders, there should be no need to
    handle those signals in other parts of the implementation.
    """

    __gsignals__ = {
        "data-to-device": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (GObject.TYPE_PYOBJECT,),
        ),
        "data-from-device": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (GObject.TYPE_PYOBJECT,),
        ),
        "ioctl-command": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            # ioctl name (string), data (bytes)
            (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT),
        ),
        "ioctl-reply": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            # ioctl name (string), data (bytes)
            (GObject.TYPE_PYOBJECT, GObject.TYPE_PYOBJECT),
        ),
    }

    class Request(Message):
        """:meta private:"""

        NAME = "fd"

        def __init__(self, bytes: bytes):
            super().__init__(bytes, direction=Message.Direction.TX)

    class Reply(Message):
        """:meta private:"""

        NAME = "fd"

        def __init__(self, bytes: bytes):
            super().__init__(bytes, direction=Message.Direction.RX)

    class IoctlCommand(Message):
        """:meta private:"""

        NAME = "ioctl"

        def __init__(self, name: str, bytes: bytes):
            super().__init__(bytes, direction=Message.Direction.TX)
            self.subtype = name

    class IoctlReply(Message):
        """:meta private:"""

        NAME = "ioctl"

        def __init__(self, name: str, bytes: bytes):
            super().__init__(bytes, direction=Message.Direction.RX)
            self.subtype = name

    @classmethod
    def from_device_info(cls, info: DeviceInfo) -> "ratbag.drivers.Rodent":
        r = Rodent(info)
        r.open()
        return r

    @classmethod
    def from_device(cls, device: Union[pathlib.Path, "ratbag.drivers.Rodent"]):
        """
        A simplification for drivers. If the given device is already a
        pre-setup device (from a recorder), this function returns that device.
        Otherwise, this function returns a :class:`ratbag.drivers.Rodent`
        instance for the given device path.
        """
        if isinstance(device, pathlib.Path):
            info = DeviceInfo.from_path(device)
            return Rodent(info)
        else:
            return device

    def __init__(self, info: DeviceInfo):
        GObject.Object.__init__(self)

        self._info = info
        if info.report_descriptor:
            self._rdesc = ratbag.hid.ReportDescriptor.from_bytes(info.report_descriptor)

    def open(self):
        self._fd = open(self.path, "r+b", buffering=0)
        os.set_blocking(self._fd.fileno(), False)

    @property
    def name(self):
        return self._info.name

    @property
    def model(self):
        return self._info.model

    @property
    def path(self):
        return self._info.path

    @property
    def report_descriptor(self):
        return self._info.report_descriptor

    @property
    def report_ids(self) -> Dict[str, Tuple[int, ...]]:
        """
        A dictionary containg the list each of "feature", "input" and "output"
        report IDs. For devices without a report descriptor, each list is
        empty.
        """
        ids: Dict[str, Tuple[int, ...]] = {
            "input": tuple(),
            "output": tuple(),
            "feature": tuple(),
        }
        if self.report_descriptor is not None:
            ids["input"] = tuple([r.report_id for r in self._rdesc.input_reports])
            ids["output"] = tuple([r.report_id for r in self._rdesc.output_reports])
            ids["feature"] = tuple([r.report_id for r in self._rdesc.feature_reports])
        return ids

    def start(self) -> None:
        """
        Start parsing data from the device.
        """
        pass

    def send(self, bytes: bytes) -> None:
        """
        Send data to the device
        """
        logger.debug(Rodent.Request(bytes))
        self.emit("data-to-device", bytes)
        self._fd.write(bytes)

    def recv(self) -> Optional[bytes]:
        """
        Receive data from the device. This method waits synchronously for the data.
        """
        poll = select.poll()
        poll.register(self._fd, select.POLLIN)

        while True:
            fds = poll.poll(1000)
            if not fds:
                continue  # block until we get an answer or error

            data = self._fd.read()
            logger.debug(Rodent.Reply(data))
            self.emit("data-from-device", data)
            return data

        return None

    def hid_get_feature(self, report_id: int) -> bytes:
        """
        Return a list of bytes as returned by this HID GetFeature request
        """
        report = self._rdesc.feature_reports[report_id]
        rsize = report.size
        buf = bytearray([report_id & 0xFF]) + bytearray(rsize - 1)
        logger.debug(Rodent.IoctlCommand("HIDIOCGFEATURE", buf))
        self.emit("ioctl-command", "HIDIOCGFEATURE", buf)

        fcntl.ioctl(self._fd.fileno(), _IOC_HIDIOCGFEATURE(None, len(buf)), buf)
        logger.debug(Rodent.IoctlReply("HIDIOCGFEATURE", buf))
        self.emit("ioctl-reply", "HIDIOCGFEATURE", buf)
        return bytes(buf)  # Note: first byte is report ID

    def hid_set_feature(self, report_id: int, data: bytes) -> None:
        """
        Issue a HID SetFeature request for the given report ID with the given
        data.

        .. note:: the first element of data must be the report_id
        """
        assert report_id in self._rdesc.feature_reports
        assert data[0] == report_id
        buf = bytearray(data)

        logger.debug(Rodent.IoctlCommand("HIDIOCSFEATURE", buf))
        self.emit("ioctl-command", "HIDIOCSFEATURE", buf)

        sz = fcntl.ioctl(self._fd.fileno(), _IOC_HIDIOCSFEATURE(None, len(buf)), buf)
        if sz != len(data):
            raise OSError("Failed to write data: {data} - bytes written: {sz}")

    def connect_to_recorder(self, recorder: ratbag.Recorder) -> None:
        """
        Connect this device to the given recorder. This is a convenience
        method to simplify drivers.
        """

        def cb_logtx(device, data):
            recorder.log_tx(data)

        def cb_logrx(device, data):
            recorder.log_rx(data)

        def cb_ioctl_tx(device, ioctl_name, bytes):
            recorder.log_ioctl_tx(ioctl_name, bytes)

        def cb_ioctl_rx(device, ioctl_name, bytes):
            recorder.log_ioctl_rx(ioctl_name, bytes)

        self.connect("data-from-device", cb_logrx)
        self.connect("data-to-device", cb_logtx)
        self.connect("ioctl-command", cb_ioctl_tx)
        self.connect("ioctl-reply", cb_ioctl_rx)


class Driver(GObject.Object):
    """
    The parent class for all driver implementations. See
    ``ratbag/drivers/drivername.py`` for the implementation of each driver
    itself.

    A driver **must** implement the :func:`DRIVER_LOAD_FUNC` function, it is
    the entry point for ratbag to instantiate the driver for the device.
    """

    DRIVER_LOAD_FUNC = "load_driver"
    """
    The name of the function to instantiate a driver. A driver file must
    contain at least the following code: ::

        class MyDriver(ratbag.Driver):
            def probe(self, rodent, config):
                pass

        def load_driver(driver_name=""):
            return myDriver()

    GObject Signals:

      - ``device-added``: emitted for each :class:`ratbag.Device` that was
        added during :meth:`probe`
    """

    __gsignals__ = {
        "failed": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "success": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "device-added": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(self):
        GObject.Object.__init__(self)
        self.name = None
        self.recorders = []
        self.connect("device-added", self._device_sanity_check)

    def add_recorder(self, recorder: ratbag.Recorder) -> None:
        """
        Instruct the driver to add ``recorder`` to log driver communication to
        the device. It is up to the driver to determine what communication is
        notable enough to be recorder for later replay.
        """
        self.recorders.append(recorder)

    def probe(
        self,
        rodent: "ratbag.drivers.Rodent",
        config: Dict[str, Any] = {},
    ) -> None:
        """
        Probe the device for information. On success, the driver will create a
        :class:`ratbag.Device` with at least one profile and the appropriate
        number of buttons/leds/resolutions and emit the ``device-added``
        signal for that device.

        A caller should subscribe to the ``device-added`` signal before
        calling this function.

        If ``device`` is a ``pathlib.Path`` object, the driver
        creates initializes for the device at that path. Otherwise, ``device``
        is used as-is as backing device instance. This is used when emulating
        devices - note that the exact requirements on the device behavior may
        differ between drivers.

        Completion of this function without an exception counts as success.

        :param device: The path to the device or a fully initialized instance
                       representing a device
        :param device_info: Static information about the device from external
                            sources (system, data files, etc).
        :param config: Driver-specific device configuration (e.g. quirks).
        """
        raise NotImplementedError("This function must be implemented by the driver")

    def _device_sanity_check(
        self, driver: "ratbag.drivers.Driver", device: ratbag.Device
    ):
        # Let the parent class do some basic sanity checks
        assert device.name is not None
        assert device.driver is not None
        assert len(device.profiles) >= 1
        # We must not skip an index
        assert None not in device.profiles
        nbuttons = len(device.profiles[0].buttons)
        nres = len(device.profiles[0].resolutions)
        nleds = len(device.profiles[0].leds)
        # We must have at least *something* to configure
        assert any([count > 0 for count in [nbuttons, nres, nleds]])
        # We don't support different numbers of features on profiles, they all
        # must have the same count
        for p in device.profiles:
            assert nbuttons == len(p.buttons)
            assert nres == len(p.resolutions)
            assert nleds == len(p.leds)


# ioctl handling is copied from hid-tools
# We only need a small subset of it but we do need to hook into the transport
# later, so copying it was easier than modifying hidtools
def _ioctl(fd, EVIOC, code, return_type, buf=None):
    size = struct.calcsize(return_type)
    if buf is None:
        buf = size * "\x00"
    abs = fcntl.ioctl(fd, EVIOC(code, size), buf)
    return struct.unpack(return_type, abs)


# extracted from <asm-generic/ioctl.h>
_IOC_WRITE = 1
_IOC_READ = 2

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS


# define _IOC(dir,type,nr,size) \
# 	(((dir)  << _IOC_DIRSHIFT) | \
# 	 ((type) << _IOC_TYPESHIFT) | \
# 	 ((nr)   << _IOC_NRSHIFT) | \
# 	 ((size) << _IOC_SIZESHIFT))
def _IOC(dir, type, nr, size):
    return (
        (dir << _IOC_DIRSHIFT)
        | (ord(type) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


# define _IOR(type,nr,size)	_IOC(_IOC_READ,(type),(nr),(_IOC_TYPECHECK(size)))
def _IOR(type, nr, size):
    return _IOC(_IOC_READ, type, nr, size)


# define _IOW(type,nr,size)	_IOC(_IOC_WRITE,(type),(nr),(_IOC_TYPECHECK(size)))
def _IOW(type, nr, size):
    return _IOC(_IOC_WRITE, type, nr, size)


# define HIDIOCGFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)
def _IOC_HIDIOCGFEATURE(none, len):
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x07, len)


def _HIDIOCGFEATURE(fd, report_id, rsize):
    """get feature report"""
    assert report_id <= 255 and report_id > -1

    # rsize has the report length in it
    buf = bytearray([report_id & 0xFF]) + bytearray(rsize - 1)
    fcntl.ioctl(fd, _IOC_HIDIOCGFEATURE(None, len(buf)), buf)
    return list(buf)  # Note: first byte is report ID


# define HIDIOCSFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
def _IOC_HIDIOCSFEATURE(none, len):
    return _IOC(_IOC_WRITE | _IOC_READ, "H", 0x06, len)


def _HIDIOCSFEATURE(fd, data):
    """set feature report"""

    buf = bytearray(data)
    sz = fcntl.ioctl(fd, _IOC_HIDIOCSFEATURE(None, len(buf)), buf)
    return sz
