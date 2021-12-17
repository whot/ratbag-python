#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import enum
import fcntl
import logging
import pathlib
import os

import hidtools.hid

import gi
from gi.repository import GObject

import ratbag

logger = logging.getLogger(__name__)

class Message(GObject.Object):
    """
    A message sent to the device or received from the device.
    """

    SUBTYPE = ""

    class Direction(enum.Enum):
        """Message direction"""

        RX = enum.auto()
        TX = enum.auto()
        IOC = enum.auto()

    def __init__(self, bytes, direction=Direction.TX):
        self.direction = direction
        self.bytes = bytes
        self.msgtype = type(self).NAME
        self.subtype = type(self).SUBTYPE

    def __str__(self):
        bytestr = " ".join(f"{b:02x}" for b in self.bytes)
        if self.subtype:
            subtype = f" {self.subtype}"
        else:
            subtype = ""
        return f"{self.msgtype}{subtype} {self.direction.name} ({len(self.bytes)}): {bytestr}"


class Rodent(GObject.Object):
    """
    An class abstracting a physical device, connected via a non-blocking
    file descriptor. This class exists so we have a default interface for
    communicating with the device that we can hook into for logging and
    others.

    :param path: the path to the physical device

    .. note:: The name Rodent was chosen to avoid confusion with :class:`ratbag.Device`.

    .. attribute:: name

        The device's name (as advertized by the device itself)

    .. attribute:: path

        The device's path we're reading to/writing from

    .. attribute:: report_descriptor

        The bytes for this hidraw device's report descriptor (if this device
        is a hidraw device, otherwise ``None``)

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

        def __init__(self, bytes):
            super().__init__(bytes, direction=Message.Direction.TX)

    class Reply(Message):
        """:meta private:"""

        NAME = "fd"

        def __init__(self, bytes):
            super().__init__(bytes, direction=Message.Direction.RX)

    class IoctlCommand(Message):
        """:meta private:"""

        NAME = "ioctl"

        def __init__(self, name, bytes):
            super().__init__(bytes, direction=Message.Direction.TX)
            self.subtype = name

    class IoctlReply(Message):
        """:meta private:"""

        NAME = "ioctl"

        def __init__(self, name, bytes):
            super().__init__(bytes, direction=Message.Direction.RX)
            self.subtype = name

    @classmethod
    def from_device(cls, device):
        """
        A simplification for drivers. If the given device is already a
        pre-setup device (from a recorder), this function returns that device.
        Otherwise, this function returns a :class:`ratbag.drivers.Rodent`
        instance for the given device path.
        """
        if isinstance(device, str) or isinstance(device, pathlib.Path):
            return Rodent(device)
        else:
            return device

    def __init__(self, path):
        GObject.Object.__init__(self)
        self.path = path

        info = ratbag.util.load_device_info(path)
        self.name = info["name"] or "Unnamed device"
        self.report_descriptor = info.get("report_descriptor", None)
        if self.report_descriptor is not None:
            self._rdesc = hidtools.hid.ReportDescriptor.from_bytes(self.report_descriptor)

        self._fd = open(path, "r+b", buffering=0)
        os.set_blocking(self._fd.fileno(), False)

    def start(self):
        """
        Start parsing data from the device.
        """
        pass

    def send(self, bytes):
        """
        Send data to the device
        """
        logger.debug(Rodent.Request(bytes))
        self.emit("data-to-device", bytes)
        self._fd.write(bytes)

    def recv(self):
        """
        Receive data from the device
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

    def hid_get_feature(self, report_id):
        report = self._rdesc.feature_reports[report_id]
        rsize = report.size
        buf = bytearray([report_id & 0xff]) + bytearray(rsize - 1)
        logger.debug(Rodent.IoctlCommand("HIDIOCGFEATURE", buf))
        self.emit("ioctl-command", "HIDIOCGFEATURE", buf)

        fcntl.ioctl(self._fd.fileno(), _IOC_HIDIOCGFEATURE(None, len(buf)), buf)
        logger.debug(Rodent.IoctlReply("HIDIOCGFEATURE", buf))
        self.emit("ioctl-reply", "HIDIOCGFEATURE", buf)
        return list(buf)  # Note: first byte is report ID


    def hid_set_feature(self, report_id, data):
        report = self._rdesc.feature_reports[report_id]
        assert data[0] == report_id
        buf = bytearray(data)

        logger.debug(Rodent.IoctlCommand("HIDIOCSFEATURE", buf))
        self.emit("ioctl-command", "HIDIOCSFEATURE", buf)

        sz = fcntl.ioctl(self._fd.fileno(), _IOC_HIDIOCSFEATURE(None, len(buf)), buf)
        if sz != len(data):
            raise OSError('Failed to write data: {data} - bytes written: {sz}')

    def connect_to_recorder(self, recorder):
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
            def probe(self, device, info, config):
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

    def add_recorder(self, recorder):
        """
        Instruct the driver to add ``recorder`` to log driver communication to
        the device. It is up to the driver to determine what communication is
        notable enough to be recorder for later replay.
        """
        self.recorders.append(recorder)

    def probe(self, device, device_info={}, config={}):
        """
        Probe the device for information. On success, the driver will create a
        :class:`ratbag.Device` with at least one profile and the appropriate
        number of buttons/leds/resolutions.

        A caller should subscribe to the ``device-added`` signal before
        calling this function.

        If ``device`` is a string or a ``pathlib.Path`` object, the driver
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




# ioctl handling is copied from hid-tools
# We only need a small subset of it but we do need to hook into the transport
# later, so copying it was easier than modifying hidtools
def _ioctl(fd, EVIOC, code, return_type, buf=None):
    size = struct.calcsize(return_type)
    if buf is None:
        buf = size * '\x00'
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
    return ((dir << _IOC_DIRSHIFT) |
            (ord(type) << _IOC_TYPESHIFT) |
            (nr << _IOC_NRSHIFT) |
            (size << _IOC_SIZESHIFT))


# define _IOR(type,nr,size)	_IOC(_IOC_READ,(type),(nr),(_IOC_TYPECHECK(size)))
def _IOR(type, nr, size):
    return _IOC(_IOC_READ, type, nr, size)


# define _IOW(type,nr,size)	_IOC(_IOC_WRITE,(type),(nr),(_IOC_TYPECHECK(size)))
def _IOW(type, nr, size):
    return _IOC(_IOC_WRITE, type, nr, size)


# define HIDIOCGFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)
def _IOC_HIDIOCGFEATURE(none, len):
    return _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x07, len)


def _HIDIOCGFEATURE(fd, report_id, rsize):
    """ get feature report """
    assert report_id <= 255 and report_id > -1

    # rsize has the report length in it
    buf = bytearray([report_id & 0xff]) + bytearray(rsize - 1)
    fcntl.ioctl(fd, _IOC_HIDIOCGFEATURE(None, len(buf)), buf)
    return list(buf)  # Note: first byte is report ID


# define HIDIOCSFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
def _IOC_HIDIOCSFEATURE(none, len):
    return _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x06, len)


def _HIDIOCSFEATURE(fd, data):
    """ set feature report """

    buf = bytearray(data)
    sz = fcntl.ioctl(fd, _IOC_HIDIOCSFEATURE(None, len(buf)), buf)
    return sz
