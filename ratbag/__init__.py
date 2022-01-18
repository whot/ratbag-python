#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

from pathlib import Path
from gi.repository import GLib, GObject
from typing import Any, Callable, Dict, List, Optional, Tuple

import enum
import logging
import pyudev

import ratbag.util


CommitCallback = Callable[["ratbag.Device", bool, int], None]

logger = logging.getLogger(__name__)


class UnsupportedDeviceError(Exception):
    """
    Error indicating that the device is not supported. This exception is
    raised for devices that ratbag does not have an implementation for.

    .. note:: This error is unrecoverable without changes to ratbag.

    .. attribute:: path

       The device path that failed

    .. attribute:: name

       The device name that failed

    """

    def __init__(self, name: str = None, path: Path = None):
        self.name = name
        self.path = path


class SomethingIsMissingError(UnsupportedDeviceError):
    """
    Error indicating that the device is missing something that we require for
    it to work. This exception is raised for devices that ratbag has an
    implementation for but for some reason the device is lacking a required
    feature.

    .. note:: This error is unrecoverable without changes to ratbag.

    .. attribute:: thing

       A string explaining the thing that is missing
    """

    def __init__(self, name: str, path: Path, thing: str):
        super().__init__(name, path)
        self.thing = thing


class ConfigError(Exception):
    """
    Error indicating that the caller has tried to set the device's
    configuration to an unsupported value, format, or feature.

    This error is recoverable by re-reading the device's current state and
    attempting a different configuration.

    .. attribute:: message

        The error message
    """

    def __init__(self, message: str):
        self.message = message


class ProtocolError(Exception):
    """
    Error indicating that the communication with the device encountered an
    error

    It depends on the specifics on the error whether this is recoverable.

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

    def __init__(self, message: str = None, name: str = None, path: str = None):
        self.name = name
        self.path = path
        self.message = message
        self.conversation: List[bytes] = []


class Ratbag(GObject.Object):
    """
    An instance managing one or more ratbag devices. This is the entry point
    for all ratbag clients. The ratbag object can be instantiated with a
    static device path (or several) or, the default, support for udev. In the
    latter case, devices are added/removed as they appear.

    Where static device paths are given, the device must be present and
    removal of that device will not re-add this device in the future.

    Example: ::

        r = ratbag.Ratbag()
        r.connect("device-added", lambda ratbag, device: print(f"New device: {device}"))
        r.start()
        GLib.MainLoop().run()

    :class:`ratbag.Ratbag` requires a GLib mainloop.

    :param config: a dictionary with configuration information

    Supported keys in ``config``:

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

    def __init__(self, config: Dict[str, Any] = {}):
        super().__init__()
        self._devices: List[Device] = []
        self._config = config

    def start(self) -> None:
        """
        Add the devices and/or start monitoring udev for new devices.
        """
        logger.debug("Installing udev monitor")
        self._install_udev_monitor()
        for path in ratbag.util.find_hidraw_devices():
            self._add_device(path=path)

        for emulator in self._config.get("emulators", []):
            driver = self._load_driver_by_name(emulator.driver)
            driver.probe(emulator, {})

    def _install_udev_monitor(self) -> None:
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

    def _add_device(self, path: str) -> None:
        try:
            from ratbag.drivers import DeviceInfo, Rodent

            info = DeviceInfo.from_path(Path(path))
            drivername, config = self._find_driver(info)

            if drivername is None:
                logger.info(
                    f"Skipping device {info.name} ({info.path}), no driver assigned"
                )
                return

            try:
                driver = self._load_driver_by_name(drivername)
            except UnsupportedDeviceError as e:
                e.name = info.name
                e.path = info.path
                raise e

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

            rodent = Rodent.from_device_info(info)
            driver.probe(rodent, config)
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

    def _find_driver(
        self,
        info: "ratbag.drivers.DeviceInfo",
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Load the driver assigned to the bus/VID/PID match. If a matching
        driver is found, that driver's :func:`LOAD_DRIVER_FUNC` is called with
        the *static* information about the device.

        :param info: a dict of various info collected for this device
        :return: a tuple of ``(driver, configdict)`` for a
                :class:`ratbag.drivers.Driver` and a config dict from the data file
                with driver-specific configuration
        :raises: UnsupportedDeviceError, NotImplementedError
        """

        match = f"{info.bus}:{info.vid:04x}:{info.pid:04x}"
        # FIXME: this needs to use the install path
        path = Path("data")
        if not path.exists():
            path = Path("/usr/share/libratbag/data")
            if not path.exists():
                raise NotImplementedError(
                    "Missing data files: none in /usr/share/libratbag, none in $PWD/data"
                )
        datafiles = ratbag.util.load_data_files(path)
        try:
            datafile = datafiles[match]
        except KeyError:
            return None, {}

        # Flatten the config file to a dict of device info and
        # a dict of driver-specific configurations
        driver_name = datafile["Device"]["Driver"]
        # Append any extra information to the info dict
        for k, v in datafile["Device"].items():
            if k not in ["Driver", "DeviceMatch"]:
                if getattr(info, k, None):
                    setattr(info, k, v)
        try:
            driver_config = {k: v for k, v in datafile[f"Driver/{driver_name}"].items()}
        except KeyError:
            # not all drivers have custom options
            driver_config = {}

        logger.debug(f"Found driver {driver_name} for {match}")
        return driver_name, driver_config

    def _load_driver_by_name(self, driver_name: str) -> "ratbag.drivers.Driver":
        # Import ratbag.drivers.foo and call load_driver() to instantiate the
        # driver.
        try:
            import importlib

            module = importlib.import_module(f"ratbag.drivers.{driver_name}")
        except ImportError as e:
            raise UnsupportedDeviceError(f"Driver {driver_name} failed to load: {e}")

        try:
            from ratbag.drivers import Driver

            load_driver_func = getattr(module, Driver.DRIVER_LOAD_FUNC)
        except AttributeError:
            raise NotImplementedError(
                f"Bug: driver {driver_name} does not have '{ratbag.drivers.Driver.DRIVER_LOAD_FUNC}()'"
            )
        return load_driver_func(driver_name)


class Recorder(GObject.Object):
    """
    Recorder can be added to a :class:`ratbag.Driver` to log data between the
    host and the device, see :func:`ratbag.Driver.add_recorder`

    :param config: A dictionary with logger-specific data to initialize
    """

    def __init__(self, config: Dict[str, Any] = {}):
        GObject.Object.__init__(self)

    def init(self, info: Dict[str, Any] = {}) -> None:
        """
        Initialize the logger for the given device.

        :param info: a dictionary of extra logging keys
        """
        pass

    def log_rx(self, data: bytes) -> None:
        """
        Log data received from the device
        """
        pass

    def log_tx(self, data: bytes) -> None:
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
        "commit": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (
                GObject.TYPE_PYOBJECT,
                GObject.TYPE_PYOBJECT,
            ),
        ),
        "resync": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __init__(
        self, driver: "ratbag.drivers.Driver", path: str, name: str, model: str
    ):
        GObject.Object.__init__(self)
        self.driver = driver
        self.path = path
        self.name = name
        self.model = model
        self._profiles: Tuple[Profile, ...] = tuple()
        self._driver = driver
        self._dirty = False
        self._seqno = 1

    @property
    def profiles(self) -> Tuple["ratbag.Profile", ...]:
        """
        The tuple of device profiles, in-order sorted by profile index.
        """
        # Internally profiles is a dict so we can create them out-of-order if
        # need be but externally it's a tuple because we don't want anyone to
        # modify it.
        return self._profiles

    def commit(self, callback: CommitCallback = None) -> int:
        """
        Write the current changes to the driver. This is an asynchronous
        operation (maybe in a separate thread). Once complete, the
        driver calls the specified callback function with a boolean status. ::

            def commit_complete(device, status, sequence_number):
                if status:
                    print("Commit was successful")

            seqno = device.commit(commit_complete)

        The returned sequence number can be used to identify the specific
        invocation of :meth:`commit`. This number increases by an unspecified
        amount every time the device state changes, a ``resync`` signal with a
        sequence number lower than returned by this method is thus from an
        earlier device change.

        The :attr:`dirty` status of the device's features is reset to
        ``False`` immediately before the callback is invoked but not before
        the driver handles the state changes. In other words, a caller must
        not rely on the :attr:`dirty` status between :meth:`commit` and the
        callback.

        If an error occurs, the driver calls the callback with a ``False``.

        If any device state changes in response to :meth:`commit`, the driver
        emits a ``resync`` signal to notify all other listeners. This signal
        includes the same sequence as passed to the callback to allow for
        filtering signals.

        :returns: a sequence number for this transaction
        """

        self._seqno += 1
        GLib.idle_add(self._cb_idle_commit, callback, self._seqno)
        return self._seqno

    def _cb_idle_commit(self, callback: CommitCallback, seqno: int) -> bool:
        if not self.dirty:
            # well, that was easy
            callback(self, True, seqno)
            return False  # don't reschedule idle func

        def callback_wrapper(device: ratbag.Device, status: bool, seqno: int) -> None:
            def clean(x: "ratbag.Feature") -> None:
                x.dirty = False  # type: ignore

            # Now reset all dirty values
            for p in self.profiles:
                map(clean, p.buttons)
                map(clean, p.resolutions)
                map(clean, p.leds)
                p.dirty = False  # type: ignore
            self.dirty = False  # type: ignore
            callback(self, status, seqno)

        logger.debug("Writing current changes to device")
        self.emit("commit", callback_wrapper, seqno)

        return False  # don't reschedule idle func

    def _add_profile(self, profile: "ratbag.Profile") -> None:
        """
        Add the profile to the device.
        """
        self._profiles = ratbag.util.add_to_sparse_tuple(
            self._profiles, profile.index, profile
        )

        def cb_dirty(profile, pspec):
            self.dirty = self.dirty or profile.dirty

        profile.connect("notify::dirty", cb_dirty)

    @GObject.Property(type=bool, default=False)
    def dirty(self) -> bool:
        """
        ``True`` if changes are uncommited. Connect to ``notify::dirty`` to receive changes.
        """
        return self._dirty

    @dirty.setter  # type: ignore
    def dirty(self, is_dirty: bool) -> None:
        if self._dirty != is_dirty:
            self._dirty = is_dirty
            self.notify("dirty")
            if self._dirty:
                logger.debug(f"Device {self.name} has uncommited changes")

    def as_dict(self) -> Dict[str, Any]:
        """
        Returns this device as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "name": self.name,
            "path": str(self.path),
            "profiles": [p.as_dict() for p in self.profiles],
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

    def __init__(self, device: ratbag.Device, index: int):
        assert index >= 0
        GObject.Object.__init__(self)
        self.device = device
        self._index = index
        self._dirty = False
        logger.debug(
            f"{self.device.name}: creating {type(self).__name__} with index {self.index}"
        )

    @property
    def index(self) -> int:
        """
        The 0-based device index of this feature. Indices are counted from the
        parent feature up, i.e. the first resolution of a profile 1 is
        resolution 0, the first resolution of profile 2 also has an index of
        0.
        """

        return self._index

    @GObject.Property(type=bool, default=False)
    def dirty(self) -> bool:
        """
        ``True`` if changes are uncommited. Connect to ``notify::dirty`` to receive changes.
        """
        return self._dirty

    @dirty.setter  # type: ignore
    def dirty(self, is_dirty) -> None:
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

    """

    class Capability(enum.Enum):
        """
        Capabilities specific to profiles.
        """

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
        capabilities=(),
        report_rate=None,
        report_rates=(),
        active=False,
    ):
        super().__init__(device, index)
        self.name = f"Unnamed {index}" if name is None else name
        self._buttons = ()
        self._resolutions = ()
        self._leds = ()
        self._default = False
        self._active = active
        self._enabled = True
        self._report_rate = report_rate
        self._report_rates = tuple(sorted(set(report_rates)))
        self._capabilities = tuple(sorted(set(capabilities)))
        self.device._add_profile(self)

    @property
    def buttons(self) -> Tuple["ratbag.Button", ...]:
        """
        The tuple of :class:`Button` that are available in this profile
        """
        return self._buttons

    @property
    def resolutions(self) -> Tuple["ratbag.Resolution", ...]:
        """
        The tuple of :class:`Resolution` that are available in this profile
        """
        return self._resolutions

    @property
    def leds(self) -> Tuple["ratbag.Led", ...]:
        """
        The tuple of :class:`Led` that are available in this profile
        """
        return self._leds

    @GObject.Property(type=int, default=0)
    def report_rate(self) -> int:
        """The report rate in Hz. If the profile does not support configurable
        (or queryable) report rates, the report rate is always ``None``"""
        return self._report_rate

    def set_report_rate(self, rate: int) -> None:
        """
        Set the report rate for this profile.

        :raises: ConfigError
        """
        if rate not in self._report_rates:
            raise ConfigError(f"{rate} is not a supported report rate")
        if rate != self._report_rate:
            self._report_rate = rate
            self.dirty = True  # type: ignore
            self.notify("report-rate")

    @property
    def report_rates(self) -> Tuple[int, ...]:
        """The tuple of supported report rates in Hz. If the device does not
        support configurable report rates, the tuple is the empty tuple"""
        return self._report_rates

    @property
    def capabilities(self) -> Tuple[Capability, ...]:
        """
        Return the tuple of supported :class:`Profile.Capability`
        """
        return self._capabilities

    @GObject.Property(type=bool, default=True)
    def enabled(self) -> bool:
        """
        ``True`` if this profile is enabled.
        """
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if Profile.Capability.DISABLE not in self.capabilities:
            raise ConfigError("Profile disable capability not supported")

        if self._enabled != enabled:
            self._enabled = enabled
            self.dirty = True  # type: ignore
            self.notify("enabled")

    @GObject.Property(type=bool, default=False)
    def active(self) -> bool:
        """
        ``True`` if this profile is active, ``False`` otherwise. Note that
        only one profile at a time can be active. See :meth:`set_active`.
        """
        return self._active

    def set_active(self) -> None:
        """
        Set this profile to be the active profile.
        """
        if not self.active:
            for p in filter(lambda p: p.active, self.device.profiles):
                p._active = False
                p.notify("active")
            self._active = True
            self.notify("active")
            self.dirty = True  # type: ignore

    @GObject.Property(type=bool, default=False)
    def default(self) -> bool:
        """
        ``True`` if this profile is the default profile, ``False`` otherwise.
        Note that only one profile at a time can be the default. See
        :meth:`set_default`.
        """
        return self._default

    def set_default(self) -> None:
        """
        Set this profile as the default profile.

        :raises: ConfigError
        """
        if Profile.Capability.SET_DEFAULT not in self.capabilities:
            raise ConfigError("Profiles set-default capability not supported")
        if not self.default:
            for p in filter(lambda p: p.default, self.device.profiles):
                p._default = False
                p.notify("default")
            self._default = True
            self.notify("default")
            self.dirty = True  # type: ignore

    def _cb_dirty(self, feature, pspec):
        self.dirty = self.dirty or feature.dirty

    def _add_button(self, button: "ratbag.Button") -> None:
        self._buttons = ratbag.util.add_to_sparse_tuple(
            self._buttons, button.index, button
        )
        button.connect("notify::dirty", self._cb_dirty)

    def _add_resolution(self, resolution: "ratbag.Resolution") -> None:
        self._resolutions = ratbag.util.add_to_sparse_tuple(
            self._resolutions, resolution.index, resolution
        )
        resolution.connect("notify::dirty", self._cb_dirty)

    def _add_led(self, led: "ratbag.Led") -> None:
        self._leds = ratbag.util.add_to_sparse_tuple(self._leds, led.index, led)
        led.connect("notify::dirty", self._cb_dirty)

    def as_dict(self) -> Dict[str, Any]:
        """
        Returns this profile as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "name": self.name,
            "capabilities": [c.name for c in self.capabilities],
            "resolutions": [r.as_dict() for r in self.resolutions],
            "buttons": [b.as_dict() for b in self.buttons],
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
        """
        Capabilities specific to resolutions.
        """

        SEPARATE_XY_RESOLUTION = enum.auto()
        """
        The device can adjust x and y resolution independently. If this
        capability is **not** present, the arguments to :meth:`set_dpi` must
        be a tuple of identical values.
        """

    def __init__(
        self,
        profile: Profile,
        index: int,
        dpi: Tuple[int, int],
        *,
        enabled: bool = True,
        capabilities: Tuple[Capability, ...] = (),
        dpi_list: Tuple[int, ...] = (),
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
        self._dpi_list = tuple(sorted(set(dpi_list)))
        self._capabilities = tuple(set(capabilities))
        self._active = False
        self._default = False
        self._enabled = enabled
        self.profile._add_resolution(self)

    @property
    def capabilities(self) -> Tuple[Capability, ...]:
        """
        Return the tuple of supported :class:`Resolution.Capability`
        """
        return self._capabilities

    @GObject.Property(type=bool, default=True)
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled != enabled:
            self._enabled = enabled
            self.notify("enabled")
            self.dirty = True  # type: ignore

    @GObject.Property(type=bool, default=False)
    def active(self) -> bool:
        """
        ``True`` if this resolution is active, ``False`` otherwise. This
        property should be treated as read-only, use :meth:`set_active`
        instead of writing directly.
        """
        return self._active

    @active.setter  # type: ignore
    def active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.notify("active")
            self.dirty = True  # type: ignore

    def set_active(self) -> None:
        """
        Set this resolution to be the active resolution.
        """
        if not self.active:
            for r in self.profile.resolutions:
                r.active = False
            self.active = True

    @GObject.Property(type=bool, default=False)
    def default(self) -> bool:
        """
        ``True`` if this resolution is the default resolution, ``False`` otherwise.
        Note that only one resolution at a time can be the default. See
        :meth:`set_default`.
        """
        return self._default

    def set_default(self) -> None:
        """
        Set this resolution as the default resolution.

        :raises: ConfigError
        """
        if not self.default:
            for r in filter(lambda r: r.default, self.profile.resolutions):
                r._default = False
                r.notify("default")
            self._default = True
            self.notify("default")
            self.dirty = True  # type: ignore

    @GObject.Property
    def dpi(self) -> Tuple[int, int]:
        """
        A tuple of `(x, y)` resolution values. If this device does not have
        :meth:`Resolution.Capability.SEPARATE_XY_RESOLUTION`, the tuple always
        has two identical values.
        """
        return self._dpi

    def set_dpi(self, new_dpi: Tuple[int, int]) -> None:
        """
        Change the dpi of this device.

        :raises: ConfigError
        """
        try:
            x, y = new_dpi
            if y not in self._dpi_list or x not in self._dpi_list:
                raise ConfigError(f"({x}, {y}) is not a supported resolution")
            if (
                x != y
                and ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION
                not in self.capabilities
            ):
                raise ConfigError(
                    "Individual x/y resolution not supported by this device"
                )
        except TypeError:
            raise ConfigError(f"Invalid resolution {new_dpi}, must be (x, y) tuple")
        if (x, y) != self._dpi:
            self._dpi = (x, y)
            self.dirty = True  # type: ignore
            self.notify("dpi")

    @property
    def dpi_list(self) -> Tuple[int, ...]:
        """
        Return a tuple of possible resolution values on this device
        """
        return self._dpi_list

    def as_dict(self) -> Dict[str, Any]:
        """
        Returns this resolution as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "dpi": list(self.dpi),
            "dpi_list": list(self.dpi_list),
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
        self._type = Action.Type.UNKNOWN

    @property
    def type(self) -> Type:
        return self._type

    def __str__(self) -> str:
        return "Unknown"

    def as_dict(self) -> Dict[str, Any]:
        return {"type": self.type.name}

    def __eq__(self, other):
        return type(self) == type(other)

    def __ne__(self, other):
        return not self == other


class ActionNone(Action):
    """
    A "none" action to signal the button is disabled and does not send an
    event when physically presed down.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._type: Action.Type = Action.Type.NONE

    def __str__(self) -> str:
        return "None"


class ActionButton(Action):
    """
    A button action triggered by a button. This is the simplest case of an
    action where a button triggers... a button event! Note that while
    :class:`Button` uses indices starting at zero, button actions start
    at button 1 (left mouse button).
    """

    def __init__(self, parent, button: int):
        super().__init__(parent)
        self._button = button
        self._type = Action.Type.BUTTON

    @property
    def button(self) -> int:
        """The 1-indexed mouse button"""
        return self._button

    def __str__(self) -> str:
        return f"Button {self.button}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            **super().as_dict(),
            **{
                "button": self.button,
            },
        }

    def __eq__(self, other):
        return type(self) == type(other) and self.button == other.button


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

    def __init__(self, parent, special: Special):
        super().__init__(parent)
        self._type = Action.Type.SPECIAL
        self._special = special

    @property
    def special(self) -> Special:
        return self._special

    def __str__(self) -> str:
        return f"Special {self.special.name}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            **super().as_dict(),
            **{
                "special": self.special.name,
            },
        }

    def __eq__(self, other):
        return type(self) == type(other) and self.special == other.special


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

    def __init__(
        self,
        parent,
        name: str = "Unnamed macro",
        events: List[Tuple[Event, int]] = [(Event.INVALID, 0)],
    ):
        super().__init__(parent)
        self._type = Action.Type.MACRO
        self._name = name
        self._events = events

    @property
    def name(self) -> str:
        return self._name

    @property
    def events(self) -> List[Tuple[Event, int]]:
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

    def _events_as_strlist(self) -> List[str]:
        prefix = {
            ActionMacro.Event.INVALID: "x",
            ActionMacro.Event.KEY_PRESS: "+",
            ActionMacro.Event.KEY_RELEASE: "-",
            ActionMacro.Event.WAIT_MS: "t",
        }
        return [f"{prefix[t]}{v}" for t, v in self.events]

    def __str__(self) -> str:
        str = " ".join(self._events_as_strlist())
        return f"Macro: {self.name}: {str}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            **super().as_dict(),
            **{
                "macro": {
                    "name": self.name,
                    "events": self._events_as_strlist(),
                }
            },
        }

    def __eq__(self, other):
        return type(self) == type(other) and all(
            [x == y for x in self.events for y in other.events]
        )


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
        profile: ratbag.Profile,
        index: int,
        *,
        types: Tuple[Action.Type] = (Action.Type.BUTTON,),
        action: Optional[Action] = None,
    ):
        super().__init__(profile.device, index)
        self.profile = profile
        self._types = tuple(set(types))
        self._action = action or Action(self)
        self.profile._add_button(self)

    @property
    def types(self) -> Tuple[Action.Type, ...]:
        """
        The list of supported :class:`Action.Type` for this button
        """
        return self._types

    @GObject.Property(type=ratbag.Action, default=None)
    def action(self) -> Action:
        """
        The currently assigned action. This action is guaranteed to be of
        type :class:`Action` or one of its subclasses.
        """
        return self._action

    def set_action(self, new_action: Action) -> None:
        """
        Set the action rate for this button.

        :raises: ConfigError
        """
        if not isinstance(new_action, Action):
            raise ConfigError(f"Invalid button action of type {type(new_action)}")
        self._action = new_action
        self.notify("action")
        self.dirty = True  # type: ignore

    def as_dict(self) -> Dict[str, Any]:
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
        profile: ratbag.Profile,
        index: int,
        *,
        color: Tuple[int, int, int] = (0, 0, 0),
        brightness: int = 0,
        colordepth: Colordepth = Colordepth.RGB_888,
        mode: Mode = Mode.OFF,
        modes: Tuple[Mode, ...] = (Mode.OFF,),
        effect_duration: int = 0,
    ):
        super().__init__(profile.device, index)
        self.profile = profile
        self._color = color
        self._colordepth = colordepth
        self._brightness = brightness
        self._effect_duration = effect_duration
        self._mode = mode
        self._modes = tuple(modes)
        self.profile._add_led(self)

    @GObject.Property
    def color(self) -> Tuple[int, int, int]:
        """
        Return a triplet of ``(r, g, b)`` of positive integers. If any color
        scaling applies because of the device's :class:`ratbag.Led.Colordepth`
        this is **not** reflected in this value. In other words, the color
        always matches the last successful call to :meth:`set_color`.
        """
        return self._color

    def set_color(self, rgb: Tuple[int, int, int]) -> None:
        """
        Set the color for this LED. The color provided has to be within the
        allowed color range, see :class:`ratbag.Led.Colordepth`. ratbag
        silently scales and/or clamps to the device's color depth, it is the
        caller's responsibility to set the colors in a non-ambiguous way.

        :raises: ConfigError
        """
        try:
            r, g, b = [int(c) for c in rgb]
            if not all([0 <= c <= 255 for c in (r, g, b)]):
                raise ValueError()
        except (TypeError, ValueError):
            raise ConfigError("Invalid color, must be (r, g, b), zero or higher")
        if self._color != rgb:
            self._color = rgb
            self.notify("color")
            self.dirty = True  # type: ignore

    def colordepth(self) -> Colordepth:
        return self._colordepth

    @GObject.Property(type=int, default=0)
    def brightness(self) -> int:
        return self._brightness

    def set_brightness(self, brightness: int) -> None:
        try:
            brightness = int(brightness)
            if not 0 <= brightness <= 255:
                raise ValueError()
        except (TypeError, ValueError):
            raise ConfigError("Invalid brightness value, must be 0-255")

        if brightness != self._brightness:
            self._brightness = brightness
            self.dirty = True  # type: ignore

    @GObject.Property(type=int, default=0)
    def effect_duration(self) -> int:
        return self._effect_duration

    def set_effect_duration(self, effect_duration: int) -> None:
        try:
            effect_duration = int(effect_duration)
            # effect over 10s is likely a bug in the caller
            if not 0 <= effect_duration <= 10000:
                raise ValueError()
        except (TypeError, ValueError):
            raise ConfigError("Invalid effect_duration value, must be >= 0")

        if effect_duration != self._effect_duration:
            self._effect_duration = effect_duration
            self.notify("effect_duration")
            self.dirty = True  # type: ignore

    @GObject.Property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        """
        Change the mode of this LED. The supplied mode must be one returned by
        :meth:`modes`.
        """
        if mode not in self.modes:
            raise ConfigError(f"Unsupported LED mode {str(mode)}")
        if mode != self._mode:
            self._mode = mode
            self.notify("mode")
            self.dirty = True  # type: ignore

    @property
    def modes(self) -> Tuple[Mode, ...]:
        """
        Return a tuple of the available :class:`Led.Mode` for this LED
        """
        return self._modes
