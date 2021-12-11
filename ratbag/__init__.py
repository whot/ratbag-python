#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import enum
import logging
import os
import pyudev
import select

import gi
from gi.repository import GObject

import ratbag.util

logger = logging.getLogger(__name__)


class UnsupportedDeviceError(Exception):
    """
    Error indicating that the device is not supported.

    .. attribute:: path

       The device path that failed

    .. attribute:: name

       The device name that failed

    """

    def __init__(self, name, path):
        self.name = name
        self.path = path


class SomethingIsMissingError(Exception):
    """
    Error indicating that the device is missing something that we require for
    it to work.

    .. attribute:: path

       The device path that failed

    .. attribute:: name

       The device name that failed

    .. attribute:: thing

       A string explaining the thing that is missing
    """

    def __init__(self, name, path, thing):
        self.name = name
        self.path = path
        self.thing = thing


class ConfigError(Exception):
    """
    .. attribute:: message

        The error message
    """

    def __init__(self, message):
        self.message = message


class ProtocolError(Exception):
    """
    Error indicating that the communication with the device encountered an
    error

    .. attribute:: path

       The device path that failed

    .. attribute:: name

       The device name that failed

    .. attribute:: conversation

       A list of byte arrays with the context of the failed conversation with
       the device.

    """

    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.conversation = None


class Message(GObject.Object):
    """
    A message sent to the device or received from the device.
    """

    class Direction(enum.Enum):
        """Message direction"""

        RX = enum.auto()
        TX = enum.auto()

    def __init__(self, bytes, direction=Direction.TX):
        self.direction = direction
        self.bytes = bytes
        self.msgtype = type(self).NAME

    def __str__(self):
        bytestr = " ".join(f"{b:02x}" for b in self.bytes)
        return f"{self.msgtype} {self.direction.name} ({len(self.bytes)}): {bytestr}"


class Ratbag(GObject.Object):
    """
    An instance managing one or more ratbag devices. This is the entry point
    for all ratbag clients. The ratbag object can be instantiated with a
    static device path (or several) or, the default, support for udev. In the
    latter case, devices are added/removed as they appear.

    Where static device paths are given, the device must be present and
    removal of that device will not re-add this device in the future.

    :class:`ratbag.Ratbag` requires a GLib mainloop.

    :param config: a dictionary with configuration information

    Configuration items:

    - ``device-paths``: a list of device paths to initialize (if any)




    GObject Signals:

    - ``device-added`` Notifcation that a new :class:`ratbag.Device` was added
    - ``device-removed`` Notifcation that the :class:`ratbag.Device` was removed

    """

    __gsignals__ = {
        "device-added": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "device-removed": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (GObject.TYPE_PYOBJECT,),
        ),
    }

    def __init__(self, config):
        super().__init__()
        self._devices = []
        self._config = config

    def start(self):
        """
        Add the devices and/or start monitoring udev for new devices.
        """
        paths = self._config.get("device-paths", None)
        if not paths:
            logger.debug("Installing udev monitor")
            self._install_udev_monitor()
            paths = util.find_hidraw_devices()
        for path in paths:
            self._add_device(path=path)

        for emulator in self._config.get("emulators", []):
            driver = self._load_driver_by_name(emulator.driver, {}, {})
            driver.probe(emulator)

    def _install_udev_monitor(self):
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by(subsystem="hidraw")

        def udev_monitor_callback(source, condition, monitor):
            device = monitor.poll(0)
            while device:
                logger.debug(f"udev monitor: {device.action} {device.device_node}")
                if device.action == "add":
                    self._add_device(device.device_node)
                device = monitor.poll(0)
            return True  # keep the callback

        GObject.io_add_watch(monitor, GObject.IO_IN, udev_monitor_callback, monitor)
        monitor.start()

    def _add_device(self, path):
        try:

            def cb_device_disconnected(device, ratbag):
                logger.info(f"disconnected {device.name}")
                self._devices.remove(device)
                self.emit("device-removed", device)

            def cb_device_added(driver, device):
                self._devices.append(device)
                device.connect("disconnected", cb_device_disconnected)
                self.emit("device-added", device)

            driver = self._find_driver(path)

            # If we're recording, tell the driver about the logger. Eventually
            # we may have multiple loggers depending on what we need to know
            # but for now we just have a simple YAML logger for all data
            # in/out
            for rec in self._config.get("recorders", []):
                driver.add_recorder(rec)

            driver.connect("device-added", cb_device_added)
            driver.probe(path)
        except UnsupportedDeviceError as e:
            logger.info(f"Skipping unsupported device {e.name} ({e.path})")
        except SomethingIsMissingError as e:
            logger.info(f"Skipping device {e.name} ({e.path}): missing {e.thing}")
        except PermissionError as e:
            logger.error(f"Unable to open device at {path}: {e}")

    def _find_driver(self, path):
        """
        Load the driver assigned to the bus/VID/PID match. If a matching
        driver is found, that driver's :func:`LOAD_DRIVER_FUNC` is called with
        the *static* information about the device.

        :return: a instance of :class:`ratbag.drivers.Driver`
        """
        info = util.load_device_info(path)
        name = info.get("name", None)
        bus = info.get("bus", None)
        vid = info.get("vid", None)
        pid = info.get("pid", None)
        match = f"{bus}:{vid:04x}:{pid:04x}"

        # FIXME: this needs to use the install path
        datafiles = util.load_data_files("data")
        try:
            datafile = datafiles[match]
        except KeyError:
            raise UnsupportedDeviceError(name, path)

        # Flatten the config file to a dict of device info and
        # a dict of driver-specific configurations
        driver_name = datafile["Device"]["Driver"]
        device_info = {k: v for k, v in datafile["Device"].items()}
        del device_info["Driver"]
        del device_info["DeviceMatch"]
        try:
            driver_config = {k: v for k, v in datafile[f"Driver/{driver_name}"].items()}
        except KeyError:
            # not all drivers have custom options
            driver_config = {}

        return self._load_driver_by_name(driver_name, device_info, driver_config)

    def _load_driver_by_name(self, driver_name, device_info, driver_config):
        # Import ratbag.drivers.foo and call load_driver() to instantiate the
        # driver.
        try:
            import importlib

            logger.debug(f"Loading driver {driver_name}")
            module = importlib.import_module(f"ratbag.drivers.{driver_name}")
        except ImportError as e:
            logger.error(f"Driver {driver_name} failed to load: {e}")
            return None

        try:
            load_driver_func = getattr(module, ratbag.drivers.Driver.DRIVER_LOAD_FUNC)
        except AttributeError as e:
            logger.error(
                f"Bug: driver {driver_name} does not have '{ratbag.drivers.Driver.DRIVER_LOAD_FUNC}()'"
            )
            return None
        return load_driver_func(driver_name, device_info, driver_config)


class Recorder(GObject.Object):
    """
    Recorder can be added to a :class:`ratbag.Driver` to log data between the
    host and the device, see :func:`ratbag.Driver.add_recorder`

    :param config: A dictionary with logger-specific data to initialize
    """

    def __init__(self, config={}):
        GObject.Object.__init__(self)

    def init(self, info={}):
        """
        Initialize the logger for the given device.

        :param info: a dictionary of extra logging keys
        """
        pass

    def log_rx(self, data):
        """
        Log data received from the device
        """
        pass

    def log_tx(self, data):
        """
        Log data sent to the device
        """
        pass


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

    class Request(ratbag.Message):
        """:meta private:"""

        NAME = "fd"

        def __init__(self, bytes):
            super().__init__(bytes, direction=ratbag.Message.Direction.TX)

    class Reply(ratbag.Message):
        """:meta private:"""

        NAME = "fd"

        def __init__(self, bytes):
            super().__init__(bytes, direction=ratbag.Message.Direction.RX)

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


class Device(GObject.Object):
    """
    A device as exposed to Ratbag clients. A driver implementation must not
    expose a :class:`ratbag.Device` until it is fully setup and ready to be
    accessed by the client. Usually this means not sending the
    :class:`ratbag.Driver`::``device-added`` signal until the device is
    finalized.

    A :class:`ratbag.Device` may be backed by one or more
    :class:`ratbag.Rodent` instances, this is an implementation detail of the
    driver.

    GObject Signals:

    - ``disconnected``: this device has been disconnected
    - ``commit``: commit the current state to the physical device. This signal
      is used by drivers.
    - ``resync``: callers should re-sync the state of the device
    """

    __gsignals__ = {
        "disconnected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "commit": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "resync": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, driver, path, name):
        GObject.Object.__init__(self)
        self.driver = driver
        self.path = path
        self.name = name
        self.profiles = {}
        self._driver = driver

    def commit(self):
        self.emit("commit")

    def add_profile(self, profile):
        """
        Add the profile to the device.
        """
        self.profiles[profile.index] = profile

    def dump(self):
        p = "  " + "\n  ".join([p.dump() for p in self.profiles.values()])
        return (
            f"Device: {self.name} {self.path}\n"
            f"  Profiles: {len(self.profiles)}\n"
            f"{p}"
        )


class Feature(GObject.Object):
    """
    Base class for all device features, including profiles. This is a
    convenience class only to avoid re-implementation of common properties.

    :attr device: The device associated with this feature
    :attr index: the 0-based index of this feature (e.g. button 0, profile 1, etc.)
    """

    def __init__(self, device, index):
        assert index >= 0
        GObject.Object.__init__(self)
        self.device = device
        self._index = index
        logger.debug(
            f"{self.device.name}: creating {type(self).__name__} with index {self.index}"
        )

    @GObject.Property
    def index(self):
        """
        The 0-based device index of this feature. Indices are counted from the
        parent feature up, i.e. the first resolution of a profile 1 is
        resolution 0, the first resolution of profile 2 also has an index of
        0.
        """

        return self._index

    @GObject.Property
    def dirty(self):
        """
        `True` if changes are uncommited. Connect to ``notify::dirty`` to receive changes.
        """
        return self._dirty

    @dirty.setter
    def dirty(self, is_dirty):
        if self._dirty != is_dirty:
            self._dirty = is_dirty
            self.notify("dirty")


class Profile(Feature):
    __gsignals__ = {
        "active": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, device, index, name=None):
        super().__init__(device, index)
        self.name = f"Unnamed {index}" if name is None else name
        self.buttons = {}
        self.resolutions = {}
        self.leds = {}

    def _cb_dirty(self, feature, dirty):
        if dirty:
            self.dirty = True

    def add_button(self, button):
        self.buttons[button.index] = button
        button.connect("notify::dirty", self._cb_dirty)

    def add_resolution(self, resolution):
        self.resolutions[resolution.index] = resolution
        resolution.connect("notify::dirty", self._cb_dirty)

    def add_led(self, led):
        self.leds[led.index] = led
        led.connect("notify::dirty", self._cb_dirty)

    def dump(self):
        res = "    " + "\n    ".join([r.dump() for r in self.resolutions.values()])
        return f"Profile {self.index}: {self.name}\n" f"{res}"


class Resolution(Feature):
    __gsignals__ = {
        "active": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, profile, index, resolution):
        super().__init__(profile.device, index)
        self.profile = profile
        self.resolution = resolution

    def dump(self):
        return f"Resolution {self.index}: {self.resolution}"


class Button(Feature):
    def __init__(self, profile, index):
        super().__init__(profile.device, index)
        self.profile = profile


class Led(Feature):
    def __init__(self, profile, index):
        super().__init__(profile.device, index)
        self.profile = profile
