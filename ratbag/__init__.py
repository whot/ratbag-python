#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import enum
import logging
import pyudev

from pathlib import Path

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

    .. attribute:: message

       An explanatory message

    .. attribute:: conversation

       A list of byte arrays with the context of the failed conversation with
       the device, if any.

    """

    def __init__(self, message=None, name=None, path=None):
        self.name = name
        self.path = path
        self.message = message
        self.conversation = []


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
    - ``emulators``: a list of :class:`ratbag.emulator.YamlDevice` or similar
      to emulate a device
    - ``recorders``: a list of :class:`ratbag.recorder.SimpleRecorder` or
      similar to record device interactions

    GObject Signals:

    - ``device-added`` Notification that a new :class:`ratbag.Device` was added
    - ``device-removed`` Notification that the :class:`ratbag.Device` was removed

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
            driver = self._load_driver_by_name(emulator.driver)
            driver.probe(emulator, {}, {})

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
            info = ratbag.util.load_device_info(path)
            driver, config = self._find_driver(path, info)

            def cb_device_disconnected(device, ratbag):
                logger.info(f"disconnected {device.name}")
                self._devices.remove(device)
                self.emit("device-removed", device)

            def cb_device_added(driver, device):
                self._devices.append(device)
                device.connect("disconnected", cb_device_disconnected)
                self.emit("device-added", device)

            # If we're recording, tell the driver about the logger. Eventually
            # we may have multiple loggers depending on what we need to know
            # but for now we just have a simple YAML logger for all data
            # in/out
            for rec in self._config.get("recorders", []):
                driver.add_recorder(rec)

            driver.connect("device-added", cb_device_added)
            driver.probe(path, info, config)
        except UnsupportedDeviceError as e:
            logger.info(f"Skipping unsupported device {e.name} ({e.path})")
        except SomethingIsMissingError as e:
            logger.info(f"Skipping device {e.name} ({e.path}): missing {e.thing}")
        except ProtocolError as e:
            logger.info(
                f"Skipping device {e.name} ({e.path}): protocol error: {e.message}"
            )
        except PermissionError as e:
            logger.error(f"Unable to open device at {path}: {e}")

    def _find_driver(self, device_path, info):
        """
        Load the driver assigned to the bus/VID/PID match. If a matching
        driver is found, that driver's :func:`LOAD_DRIVER_FUNC` is called with
        the *static* information about the device.

        :param device_path: the path to the device node
        :param info: a dict of various info collected for this device
        :return: a instance of :class:`ratbag.drivers.Driver`
        """
        name = info.get("name", None)
        bus = info.get("bus", None)
        vid = info.get("vid", None)
        pid = info.get("pid", None)

        match = f"{bus}:{vid:04x}:{pid:04x}"
        # FIXME: this needs to use the install path
        path = Path("data")
        if not path.exists():
            path = "/usr/share/libratbag/"
            if not path("data"):
                raise NotImplementedError(
                    "Missing data files: none in /usr/share/libratbag, none in $PWD/data"
                )
        datafiles = util.load_data_files(path)
        try:
            datafile = datafiles[match]
        except KeyError:
            raise UnsupportedDeviceError(name, path)

        # Flatten the config file to a dict of device info and
        # a dict of driver-specific configurations
        driver_name = datafile["Device"]["Driver"]
        # Append any extra information to the info dict
        for k, v in datafile["Device"].items():
            if k not in ["Driver", "DeviceMatch"]:
                info[k] = v
        try:
            driver_config = {k: v for k, v in datafile[f"Driver/{driver_name}"].items()}
        except KeyError:
            # not all drivers have custom options
            driver_config = {}

        logger.debug(f"Loading driver {driver_name} for {match} ({device_path})")
        return self._load_driver_by_name(driver_name), driver_config

    def _load_driver_by_name(self, driver_name):
        # Import ratbag.drivers.foo and call load_driver() to instantiate the
        # driver.
        try:
            import importlib

            module = importlib.import_module(f"ratbag.drivers.{driver_name}")
        except ImportError as e:
            logger.error(f"Driver {driver_name} failed to load: {e}")
            return None

        try:
            load_driver_func = getattr(module, ratbag.drivers.Driver.DRIVER_LOAD_FUNC)
        except AttributeError:
            logger.error(
                f"Bug: driver {driver_name} does not have '{ratbag.drivers.Driver.DRIVER_LOAD_FUNC}()'"
            )
            return None
        return load_driver_func(driver_name)


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


class Device(GObject.Object):
    """
    A device as exposed to Ratbag clients. A driver implementation must not
    expose a :class:`ratbag.Device` until it is fully setup and ready to be
    accessed by the client. Usually this means not sending the
    :class:`ratbag.Driver`::``device-added`` signal until the device is
    finalized.

    .. attribute:: name

        The device name

    .. attribute:: path

        The path to the source device

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
        self._dirty = False

    def commit(self):
        """
        Write the current changes to the driver. This function emits the
        ``commit`` signal to notify the respective driver that the current
        state of the device is to be committed. Calling this method resets
        :attr:`dirty` to `False` for all features of this device.

        If an error occurs, the driver emits the ``resync`` signal. A caller
        receiving that signal should synchronize its own state of the device.
        """
        if not self.dirty:
            # well, that was easy
            return

        logger.debug("Writing current changes to device")
        self.emit("commit")

        def clean(x):
            x.dirty = False

        # Now reset all dirty values
        for p in self.profiles.values():
            map(clean, p.buttons.values())
            map(clean, p.resolutions.values())
            map(clean, p.leds.values())
            p.dirty = False
        self.dirty = False

    def _add_profile(self, profile):
        """
        Add the profile to the device.
        """
        assert profile.index not in self.profiles

        def cb_dirty(profile, pspec):
            self.dirty = self.dirty or profile.dirty

        self.profiles[profile.index] = profile
        profile.connect("notify::dirty", cb_dirty)

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
            if self._dirty:
                logger.debug(f"Device {self.name} has uncommited changes")

    def as_dict(self):
        """
        Returns this device as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "name": self.name,
            "path": self.path,
            "profiles": [p.as_dict() for p in self.profiles.values()],
        }


class Feature(GObject.Object):
    """
    Base class for all device features, including profiles. This is a
    convenience class only to avoid re-implementation of common properties.

    :param device: the device this feature belongs to
    :param index: the 0-based feature index

    .. attribute:: device

        The device associated with this feature
    """

    def __init__(self, device, index):
        assert index >= 0
        GObject.Object.__init__(self)
        self.device = device
        self._index = index
        self._dirty = False
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
    """
    A profile on the device. A device must have at least one profile, the
    number of available proviles is device-specific.

    Only one profile may be active at any time. When the active profile
    changes, the ``active`` signal is emitted for the previously
    active profile with a boolean false value, then the ``active`` signal is
    emitted on the newly active profile.

    .. attribute:: name

        The profile name (may be software-assigned)

    .. attribute:: buttons

        The list of :class:`Button` that are available in this profile

    .. attribute:: resolutions

        The list of :class:`Resolution` that are available in this profile

    .. attribute:: leds

        The list of :class:`Led` that are available in this profile

    """

    class Capability(enum.Enum):
        SET_DEFAULT = enum.auto()
        """
        This profile can be set as the default profile. The default profile is
        the one used immediately after the device has been plugged in. If this
        capability is missing, the device typically picks either the last-used
        profile or the first available profile.
        """
        DISABLE = enum.auto()
        """
        The profile can be disabled and enabled. Profiles are not
        immediately deleted after being disabled, it is not guaranteed
        that the device will remember any disabled profiles the next time
        ratbag runs. Furthermore, the order of profiles may get changed
        the next time ratbag runs if profiles are disabled.

        Note that this capability only notes the general capability. A
        specific profile may still fail to be disabled, e.g. when it is
        the last enabled profile on the device.
        """
        WRITE_ONLY = enum.auto()
        """
        The profile information cannot be queried from the hardware.
        Where this capability is present, libratbag cannot
        query the device for its current configuration and the
        configured resolutions and button mappings are unknown.
        libratbag will still provide information about the structure of
        the device such as the number of buttons and resolutions.
        Clients that encounter a device without this resolution are
        encouraged to upload a configuration stored on-disk to the
        device to reset the device to a known state.

        Any changes uploaded to the device will be cached in libratbag,
        once a client has sent a full configuration to the device
        libratbag can be used to query the device as normal.
        """
        INDIVIDUAL_REPORT_RATE = enum.auto()
        """
        The report rate applies per-profile. On devices without this
        capability changing the report rate on one profile also changes it on
        all other profiles.
        """

    __gsignals__ = {
        "active": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(
        self,
        device,
        index,
        name=None,
        capabilities=[],
        report_rate=None,
        report_rates=[],
    ):
        super().__init__(device, index)
        self.name = f"Unnamed {index}" if name is None else name
        self.buttons = {}
        self.resolutions = {}
        self.leds = {}
        self._default = False
        self._active = False
        self._enabled = True
        self._report_rate = report_rate
        self._report_rates = report_rates
        self._capabilities = capabilities
        self.device._add_profile(self)

    @GObject.Property
    def report_rate(self):
        """The report rate in Hz. If the profile does not support configurable
        (or queryable) report rates, the report rate is always ``None``"""
        return self._report_rate

    @report_rate.setter
    def report_rate(self, rate):
        if rate not in self._report_rates:
            raise ConfigError(f"{rate} is not a supported report rate")
        if rate != self._report_rate:
            self._report_rate = rate
            self.dirty = True
            self.notify("report-rate")

    @property
    def report_rates(self):
        """The list of supported report rates in Hz. If the device does not
        support configurable report rates, the list is the empty list"""
        return self._report_rates

    @property
    def capabilities(self):
        return self._capabilities

    @GObject.Property
    def enabled(self):
        """
        ``True`` if this profile is enabled.
        """
        return self._enabled

    @enabled.setter
    def enabled(self, enabled):
        if self._enabled != enabled:
            self._enabled = enabled
            self.dirty = True
            self.notify("enabled")

    @GObject.Property
    def active(self):
        """
        ``True`` if this profile is active, ``False`` otherwise. Note that
        only one profile at a time can be active. See :meth:`set_active`.
        """
        return self._active

    def set_active(self):
        """
        Set this profile to be the active profile.
        """
        if not self.active:
            for p in [p for p in self.device.profiles.values() if p.active]:
                p._active = False
                p.notify("active")
            self._active = True
            self.notify("active")
            self.dirty = True

    @GObject.Property
    def default(self):
        """
        ``True`` if this profile is the default profile, ``False`` otherwise.
        Note that only one profile at a time can be the default. See
        :meth:`set_default`.
        """
        return self._default

    def set_default(self):
        if Profile.Capability.SET_DEFAULT not in self.capabilities:
            raise ConfigError("Profiles set-default capability not supported")
        if not self.default:
            for p in [p for p in self.device.profiles.values() if p.default]:
                p._default = False
                p.notify("default")
            self._default = True
            self.notify("default")
            self.dirty = True

    def _cb_dirty(self, feature, pspec):
        self.dirty = self.dirty or feature.dirty

    def _add_button(self, button):
        assert button.index not in self.buttons
        self.buttons[button.index] = button
        button.connect("notify::dirty", self._cb_dirty)

    def _add_resolution(self, resolution):
        assert resolution.index not in self.resolutions
        self.resolutions[resolution.index] = resolution
        resolution.connect("notify::dirty", self._cb_dirty)

    def _add_led(self, led):
        assert led.index not in self.leds
        self.leds[led.index] = led
        led.connect("notify::dirty", self._cb_dirty)

    def as_dict(self):
        """
        Returns this profile as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "name": self.name,
            "capabilities": [c.name for c in self.capabilities],
            "resolutions": [r.as_dict() for r in self.resolutions.values()],
            "buttons": [b.as_dict() for b in self.buttons.values()],
            "report_rates": [r for r in self.report_rates],
            "report_rate": self.report_rate or 0,
        }


class Resolution(Feature):
    """
    A resolution within a profile. A device must have at least one profile, the
    number of available proviles is device-specific.

    Only one resolution may be active at any time. When the active resolution
    changes, the ``notify::active`` signal is emitted for the previously
    active resolution with a boolean false value, then the ``notify::active``
    signal is emitted on the newly active resolution.

    """

    class Capability(enum.Enum):
        SEPARATE_XY_RESOLUTION = enum.auto()

    def __init__(
        self, profile, index, dpi, *, enabled=True, capabilities=[], dpi_list=[]
    ):
        try:
            assert index >= 0
            assert len(dpi) == 2, "dpi must be a tuple"
            assert all([int(v) >= 0 for v in dpi]), "dpi must be positive"
            assert all(
                [int(v) > 0 for v in dpi_list]
            ), "all in dpi_list must be positive"
            assert all([x in Resolution.Capability for x in capabilities])
            assert index not in profile.resolutions, "duplicate resolution index"
        except (TypeError, ValueError) as e:
            assert e is None

        super().__init__(profile.device, index)
        self.profile = profile
        self._dpi = dpi
        self._dpi_list = dpi_list
        self._capabilities = capabilities
        self._active = False
        self._default = False
        self._enabled = enabled
        self.profile._add_resolution(self)

    @property
    def capabilities(self):
        """
        Return the list of supported :class:`Resolution.Capability`
        """
        return self._capabilities

    @GObject.Property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, enabled):
        if self._enabled != enabled:
            self._enabled = enabled
            self.notify("enabled")
            self.dirty = True

    @GObject.Property
    def active(self):
        """
        ``True`` if this resolution is active, ``False`` otherwise. This
        property should be treated as read-only, use :meth:`set_active`
        instead of writing directly.
        """
        return self._active

    @active.setter
    def active(self, active):
        if self._active != active:
            self._active = active
            self.notify("active")
            self.dirty = True

    def set_active(self):
        """
        Set this resolution to be the active resolution.
        """
        if not self.active:
            for r in self.profile.resolutions.values():
                r.active = False
            self.active = True

    @GObject.Property
    def default(self):
        """
        ``True`` if this resolution is the default resolution, ``False`` otherwise.
        Note that only one resolution at a time can be the default. See
        :meth:`set_default`.
        """
        return self._default

    def set_default(self):
        if not self.default:
            for r in [r for r in self.profile.resolutions.values() if r.default]:
                r._default = False
                r.notify("default")
            self._default = True
            self.notify("default")
            self.dirty = True

    @GObject.Property
    def dpi(self):
        """
        A tuple of `(x, y)` resolution values. If this device does not have
        :meth:`Resolution.Capability.SEPARATE_XY_RESOLUTION`, the tuple always
        has two identical values.
        """
        return self._dpi

    @dpi.setter
    def dpi(self, new_dpi):
        try:
            x, y = new_dpi
            if y not in self._dpi_list:
                raise ConfigError(f"{y} is not a supported resolution")
        except TypeError:
            x = new_dpi
            y = new_dpi
        if x not in self._dpi_list:
            raise ConfigError(f"{x} is not a supported resolution")
        if (x, y) != self._dpi:
            self._dpi = (x, y)
            self.dirty = True
            self.notify("dpi")

    @property
    def dpi_list(self):
        """
        Return a list of possible resolution values on this device
        """
        return self._dpi_list

    def as_dict(self):
        """
        Returns this resolution as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "dpi": list(self.dpi),
            "dpi_list": self.dpi_list,
            "active": self.active,
            "enabled": self.enabled,
            "default": self.default,
        }


class Action(GObject.Object):
    class Type(enum.Enum):
        NONE = enum.auto()
        BUTTON = enum.auto()
        MACRO = enum.auto()
        SPECIAL = enum.auto()
        UNKNOWN = enum.auto()

    def __init__(self, parent):
        GObject.Object.__init__(self)
        self._parent = parent
        self.type = Action.Type.UNKNOWN

    def __str__(self):
        return "Unknown"

    def as_dict(self):
        return {"type": self.type.name}


class ActionNone(Action):
    """
    A "none" action to signal the button is disabled and does not send an
    event when physically presed down.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.type = Action.Type.NONE

    def __str__(self):
        return "None"


class ActionButton(Action):
    """
    A button action triggered by a button. This is the simplest case of an
    action where a button triggers... a button event! Note that while
    :class:`Button` uses indices starting at zero, button actions start
    at button 1 (left mouse button).
    """

    def __init__(self, parent, button):
        super().__init__(parent)
        self._button = button
        self.type = Action.Type.BUTTON

    @property
    def button(self):
        """The 1-indexed mouse button"""
        return self._button

    def __str__(self):
        return f"Button {self.button}"

    def as_dict(self):
        return {
            **super().as_dict(),
            **{
                "button": self.button,
            },
        }


class ActionSpecial(Action):
    """
    A special action triggered by a button. These actions are fixed
    events supported by devices, see :class:`ActionSpecial.Special` for the
    list of known actions.

    Note that not all devices support all special actions and buttons on a
    given device may not support all special events.
    """

    class Special(enum.Enum):
        UNKNOWN = enum.auto()
        DOUBLECLICK = enum.auto()

        WHEEL_LEFT = enum.auto()
        WHEEL_RIGHT = enum.auto()
        WHEEL_UP = enum.auto()
        WHEEL_DOWN = enum.auto()
        RATCHET_MODE_SWITCH = enum.auto()

        RESOLUTION_UP = enum.auto()
        RESOLUTION_DOWN = enum.auto()
        RESOLUTION_CYCLE_UP = enum.auto()
        RESOLUTION_CYCLE_DOWN = enum.auto()
        RESOLUTION_ALTERNATE = enum.auto()
        RESOLUTION_DEFAULT = enum.auto()

        PROFILE_CYCLE_UP = enum.auto()
        PROFILE_CYCLE_DOWN = enum.auto()
        PROFILE_UP = enum.auto()
        PROFILE_DOWN = enum.auto()

        SECOND_MODE = enum.auto()
        BATTERY_LEVEL = enum.auto()

    def __init__(self, parent, special):
        super().__init__(parent)
        self.type = Action.Type.SPECIAL
        self._special = special

    @property
    def special(self):
        return self._special

    def __str__(self):
        return f"Special {self.special.name}"

    def as_dict(self):
        return {
            **super().as_dict(),
            **{
                "special": self.special.name,
            },
        }


class ActionMacro(Action):
    """
    A macro assigned to a button. The macro may consist of key presses,
    releases and timeouts (see :class:`ActionMacro.Event`), the length of the
    macro and limitations on what keys can be used are device-specific.
    """

    class Event(enum.Enum):
        INVALID = enum.auto()
        NONE = enum.auto()
        KEY_PRESS = enum.auto()
        KEY_RELEASE = enum.auto()
        WAIT_MS = enum.auto()

    def __init__(self, parent, name="Unnamed macro", events=[(Event.INVALID,)]):
        super().__init__(parent)
        self.type = Action.Type.MACRO
        self.name = name
        self._events = events

    @property
    def events(self):
        """
        A list of tuples that describe the sequence of this macro. Each tuple
        is of type ``(Macro.Event.KEY_PRESS, 34)`` or ``(Macro.Event.WAIT_MS, 500)``,
        i.e. the first entry is a :class:`Macro.Event` enum and the remaining
        entries are the type-specific values.

        The length of each tuple is type-specific, clients must be able to
        handle tuples with lengths other than 2.

        This property is read-only. To change a macro, create a new one with
        the desired event sequence and assign it to the button.
        """
        return self._events

    def _events_as_strlist(self):
        prefix = {
            ActionMacro.Event.INVALID: "x",
            ActionMacro.Event.KEY_PRESS: "+",
            ActionMacro.Event.KEY_RELEASE: "-",
            ActionMacro.Event.WAIT_MS: "t",
        }
        return [f"{prefix[t]}{v}" for t, v in self.events]

    def __str__(self):
        str = " ".join(self._events_as_strlist())
        return f"Macro: {self.name}: {str}"

    def as_dict(self):
        return {
            **super().as_dict(),
            **{
                "macro": {
                    "name": self.name,
                    "events": self._events_as_strlist(),
                }
            },
        }


class Button(Feature):
    """
    A physical button on the device as represented in a profile. A button has
    an :class:`Action` assigned to it, be that to generate a button click, a
    special event or even a full sequence of key strokes (:class:`Macro`).

    Note that each :class:`Button` represents one profile only so the same
    physical button will have multiple :class:`Button` instances.

    .. attribute:: profile

        The profile this button belongs to

    """

    def __init__(
        self,
        profile,
        index,
        *,
        types=[Action.Type.BUTTON],
        action=None,
    ):
        super().__init__(profile.device, index)
        self.profile = profile
        self._types = types
        self._action = action
        self.profile._add_button(self)

    @property
    def types(self):
        """
        The list of supported :class:`Action.Type` for this button
        """
        return self._types

    @GObject.Property
    def action(self):
        """
        The currently assigned action. This action is guaranteed to be of
        type :class:`Action` or one of its subclasses.
        """
        return self._action

    @action.setter
    def action(self, new_action):
        if not isinstance(new_action, Action):
            raise ConfigError(f"Invalid button action of type {type(new_action)}")
        self._action = new_action
        self.notify("action")
        self.dirty = True

    def as_dict(self):
        """
        Returns this button as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "action": self.action.as_dict(),
        }


class Led(Feature):
    class Colordepth(enum.Enum):
        MONOCHROME = enum.auto()
        RGB_111 = enum.auto()
        RGB_888 = enum.auto()

    class Mode(enum.Enum):
        OFF = enum.auto()
        ON = enum.auto()
        CYCLE = enum.auto()
        BREATHING = enum.auto()

    def __init__(
        self,
        profile,
        index,
        *,
        color=(0, 0, 0),
        colordepth=Colordepth.RGB_888,
        modes=[Mode.OFF],
    ):
        super().__init__(profile.device, index)
        self.profile = profile
        self._color = color
        self._colordepth = colordepth
        self._effect_duration = 0
        self._mode = Led.Mode.OFF
        self._modes = modes
        self.profile._add_led(self)

    @GObject.Property
    def color(self):
        return self._color

    @color.setter
    def color(self, rgb):
        try:
            if len(rgb) != 3:
                raise ConfigError("Invalid color, must be (r, g, b)")
        except TypeError:
            raise ConfigError("Invalid color, must be (r, g, b)")
        if self._color != rgb:
            self._color = rgb
            self.notify("color")
            self.dirty = True

    def colordepth(self):
        return self._colordepth

    @GObject.Property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, brightness):
        if brightness != self._brightness:
            self._brightness = brightness
            self.dirty = True

    @GObject.Property
    def effect_duration(self):
        return self._effect_duration

    @effect_duration.setter
    def effect_duration(self, effect_duration):
        if effect_duration != self._effect_duration:
            self._effect_duration = effect_duration
            self.notify("effect_duration")
            self.dirty = True

    @GObject.Property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, mode):
        if mode not in self.modes:
            raise ConfigError(f"Unsupported LED mode {str(mode)}")
        if mode != self._mode:
            self._mode = mode
            self.notify("mode")
            self.dirty = True

    def modes(self):
        """
        Return the list of :class:`Led.Mode` available for this LED
        """
        return self._modes
