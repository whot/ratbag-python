#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

from pathlib import Path
from gi.repository import GLib, GObject
from typing import Any, Callable, Dict, List, Optional, Tuple
from itertools import count

import attr
import enum
import logging

import ratbag.util


logger = logging.getLogger(__name__)


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


@attr.s
class Ratbag(GObject.Object):
    """
    An instance managing one or more ratbag devices. This is the entry point
    for all ratbag clients. This context loads the data files and instantiates
    the drivers accordingly.

    Example: ::

        r = ratbag.Ratbag()
        r.connect("device-added", lambda ratbag, device: print(f"New device: {device}"))
        r.start()
        GLib.MainLoop().run()

    :class:`ratbag.Ratbag` requires a GLib mainloop.

    :param config: a dictionary with configuration information
    :param load_data_files: ``True`` if the data files should be loaded. There
        is rarely a need for setting this to ``False`` outside specific test
        cases.

    GObject Signals:

    - ``device-added`` Notification that a new :class:`ratbag.Device` was added
    - ``device-removed`` Notification that the :class:`ratbag.Device` was removed

    """

    _devices: List["Device"] = attr.ib(init=False, default=attr.Factory(list))
    _blackbox: Optional["Blackbox"] = attr.ib(default=None)

    def __attrs_pre_init__(self):
        GObject.Object.__init__(self)

    @classmethod
    def create_empty(cls, /, blackbox: Optional["Blackbox"]) -> "Ratbag":
        """
        Create an "empty" instance of ratbag that does not load any drivers
        and thus will not detect devices. The caller is responsible for
        adding drivers.

        This is used for testing only, use :meth:`Ratbag.create` instead.
        """
        r = cls(blackbox=blackbox)
        return r

    @classmethod
    def create(cls, /, blackbox: Optional["Blackbox"] = None) -> "Ratbag":
        """
        Create a new Ratbag instance.
        """
        r = cls(blackbox=blackbox)
        r._load_data_files()
        return r

    @GObject.Signal(name="start")
    def _start(self, *args):
        """
        GObject signal emitted in response to :meth:`start`.
        This signal is for internal use.
        """
        pass

    @GObject.Signal(name="device-added", arg_types=(object,))
    def device_added(self, *args):
        """
        GObject signal emitted when a new :class:`ratbag.Device` was added
        """
        pass

    def _load_data_files(self):
        """
        Load all data files, extract the driver name and the match and compile
        a list of the matches and any driver-specific configuration.
        Then load all the drivers so they can set up the monitors as needed.

        This approach is inefficient (since we load all drivers even when
        we're likely to only have one device that needs one driver), but it
        pushes device discovery into the drivers, making them independent of
        the context and thus more flexible for future drivers that don't just
        hook onto hidraw devices.
        """

        from ratbag.driver import DeviceConfig

        datafiles = ratbag.util.load_data_files()

        # drivers want the list of all entries passed as one, so we need to
        # extract them first, into a dict of
        # "drivername" : [DeviceConfig(match1), DeviceConfig(match2), ...]
        drivers: Dict[str, List["ratbag.driver.DeviceConfig"]] = {}
        for f in datafiles:
            supported_devices = [
                DeviceConfig(match, f.driver_options) for match in f.matches
            ]
            drivers[f.driver] = drivers.get(f.driver, []).extend(supported_devices)

        for drivername, configs in drivers.items():
            try:
                self.add_driver(drivername, configs)
            except ratbag.driver.DriverUnavailable as e:
                logger.error(f"{e}")

    def add_driver(
        self, drivername: str, supported_devices: List["ratbag.driver.DeviceConfig"]
    ):
        """
        Add the given driver name. This API exists primarily to support
        testing and niche features, there is rarely a need for calling this
        function. Drivers are handled automatically for known devices.

        :param drivername: The string name of the driver to load
        :param supported_devices: A list of
                    :class:`ratbag.driver.DeviceConfig` instances with the
                    devices supported by this driver.
        :raises ratbag.driver.DriverUnavailable:
        """
        from ratbag.driver import load_driver_by_name

        driverclass = load_driver_by_name(drivername)
        if not driverclass:
            return

        driver = driverclass.new_with_devicelist(self, supported_devices)

        def cb_device_disconnected(device, ratbag):
            logger.info(f"disconnected {device.name}")
            self._devices.remove(device)

        def cb_device_added(driver, device):
            self._devices.append(device)
            device.connect("disconnected", cb_device_disconnected)
            self.emit("device-added", device)

        def cb_rodent_found(driver, rodent):
            rodent.enable_recorder(self._blackbox)

        driver.connect("device-added", cb_device_added)
        if self._blackbox:
            try:
                driver.connect("rodent-found", cb_rodent_found)
            except (AttributeError, TypeError) as e:
                logger.warning(
                    f"Signal 'rodent-found' not available, cannot record: {e}"
                )

    def start(self) -> None:
        """
        Start the context. Before invoking this function ensure the caller has
        connected to all the signals.
        """
        self.emit("start")


@attr.s
class Blackbox:
    """
    The manager class for any recorders active in this session.

    The default recordings directory is
    ``$XDG_STATE_HOME/ratbag/recordings/$timestamp``.
    """

    directory: Path = attr.ib()
    _recorders: List["Recorder"] = attr.ib(init=False, default=attr.Factory(list))

    @directory.validator
    def _directory_check(self, attribute, value):
        if value.exists() and not value.is_dir():
            raise ValueError("Path must be a directory")

    @directory.default
    def _directory_default(self):
        import os
        from datetime.datetime import now

        ts = now.strftime("%Y-%m-%d-%H:%M:%S")
        fallback = Path.home() / ".state"
        statedir = os.environ.get("XDG_STATE_HOME", fallback)
        return statedir / "ratbag" / "recordings" / ts

    def add_recorder(self, recorder: "Recorder"):
        if not self._recorders and not self.directory.exists():
            self.directory.mkdir(exist_ok=True, parents=True)

        self._recorders.append(recorder)

    def make_path(self, filename) -> Path:
        """
        Return a path for ``filename`` that is within this blackbox'
        recordings directory.
        """
        return self.directory / filename

    @classmethod
    def create(cls, directory: Path) -> "Blackbox":
        return cls(directory=directory)


class Recorder(GObject.Object):
    """
    Recorder can be added to a :class:`ratbag.Driver` to log data between the
    host and the device, see :func:`ratbag.Driver.add_recorder`

    :param config: A dictionary with logger-specific data to initialize
    """

    def __init__(self, config: Dict[str, Any] = {}):
        GObject.Object.__init__(self)

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


@attr.s
class CommitTransaction(GObject.Object):
    """
    A helper object for :meth:`Device.commit`. This object keeps track of a
    current commit transaction and emits the ``finished`` signal once the
    driver has completed the transaction.

    A transaction object can only be used once.
    """

    class State(enum.IntEnum):
        NEW = enum.auto()
        IN_USE = enum.auto()
        FAILED = enum.auto()
        SUCCESS = enum.auto()

    _seqno: int = attr.ib(init=False, factory=lambda c=count(): next(c))  # type: ignore
    """
    Unique serial number for this transaction
    """
    _state: State = attr.ib(init=False, default=State.NEW)

    def __attrs_pre_init__(self):
        GObject.Object.__init__(self)

    @classmethod
    def create(cls) -> "CommitTransaction":
        return cls()

    @GObject.Signal()
    def finished(self, *args):
        """
        GObject signal sent when the transaction is complete.
        """
        pass

    @property
    def seqno(self) -> int:
        """
        The unique sequence number for this transaction. This can be used to
        compare transactions.
        """
        return self._seqno

    @property
    def used(self) -> bool:
        """
        True if the transaction has been used in :meth:`Device.commit` (even
        if the transaction is not yet complete).
        """
        return self._state != CommitTransaction.State.NEW

    @property
    def device(self) -> "ratbag.Device":
        """
        The device assigned to this transaction. This property is not
        available until the transaction is used.
        """
        return self._device

    @property
    def success(self) -> bool:
        """
        Returns ``True`` on success. This property is not available unless the
        transaction is complete.
        """
        return self._state == CommitTransaction.State.SUCCESS

    @property
    def is_finished(self) -> bool:
        return self._state in [
            CommitTransaction.State.SUCCESS,
            CommitTransaction.State.FAILED,
        ]

    def mark_as_in_use(self, device: "ratbag.Device"):
        """
        :meta private:
        """
        assert self._state in [CommitTransaction.State.NEW]
        self._state == CommitTransaction.State.IN_USE
        self._device = device

    def complete(self, success: bool):
        """
        Complete this transaction with the given success status.
        """
        if self._state not in [
            CommitTransaction.State.SUCCESS,
            CommitTransaction.State.FAILED,
        ]:
            self._state = (
                CommitTransaction.State.SUCCESS
                if success
                else CommitTransaction.State.FAILED
            )
            self.emit("finished")


@attr.s
class Device(GObject.Object):
    """
    A device as exposed to Ratbag clients. A driver implementation must not
    expose a :class:`ratbag.Device` until it is fully setup and ready to be
    accessed by the client. Usually this means not sending the
    :class:`ratbag.Driver`::``device-added`` signal until the device is
    finalized.

    GObject Signals:

    - ``disconnected``: this device has been disconnected
    - ``commit``: commit the current state to the physical device. This signal
      is used by drivers.
    - ``resync``: callers should re-sync the state of the device
    """

    driver: "ratbag.driver.Driver" = attr.ib()
    path: str = attr.ib()
    name: str = attr.ib()
    """The device name as advertised by the kernel"""
    model: str = attr.ib(default="")
    """The device model, a more precise identifier (where available)"""
    firmware_version: str = attr.ib(default="")
    """
    A device-specific string with the firmware version, or the empty
    string. For devices with a major/minor or purely numeric firmware
    version, the conversion into a string is implementation-defined.
    """

    _profiles: Tuple["Profile", ...] = attr.ib(init=False, default=attr.Factory(tuple))
    _dirty: bool = attr.ib(init=False, default=False)

    @classmethod
    def create(cls, driver: "ratbag.driver.Driver", path: str, name: str, **kwargs):
        permitted = ["firmware_version", "model"]

        filtered = {k: v for k, v in kwargs.items() if k in permitted}
        if filtered.keys() != kwargs.keys():
            logger.error(f"BUG: filtered kwargs down to {filtered}")

        return cls(driver=driver, path=path, name=name, **filtered)

    @GObject.Signal()
    def disconnected(self, *args):
        """
        GObject signal emitted when the device was disconnected
        """
        pass

    @GObject.Signal(name="commit", arg_types=(object,))
    def _commit(self, *args):
        """
        GObject signal emitted when the device was disconnected. This signal
        is for internal use only.

        Name clash with :meth:`commit`
        """
        pass

    @GObject.Signal(arg_types=(object,))
    def resync(self, *args):
        """
        GObject signal emitted when the device state has changed and the
        caller should update its internal state from the device.

        This signal carries a single integer that is the
        :meth:`CommitTransaction.seqno` for the corresponding transaction.
        """
        pass

    def __attrs_pre_init__(self):
        GObject.Object.__init__(self)

    @property
    def profiles(self) -> Tuple["ratbag.Profile", ...]:
        """
        The tuple of device profiles, in-order sorted by profile index.
        """
        # Internally profiles is a dict so we can create them out-of-order if
        # need be but externally it's a tuple because we don't want anyone to
        # modify it.
        return self._profiles

    def commit(self, transaction: Optional[CommitTransaction] = None):
        """
        Write the current changes to the driver. This is an asynchronous
        operation (maybe in a separate thread). Once complete, the
        given transaction object will emit the ``finished`` signal.

            >>> t = CommitTransaction.create()
            >>> def on_finished(transaction):
            ...     print(f"Device {transaction.device} is done")
            >>> signal_number = t.connect("finished", on_finished)
            >>> device.commit(t)  # doctest: +SKIP

        The :attr:`dirty` status of the device's features is reset to
        ``False`` immediately before the callback is invoked but not before
        the driver handles the state changes. In other words, a caller must
        not rely on the :attr:`dirty` status between :meth:`commit` and the
        callback.

        If an error occurs, the driver calls the callback with a ``False``.

        If any device state changes in response to :meth:`commit`, the driver
        emits a ``resync`` signal to notify all other listeners. This signal
        includes the same sequence number as the transaction to allow for
        filtering signals.

        :returns: a sequence number for this transaction
        """
        if transaction is None:
            transaction = CommitTransaction.create()
        elif transaction.used:
            raise ValueError("Transactions cannot be re-used")

        transaction.mark_as_in_use(self)

        GLib.idle_add(self._cb_idle_commit, transaction)

    def _cb_idle_commit(self, transaction: CommitTransaction) -> bool:
        if not self.dirty:
            # well, that was easy
            transaction.complete(True)
            return False  # don't reschedule idle func

        def reset_dirty(transaction: CommitTransaction):
            def clean(x: "ratbag.Feature") -> None:
                x.dirty = False  # type: ignore

            device = transaction.device

            # Now reset all dirty values
            for p in device.profiles:
                map(clean, p.buttons)
                map(clean, p.resolutions)
                map(clean, p.leds)
                p.dirty = False  # type: ignore
            device.dirty = False  # type: ignore
            device.emit("resync", transaction.seqno)
            transaction.disconnect_by_func(reset_dirty)

        transaction.connect("finished", reset_dirty)
        logger.debug("Writing current changes to device")
        self.emit("commit", transaction)

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
            "firmware_version": self.firmware_version,
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

    class Capability(enum.IntEnum):
        """
        Capabilities specific to profiles.
        """

        SET_DEFAULT = 101
        """
        This profile can be set as the default profile. The default profile is
        the one used immediately after the device has been plugged in. If this
        capability is missing, the device typically picks either the last-used
        profile or the first available profile.
        """
        DISABLE = 102
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
        WRITE_ONLY = 103
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
        INDIVIDUAL_REPORT_RATE = 104
        """
        The report rate applies per-profile. On devices without this
        capability changing the report rate on one profile also changes it on
        all other profiles.
        """

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

    @GObject.Property(type=int, default=0, flags=GObject.ParamFlags.READABLE)
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

    @GObject.Property(type=bool, default=True, flags=GObject.ParamFlags.READABLE)
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

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
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
                p.dirty = True  # type: ignore
                p.notify("active")
            self._active = True
            self.dirty = True  # type: ignore
            self.notify("active")

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
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
            "leds": [l.as_dict() for l in self.leds],
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

    class Capability(enum.IntEnum):
        """
        Capabilities specific to resolutions.
        """

        SEPARATE_XY_RESOLUTION = 1
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

    @GObject.Property(type=bool, default=True, flags=GObject.ParamFlags.READABLE)
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled != enabled:
            self._enabled = enabled
            self.notify("enabled")
            self.dirty = True  # type: ignore

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
    def active(self) -> bool:
        """
        ``True`` if this resolution is active, ``False`` otherwise. This
        property should be treated as read-only, use :meth:`set_active`
        instead of writing directly.
        """
        return self._active

    def set_active(self) -> None:
        """
        Set this resolution to be the active resolution.
        """
        if not self.active:
            for r in self.profile.resolutions:
                if r._active:
                    r._active = False
                    r.notify("active")
                    r.dirty = True  # type: ignore
            self._active = True
            self.dirty = True  # type: ignore

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
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

    @GObject.Property(flags=GObject.ParamFlags.READABLE)
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
    class Type(enum.IntEnum):
        NONE = 0
        BUTTON = 1
        SPECIAL = 2
        # KEY is 3 in libratbag
        MACRO = 4
        UNKNOWN = 1000

    def __init__(self):
        GObject.Object.__init__(self)
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

    def __init__(self):
        super().__init__()
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

    def __init__(self, button: int):
        super().__init__()
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

    class Special(enum.IntEnum):
        UNKNOWN = 0x40000000
        DOUBLECLICK = 0x40000001

        WHEEL_LEFT = 0x40000002
        WHEEL_RIGHT = 0x40000003
        WHEEL_UP = 0x40000004
        WHEEL_DOWN = 0x40000005
        RATCHET_MODE_SWITCH = 0x40000006

        RESOLUTION_CYCLE_UP = 0x40000007
        RESOLUTION_CYCLE_DOWN = 0x40000008
        RESOLUTION_UP = 0x40000009
        RESOLUTION_DOWN = 0x4000000A
        RESOLUTION_ALTERNATE = 0x4000000B
        RESOLUTION_DEFAULT = 0x4000000C

        PROFILE_CYCLE_UP = 0x4000000D
        PROFILE_CYCLE_DOWN = 0x4000000E
        PROFILE_UP = 0x4000000F
        PROFILE_DOWN = 0x40000010

        SECOND_MODE = 0x40000011
        BATTERY_LEVEL = 0x40000012

    def __init__(self, special: Special):
        super().__init__()
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

    class Event(enum.IntEnum):
        INVALID = -1
        NONE = 0
        KEY_PRESS = 1
        KEY_RELEASE = 2
        WAIT_MS = 3

    def __init__(
        self,
        name: str = "Unnamed macro",
        events: List[Tuple[Event, int]] = [(Event.INVALID, 0)],
    ):
        super().__init__()
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
        self._action = action or Action()
        self.profile._add_button(self)

    @property
    def types(self) -> Tuple[Action.Type, ...]:
        """
        The list of supported :class:`Action.Type` for this button
        """
        return self._types

    @GObject.Property(
        type=ratbag.Action, default=None, flags=GObject.ParamFlags.READABLE
    )
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
    class Colordepth(enum.IntEnum):
        MONOCHROME = 0
        RGB_888 = 1
        RGB_111 = 2

    class Mode(enum.IntEnum):
        OFF = 0
        ON = 1
        CYCLE = 2
        BREATHING = 3

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

    @GObject.Property(flags=GObject.ParamFlags.READABLE)
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

    @property
    def colordepth(self) -> Colordepth:
        return self._colordepth

    @GObject.Property(type=int, default=0, flags=GObject.ParamFlags.READABLE)
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

    @GObject.Property(type=int, default=0, flags=GObject.ParamFlags.READABLE)
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

    @GObject.Property(flags=GObject.ParamFlags.READABLE)
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

    def as_dict(self) -> Dict[str, Any]:
        """
        Returns this resolution as a dictionary that can e.g. be printed as YAML
        or JSON.
        """
        return {
            "index": self.index,
            "color": list(self.color),
            "colordepth": self.colordepth.name,
            "brightness": self.brightness,
            "mode": self.mode.name,
            "modes": [m.name for m in self.modes],
        }
