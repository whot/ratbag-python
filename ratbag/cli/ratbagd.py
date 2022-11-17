#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

from dbus_next import BusType, Variant, PropertyAccess, DBusError
from dbus_next.glib import MessageBus
from dbus_next.service import ServiceInterface, method, dbus_property, signal
from pathlib import Path
from gi.repository import GLib
from typing import List

import attr
import argparse
import datetime
import dbus_next
import logging
import sys
import os

import ratbag

logger = logging.getLogger("ratbagd")

PATH_PREFIX = "/org/freedesktop/ratbag1"
NAME_PREFIX = "org.freedesktop.ratbag1"

# Replacements in here: {console_log_level}, {log_level}, {log_file}
log_config = """
version: 1
formatters:
  simple:
    format: '%(levelname).1s|%(name)s: %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    level: {console_log_level}
    formatter: simple
    stream: ext://sys.stdout
  file:
    class: logging.handlers.RotatingFileHandler
    formatter: simple
    level: {log_level}
    filename: {log_file}
    maxBytes: 4194304
    backupCount: 5
root:
    level: DEBUG
    handlers: [console, file]
"""


@attr.s
class LogLevels(object):
    console: int = attr.ib()
    file: int = attr.ib()

    @classmethod
    def from_args(cls, console: str, file: str):
        map = {
            "disabled": logging.NOTSET,
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        return cls(map[console], map[file])


def init_logger(levels: LogLevels, logdir: Path) -> None:
    import yaml
    import logging.config

    logfile = logdir / "ratbagd.log"

    yml = yaml.safe_load(
        log_config.format(
            console_log_level=levels.console, log_level=levels.file, log_file=logfile
        )
    )
    logging.config.dictConfig(yml)


def make_name(name: str) -> str:
    """
    Creates the interface name based on the suffix given
    """
    assert name in (
        "Manager",
        "Device",
        "Profile",
        "Resolution",
        "Led",
        "Button",
        "ValueError",
    )
    return f"{NAME_PREFIX}.{name}"


def make_path(*args) -> str:
    """
    Creates an object path based on the args given
    """
    items = args
    return f"{PATH_PREFIX}/{'/'.join([str(i) for i in items])}"


class RatbagResolution(ServiceInterface):
    def __init__(self, bus, ratbag_resolution):
        super().__init__(make_name("Resolution"))
        self._resolution = ratbag_resolution
        self._bus = bus
        self.objpath = make_path(
            "device",
            ratbag_resolution.profile.device.path.name,
            "p",
            ratbag_resolution.profile.index,
            "r",
            ratbag_resolution.index,
        )
        bus.export(self.objpath, self)

    @dbus_property(access=PropertyAccess.READ)
    def Index(self) -> "u":  # type: ignore
        return self._resolution.index

    @dbus_property(access=PropertyAccess.READ)
    def IsActive(self) -> "b":  # type: ignore
        return self._resolution.active

    @dbus_property(access=PropertyAccess.READ)
    def IsDefault(self) -> "b":  # type: ignore
        return self._resolution.default

    @dbus_property(access=PropertyAccess.READ)
    def Resolutions(self) -> "au":  # type: ignore
        return list(self._resolution.dpi_list)

    @dbus_property(access=PropertyAccess.READWRITE)
    def Resolution(self) -> "v":  # type: ignore
        # Note: the dbus interface allows for either a single "u" or "(uu)" if
        # separate resolutions are possible. This was a bad design choice
        # since it's easier to just compare x==y than working around different
        # variant types. For now we just always send (uu) which should work
        # with Piper, eventually we should bump the version though.
        return Variant("(uu)", list(self._resolution.dpi))

    @Resolution.setter  # type: ignore
    def Resolution(self, res: "v"):  # type: ignore
        # See the comment in Resolution above
        if res.type.signature == "u":
            x = res.value
            y = x
        elif res.type.signature == "(uu)":
            x, y = res.value
        else:
            raise DBusError(make_name("ValueError"), "Resolution must be (uu)")
        self._resolution.set_dpi((x, y))
        self.emit_properties_changed(
            {"Resolution": Variant("(uu)", list(self._resolution.dpi))}
        )

    @method()
    def SetActive(self) -> "u":  # type: ignore
        self._resolution.set_active()
        self.emit_properties_changed(
            {"IsActive": True},
        )
        return 0

    @method()
    def SetDefault(self) -> "u":  # type: ignore
        self._resolution.set_default()
        self.emit_properties_changed(
            {"IsDefault": True},
        )
        return 0


class RatbagLed(ServiceInterface):
    def __init__(self, bus, ratbag_led):
        super().__init__(make_name("Led"))
        self._led = ratbag_led
        self._bus = bus
        self.objpath = make_path(
            "device",
            ratbag_led.profile.device.path.name,
            "p",
            ratbag_led.profile.index,
            "l",
            ratbag_led.index,
        )
        bus.export(self.objpath, self)

    @dbus_property(access=PropertyAccess.READ)
    def Index(self) -> "u":  # type: ignore
        return self._led.index

    @dbus_property(access=PropertyAccess.READWRITE)
    def Mode(self) -> "u":  # type: ignore
        return self._led.mode

    @Mode.setter  # type: ignore
    def Mode(self, mode: "u"):  # type: ignore
        modes = {
            0: ratbag.Led.Mode.OFF,
            1: ratbag.Led.Mode.ON,
            2: ratbag.Led.Mode.CYCLE,
            3: ratbag.Led.Mode.BREATHING,
        }
        self._led.set_mode(modes[mode])
        self.emit_properties_changed({"Mode": modes[mode]})

    @dbus_property(access=PropertyAccess.READ)
    def Modes(self) -> "au":  # type: ignore
        return list(self._led.modes)  # FIXME

    @dbus_property(access=PropertyAccess.READWRITE)
    def Color(self) -> "(uuu)":  # type: ignore
        return list(self._led.color)  # FIXME

    @Color.setter  # type: ignore
    def Color(self, color: "(uuu)"):  # type: ignore
        r, g, b = color
        self._led.set_color((r, g, b))
        self.emit_properties_changed({"Color": (r, g, b)})

    @dbus_property(access=PropertyAccess.READ)
    def ColorDepth(self) -> "u":  # type: ignore
        return self._led.colordepth  # FIXME

    @dbus_property(access=PropertyAccess.READWRITE)
    def EffectDuration(self) -> "u":  # type: ignore
        return self._led.effect_duration

    @EffectDuration.setter  # type: ignore
    def EffectDuration(self, duration: "u"):  # type: ignore
        self._led.set_effect_duration(duration)
        self.emit_properties_changed({"EffectDuration": duration})

    @dbus_property(access=PropertyAccess.READWRITE)
    def Brightness(self) -> "u":  # type: ignore
        return self._led.brightness

    @Brightness.setter  # type: ignore
    def Brightness(self, brightness: "u"):  # type: ignore
        self._led.set_brightness(brightness)
        self.emit_properties_changed({"Brightness": brightness})


class RatbagButton(ServiceInterface):
    def __init__(self, bus, ratbag_button):
        super().__init__(make_name("Button"))
        self._button = ratbag_button
        self._bus = bus
        self.objpath = make_path(
            "device",
            ratbag_button.profile.device.path.name,
            "p",
            ratbag_button.profile.index,
            "b",
            ratbag_button.index,
        )
        bus.export(self.objpath, self)

    @dbus_property(access=PropertyAccess.READ)
    def Index(self) -> "u":  # type: ignore
        return self._button.index

    @dbus_property(access=PropertyAccess.READWRITE)
    def Mapping(self) -> "(uv)":  # type: ignore
        action = self._button.action
        value = None

        if action.type == ratbag.Action.Type.BUTTON:
            value = dbus_next.Variant("u", int(action.button))
        elif action.type == ratbag.Action.Type.SPECIAL:
            value = dbus_next.Variant("u", int(action.special))
        # elif action.type == ratbag.Action.Type.KEY:
        #    value = dbus_next.Variant("u", int(ratbag.Action.Type.UNKNOWN))  # FIXME
        elif action.type == ratbag.Action.Type.MACRO:
            value = dbus_next.Variant(
                "a(uu)", [[e[0].value, e[1]] for e in action.events]
            )
        else:
            value = dbus_next.Variant("u", int(ratbag.Action.Type.UNKNOWN))

        assert value is not None
        return [action.type.value, value]

    @Mapping.setter  # type: ignore
    def Mapping(self, mapping: "(uv)"):  # type: ignore
        type = mapping[0]
        variant = mapping[1]

        if type == int(ratbag.Action.Type.BUTTON):
            action = ratbag.ActionButton(self._button, variant.value)
        elif action.type == ratbag.Action.Type.SPECIAL:
            action = ratbag.ActionSpecial(
                self._button, ratbag.ActionSpecial.Special(variant.value)
            )
        # if action.type == ratbag.Action.Type.KEY:
        #    action = None  # FIXME
        if action.type == ratbag.Action.Type.MACRO:
            events = [(ratbag.ActionMacro.Event(t), v) for t, v in variant.value]
            action = ratbag.ActionMacro(self._button, events=events)
        self._button.set_action(action)

    @dbus_property(access=PropertyAccess.READ)
    def ActionTypes(self) -> "au":  # type: ignore
        return [t.value for t in self._button.types]

    @method()
    def Disable(self) -> "u":  # type: ignore
        # FIXME
        return 0


class RatbagProfile(ServiceInterface):
    def __init__(self, bus, ratbag_profile):
        super().__init__(make_name("Profile"))
        self._profile = ratbag_profile
        self._bus = bus
        self.objpath = make_path(
            "device", ratbag_profile.device.path.name, "p", ratbag_profile.index
        )
        self._resolutions = [
            RatbagResolution(bus, r) for r in ratbag_profile.resolutions
        ]
        self._buttons = [RatbagButton(bus, r) for r in ratbag_profile.buttons]
        self._leds = [RatbagLed(bus, r) for r in ratbag_profile.leds]
        bus.export(self.objpath, self)

    @dbus_property(access=PropertyAccess.READ)
    def Index(self) -> "u":  # type: ignore
        return self._profile.index

    @dbus_property(access=PropertyAccess.READ)
    def Name(self) -> "s":  # type: ignore
        return self._profile.name or f"Profile {self._profile.index}"

    @dbus_property(access=PropertyAccess.READ)
    def Capabilities(self) -> "au":  # type: ignore
        mapping = {
            ratbag.Profile.Capability.SET_DEFAULT: 101,
            ratbag.Profile.Capability.DISABLE: 102,
            ratbag.Profile.Capability.WRITE_ONLY: 103,
            ratbag.Profile.Capability.INDIVIDUAL_REPORT_RATE: 103,
        }
        return [mapping[c] for c in self._profile.capabilities]

    @dbus_property(access=PropertyAccess.READWRITE)
    def Enabled(self) -> "b":  # type: ignore
        return self._profile.enabled

    @Enabled.setter  # type: ignore
    def Enabled(self, enabled: "b"):  # type: ignore
        self._profile.set_enabled(enabled)

    @dbus_property(access=PropertyAccess.READ)
    def ReportRates(self) -> "au":  # type: ignore
        return list(self._profile.report_rates)

    @dbus_property(access=PropertyAccess.READWRITE)
    def ReportRate(self) -> "u":  # type: ignore
        return self._profile.report_rate

    @ReportRate.setter  # type: ignore
    def ReportRate(self, rate: int):  # type: ignore
        self._profile.report_rate = rate

    @dbus_property(access=PropertyAccess.READ)
    def IsActive(self) -> "b":  # type: ignore
        return self._profile.active

    @dbus_property(access=PropertyAccess.READ)
    def IsDefault(self) -> "b":  # type: ignore
        return self._profile.default

    @dbus_property(access=PropertyAccess.READ)
    def Resolutions(self) -> "ao":  # type: ignore
        return [r.objpath for r in self._resolutions]

    @dbus_property(access=PropertyAccess.READ)
    def Buttons(self) -> "ao":  # type: ignore
        return [b.objpath for b in self._buttons]

    @dbus_property(access=PropertyAccess.READ)
    def Leds(self) -> "ao":  # type: ignore
        return [l.objpath for l in self._leds]

    @method()
    def SetActive(self) -> "u":  # type: ignore
        self._profile.set_active()
        self.emit_properties_changed(
            {"IsActive": True},
        )
        return 0

    @method()
    def SetDefault(self) -> "u":  # type: ignore
        self._profile.set_default()
        return 0


class RatbagdDevice(ServiceInterface):
    def __init__(self, bus, ratbag_device):
        super().__init__(make_name("Device"))
        self._device = ratbag_device
        self._bus = bus
        self.objpath = make_path("device", ratbag_device.path.name)
        self._profiles = list(RatbagProfile(bus, p) for p in ratbag_device.profiles)
        bus.export(self.objpath, self)

    @dbus_property(access=PropertyAccess.READ)
    def Name(self) -> "s":  # type: ignore
        return self._device.name

    @dbus_property(access=PropertyAccess.READ)
    def Model(self) -> "s":  # type: ignore
        return self._device.model

    @dbus_property(access=PropertyAccess.READ)
    def Profiles(self) -> "ao":  # type: ignore
        return [p.objpath for p in self._profiles]

    @method()
    def Commit(self) -> "u":  # type: ignore
        logger.debug(f"Committing state to {self._device.name}")
        self._device.commit()
        return 0

    @signal()
    def Resync(self) -> None:
        logger.debug(f"Signal resync for  {self._device.name}")


class RatbagdManager(ServiceInterface):
    def __init__(self, bus, ratbag: ratbag.Ratbag):
        super().__init__(make_name("Manager"))
        self._devices: List[RatbagdDevice] = []
        self._ratbag = ratbag
        self._bus = bus
        ratbag.connect("device-added", self.cb_device_added)
        bus.export(PATH_PREFIX, self)

    @dbus_property(access=PropertyAccess.READ)
    def APIVersion(self) -> "i":  # type: ignore
        return 1

    @dbus_property(access=PropertyAccess.READ)
    def Devices(self) -> "ao":  # type: ignore
        return [d.objpath for d in self._devices]

    def cb_device_added(self, ratbag: ratbag.Ratbag, device: ratbag.Device):
        logger.info(f"exporting device {device.name}")
        self._devices.append(RatbagdDevice(self._bus, device))


class Ratbagd(object):
    def __init__(self, ratbag: ratbag.Ratbag):
        self.ratbag = ratbag
        self.busname = None

    def init_dbus(self, busname=NAME_PREFIX, use_system_bus=True):
        self.busname = busname
        bus_type = BusType.SYSTEM if use_system_bus else BusType.SESSION
        self.bus = MessageBus(bus_type=bus_type).connect_sync()
        logger.debug(f"Requesting bus name '{self.busname}'")
        self.bus.request_name_sync(self.busname, dbus_next.NameFlag.REPLACE_EXISTING)
        self.manager = RatbagdManager(self.bus, self.ratbag)

    def start(self):
        self.ratbag.start()


def init_logdir(path):
    xdg = path or os.getenv("XDG_STATE_HOME")
    if not xdg:
        if os.getuid() != 0:
            xdg = Path.home() / ".local" / "state"
        else:
            xdg = Path("/") / "var" / "log"
    basedir = Path(xdg) / "ratbagd"
    logdir = basedir / datetime.datetime.now().strftime("%y-%m-%d-%H%M%S")
    logdir.mkdir(exist_ok=True, parents=True)

    latest = basedir / "latest"
    if latest.is_symlink() or not latest.exists():
        latest.unlink(missing_ok=True)
        latest.symlink_to(logdir)

    return logdir


desc = """
This daemon needs sufficient privileges to access the devices and own the DBus
name. This usually means it needs to be run as root.

Log files and recordings of devices are stored in $XDG_STATE_HOME/ratbagd by
default (or /var/log/ratbagd if run as root). The recordings contain all
interactions of ratbagd with the device - this does not usually include
sensitive data.
"""


def main():
    parser = argparse.ArgumentParser(
        description="A ratbag DBus daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=desc,
    )
    parser.add_argument(
        "--disable-recordings",
        default=False,
        action="store_true",
        help="Disable device recordings",
    )
    parser.add_argument(
        "--logdir",
        type=Path,
        default=None,
        help="Directory to store log files and recordings in",
    )
    parser.add_argument(
        "--console-log-level",
        default="info",
        choices=["disabled", "debug", "info", "warning", "error", "critical"],
        help="Log level for stdout logging",
    )
    parser.add_argument(
        "--log-level",
        default="debug",
        choices=["disabled", "debug", "info", "warning", "error", "critical"],
        help="Log level for log file logging",
    )

    ns = parser.parse_args()
    logdir = init_logdir(ns.logdir)
    levels = LogLevels.from_args(ns.console_log_level, ns.log_level)
    init_logger(levels, logdir)
    kwargs = {}
    if not ns.disable_recordings:
        blackbox = ratbag.Blackbox.create(directory=logdir)
        kwargs["blackbox"] = blackbox
    rb = ratbag.Ratbag.create(**kwargs)
    ratbagd = Ratbagd(rb)
    try:
        ratbagd.init_dbus()
    except DBusError as e:
        print(
            f"Failed to own bus name {ratbagd.busname}: {e}. Another ratbagd may be running. Exiting."
        )
        sys.exit(1)

    ratbagd.start()

    try:
        mainloop = GLib.MainLoop()
        mainloop.run()
    except KeyboardInterrupt:
        pass
