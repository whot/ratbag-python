#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

import enum

import gi
from gi.repository import GObject


class Message(GObject.Object):
    """
    A message sent to the device or received from the device.
    """

    class Direction(enum.Enum):
        """Message direction"""

        RX = enum.auto()
        TX = enum.auto()
        IOC = enum.auto()

    def __init__(self, bytes, direction=Direction.TX):
        self.direction = direction
        self.bytes = bytes
        self.msgtype = type(self).NAME

    def __str__(self):
        bytestr = " ".join(f"{b:02x}" for b in self.bytes)
        return f"{self.msgtype} {self.direction.name} ({len(self.bytes)}): {bytestr}"


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

    def __init__(self, path):
        GObject.Object.__init__(self)
        self.name = "Unnamed device"
        self.path = path

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
            ... implementation of the driver

        def load_driver(driver_name="", device_info={}, driver_config={}):
            # checks and balances
            return myDriver()

    The ``device_info`` and ``driver_config`` arguments are static information
    about the device to be probed later, i.e. it comes from a data file, not
    the device itself.

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

    def add_recorder(self, recorder):
        """
        Instruct the driver to add ``recorder`` to log driver communication to
        the device. It is up to the driver to determine what communication is
        notable enough to be recorder for later replay.
        """
        logger.warning(
            f"Recorder {cls.__name__} requested but driver does not implement this functionality"
        )

    def probe(self, device):
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
        """
        raise NotImplementedError("This function must be implemented by the driver")
