#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import attr
import click
import logging
import logging.config
import os
import re
import sys
import yaml

from typing import Any, Dict, List, Optional

try:
    from gi.repository import GLib
except ImportError:
    print(
        "GObject introspection packages missing. See https://pygobject.readthedocs.io/en/latest/getting_started.html",
        file=sys.stderr,
    )
    sys.exit(1)

from pathlib import Path


import ratbag

import ratbag.emulator
import ratbag.recorder

# mypy doesn't like late initializations
logger: logging.Logger = None  # type: ignore


@attr.s
class Config(object):
    """
    Abstraction of a device configuration file. Note that this is specific to
    the ratbagcli tool only, device configuration is not handled by ratbag
    itself.

    So all the parsing, etc. is done here and then applied to the various
    ratbag objects.
    """

    class Error(Exception):
        pass

    matches: List[str] = attr.ib(init=False, default=attr.Factory(list))
    profiles: List[Dict[str, Any]] = attr.ib(init=False, default=attr.Factory(list))

    @classmethod
    def create_from_file(cls, filename: Path):
        obj = cls()
        with open(filename) as fd:
            yml = yaml.safe_load(fd)
            obj.parse(yml)
        return obj

    def parse(self, yml):
        self.matches = yml.get("matches", [])
        self.profiles = yml.get("profiles", [])
        if not self.profiles:
            raise Config.Error("Missing 'profiles' array")

        # verify the config and switch a few things to be more useful:
        # - index and report_rate are converted to int
        # - button special are converted to the ratbag.ActionSpecial type
        # - resolution dpi is converted to an int tuple
        for pidx, p in enumerate(self.profiles):
            if "index" not in p:
                raise Config.Error(f"Profile entry {pidx+1} has no 'index'")
            p["index"] = int(p["index"])
            pidx = p["index"]
            if not p.get("disable", True):
                raise Config.Error(f"Profile {pidx}: disable must be 'true'")

            report_rate = p.get("report-rate", None)
            if report_rate is not None:
                try:
                    p["report-rate"] = int(report_rate)
                except ValueError:
                    raise Config.Error(
                        f"Profile {pidx}: invalid report rate {report_rate}"
                    )

            # Buttons
            for bidx, b in enumerate(p.get("buttons", [])):
                if "index" not in b:
                    raise Config.Error(
                        f"Button entry {bidx+1}, profile {pidx} has no 'index'"
                    )
                b["index"] = int(b["index"])
                bidx = b["index"]
                if not b.get("disable", True):
                    raise Config.Error(f"Button {pidx}.{bidx}: disable must be 'true'")

                button = b.get("button", None)
                if button:
                    try:
                        b["button"] = int(button)
                    except ValueError:
                        raise Config.Error(
                            f"Button {pidx}.{bidx}: invalid button number {button}"
                        )

                special = b.get("special", None)
                if special:
                    name = special.replace("-", "_").upper()
                    try:
                        b["special"] = ratbag.ActionSpecial.Special[name]
                    except KeyError:
                        raise Config.Error(
                            f"Button {pidx}.{bidx}: unknown special action {special}"
                        )

                macro = b.get("macro", {})
                if macro and "entries" not in macro:
                    raise Config.Error(f"Button {pidx}.{bidx}: macro needs 'entries'")
                for entry in macro.get("entries", []):
                    if not re.match("[+-t][0-9]+", entry):
                        raise Config.Error(
                            f"Button {pidx}.{bidx}: invalid macro entry {entry}"
                        )

                if list(map(bool, [button, special, macro])).count(True) > 1:
                    raise Config.Error(
                        f"Button {pidx}.{bidx}: only one of button, special or macro allowed"
                    )

            # Resolutions
            for ridx, r in enumerate(p.get("resolutions", [])):
                if "index" not in r:
                    raise Config.Error(
                        f"Resolution entry {ridx+1}, profile {pidx} has no 'index'"
                    )
                r["index"] = int(r["index"])
                ridx = r["index"]
                if not r.get("disable", True):
                    raise Config.Error(
                        f"Resolution {pidx}.{ridx}: disable must be 'true'"
                    )
                dpis = r.get("dpis", None)
                if dpis is not None:
                    if len(dpis) != 2:
                        raise Config.Error(
                            f"Resolution {pidx}.{ridx}: dpi must an (x, y) tuple"
                        )
                    else:
                        try:
                            map(int, dpis)
                        except ValueError:
                            raise Config.Error(
                                f"Resolution {pidx}.{ridx}: dpi must an (x, y) tuple"
                            )

    def _matches(self, device):
        if not self.matches:
            return True

        for m in self.matches:
            if m["name"] and device.name == m["name"]:
                return True

        return False

    def apply(self, device: ratbag.Device, nocommit: bool = False):
        """
        Apply this configuration to the given device.

        If nocommit is True, the config is applied to the virtual device but
        not "committed" to the device itself.
        """
        if not self._matches(device):
            return

        for pconf in self.profiles:
            pidx = pconf["index"]
            try:
                profile = device.profiles[pidx]
            except IndexError:
                logger.warning(
                    f"Config references nonexisting profile {pidx}. Skipping"
                )
                continue

            logger.info(f"Config found for profile {profile.index}")

            # Disabling is handled first, it discards all other config for that
            # profile
            if pconf.get("disable", False):
                logger.info(f"Disabling profile {profile.index}")
                profile.enabled = False
                continue

            report_rate = pconf.get("report-rate", None)
            if report_rate is not None:
                logger.info(f"Report rate for {profile.index} is now {report_rate}")
                profile.set_report_rate(report_rate)

            # Resolutions
            for rconf in pconf.get("resolutions", []):
                ridx = rconf["index"]
                try:
                    resolution = profile.resolutions[ridx]
                except IndexError:
                    logger.warning(
                        f"Config references nonexisting resolution {pidx}.{ridx}. Skipping"
                    )
                    continue
                logger.info(
                    f"Config found for resolution {profile.index}.{resolution.index}"
                )
                if rconf.get("disable", False):
                    logger.info(
                        f"Disabling resolution {profile.index}.{resolution.index}"
                    )
                    resolution.enabled = False
                    continue
                dpis = rconf.get("dpi", None)
                if dpis:
                    resolution.enabled = True
                    resolution.set_dpi(dpis)

            # Buttons
            for bconf in pconf.get("buttons", []):
                bidx = bconf["index"]
                try:
                    button = profile.buttons[bidx]
                except IndexError:
                    logger.warning(
                        f"Config references nonexisting button {pidx}.{bidx}. Skipping"
                    )
                    continue
                logger.info(f"Config found for button {profile.index}.{button.index}")

                # Disabling is handled first, it discards all other config for that
                # button
                if bconf.get("disable", False):
                    logger.info(f"Disabling button {profile.index}.{button.index}")
                    button.set_action(ratbag.ActionNone(button))
                    continue

                # Button numbers
                bnumber = bconf.get("button", 0)
                if bnumber > 0:
                    logger.info(
                        f"Button {profile.index}.{button.index} sends button {bnumber}"
                    )
                    button.set_action(ratbag.ActionButton(button, bnumber))
                    continue

                # Button special
                special = bconf.get("special", None)
                if special:
                    logger.info(
                        f"Button {profile.index}.{button.index} sends special {special.name}"
                    )
                    button.set_action(ratbag.ActionSpecial(button, special))
                    continue

                # Button macro
                macro = bconf.get("macro", {})
                if macro:
                    lut = {
                        "t": ratbag.ActionMacro.Event.WAIT_MS,
                        "+": ratbag.ActionMacro.Event.KEY_PRESS,
                        "-": ratbag.ActionMacro.Event.KEY_RELEASE,
                    }
                    events = [
                        (lut[entry[0]], int(entry[1:])) for entry in macro["entries"]
                    ]
                    name = macro.get("name", "macro {profile.index}.{button.index}")
                    logger.info(
                        f"Button {profile.index}.{button.index} macro {str(events)}"
                    )
                    button.set_action(ratbag.ActionMacro(button, name, events))
                    continue

        if not nocommit:

            def cb_commit_finished(transaction):
                if not transaction.success:
                    logger.error(
                        f"Failed to write changes to device {transaction.device.name}"
                    )
                else:
                    logger.debug("done")

            transaction = ratbag.CommitTransaction.create(device)
            transaction.connect("finished", cb_commit_finished)

            transaction.commit()
            logger.debug("Waiting for device to commit")

    def verify(self, device):
        logger.info(f"Verifying config against {device.name}")
        if not self._matches(device):
            return

        def err_non_existing(what, pidx, fidx=None):
            if fidx is not None:
                idx = f"{pidx}.{fidx}"
            else:
                idx = f"{pidx}"
            click.secho(f"Config references nonexisting {what} {idx}", fg="blue")

        def err_differs(what, pidx, fidx, item, expected, got):
            what = what.capitalize()
            if fidx is not None:
                idx = f"{pidx}.{fidx}"
            else:
                idx = f"{pidx}"
            click.secho(f"{what} {idx} {item} expected {expected}, is {got}", fg="red")

        def err_is_enabled(what, pidx, fidx=None):
            err_differs(what, pidx, fidx, "", "disabled", "enabled")

        for pconf in self.profiles:
            pidx = pconf["index"]
            try:
                profile = device.profiles[pidx]
            except IndexError:
                err_non_existing("profile", pidx)
                continue

            if pconf.get("disable", False) and profile.enabled:
                err_is_enabled("profile", pidx)

            report_rate = pconf.get("report-rate", profile.report_rate)
            if report_rate != profile.report_rate:
                err_differs(
                    "profile",
                    pidx,
                    None,
                    "report-rate",
                    pconf["report-rate"],
                    profile.report_rate,
                )

            for rconf in pconf.get("resolutions", []):
                ridx = rconf["index"]
                try:
                    resolution = profile.resolutions[ridx]
                except IndexError:
                    err_non_existing("resolution", pidx, ridx)
                    continue

                if rconf.get("disable", False) and resolution.enabled:
                    err_is_enabled("resolution", pidx, ridx)
                    continue

                dpis = rconf.get("dpi", None)
                if dpis and tuple(dpis) != resolution.dpi:
                    err_differs(
                        "resolution",
                        pidx,
                        ridx,
                        "dpi",
                        tuple(dpis),
                        tuple(resolution.dpi),
                    )

            for bconf in pconf.get("buttons", []):
                bidx = bconf["index"]
                try:
                    button = profile.buttons[bidx]
                except IndexError:
                    err_non_existing("button", pidx, bidx)
                    continue

                if (
                    bconf.get("disable", False)
                    and button.action.type != ratbag.Action.Type.NONE
                ):
                    err_is_enabled("button", pidx, bidx)
                    continue

                bstring = {
                    ratbag.Action.Type.NONE: lambda b: "disabled",
                    ratbag.Action.Type.UNKNOWN: lambda b: "unknown",
                    ratbag.Action.Type.BUTTON: lambda b: f"button {b.action.button}",
                    ratbag.Action.Type.SPECIAL: lambda b: f"special {b.action.special.name}",
                    ratbag.Action.Type.MACRO: lambda b: f"macro {str(b.action.macro)}",
                }[button.action.type](button)

                # Button numbers
                bnumber = bconf.get("button", 0)
                if bnumber > 0 and button.action != ratbag.ActionButton(None, bnumber):
                    err_differs("button", pidx, bidx, "button", bnumber, bstring)
                    continue

                special = bconf.get("special", None)
                if special and button.action != ratbag.ActionSpecial(None, special):
                    err_differs("button", pidx, bidx, "special", special, bstring)
                    continue

                macro = bconf.get("macro", {})
                # FIXME: duplicated from apply()
                if macro:
                    lut = {
                        "t": ratbag.ActionMacro.Event.WAIT_MS,
                        "+": ratbag.ActionMacro.Event.KEY_PRESS,
                        "-": ratbag.ActionMacro.Event.KEY_RELEASE,
                    }
                    events = [
                        (lut[entry[0]], int(entry[1:])) for entry in macro["entries"]
                    ]

                    if button.action != ratbag.ActionMacro(
                        None, name=None, events=events
                    ):
                        err_differs("button", pidx, bidx, "macro", events, bstring)
                        continue


def _init_logger_config(conf: Optional[Path]) -> None:
    """
    Initialize the logging configuration based on a logger config file
    """
    conf = conf or Path("config-logger.yml")
    if not conf.exists():
        xdg = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        conf = xdg / "ratbag" / "config-logger.yml"
    if Path(conf).exists():
        with open(conf) as fd:
            yml = yaml.safe_load(fd)
        logging.config.dictConfig(yml)
    else:
        _init_logger(verbose=False)


def _init_logger(verbose: bool) -> None:
    """
    Initialize the logging configuration based on a verbosity level
    """
    lvl = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(levelname)s: %(name)s: %(message)s", level=lvl)


def _init_emulators(infile):
    return [ratbag.emulator.YamlEmulator(infile)]


@click.group()
@click.option("--verbose", count=True, help="Enable debug logging")
@click.option("--quiet", is_flag=True, help="Disable debug logging")
@click.option(
    "--log-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the logger config file",
)
@click.option(
    "--record",
    help="Path to the directory to collect recordings in",
    type=click.Path(dir_okay=True, path_type=Path),
)
@click.option(
    "--replay",
    help="Path to the device recording",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.pass_context
def ratbagcli(
    ctx, verbose: int, quiet: bool, log_config: Path, record: Path, replay: Path
):
    global logger

    if quiet:
        _init_logger(verbose=False)
    elif verbose >= 1:
        _init_logger(verbose=True)
    else:
        _init_logger_config(log_config)

    logger = logging.getLogger("ratbagcli")

    ctx.obj = {}
    ctx.obj["blackbox"] = ratbag.Blackbox.create(
        directory=record or ratbag.Blackbox.default_recordings_directory()
    )
    if replay:
        ctx.obj["emulators"] = _init_emulators(replay)


@ratbagcli.command(name="apply-config")
@click.option(
    "--nocommit", type=bool, is_flag=True, help="Never invoke commit() on the device"
)
@click.argument("config", type=click.Path(exists=True, dir_okay=False))
@click.argument("name", required=False)
@click.pass_context
def ratbagcli_apply_config(ctx, nocommit: bool, config: Path, name: Optional[str]):
    """
    Apply the given config to the device.

    If the --nocommit option is given, the configuration is applied to the
    virtual device but not actually sent to the physical device.

    If a device name is given, only devices with that name are
    configured. The name may be a part of the name, e.g. "G303" matches the
    "Logitech G303" device.
    """
    try:
        user_config = Config.create_from_file(filename=config)
    except Config.Error as e:
        click.secho(f"Config error in {config}: {str(e)}. Aborting", fg="red")
        sys.exit(1)

    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag.create(blackbox=ctx.obj.get("blackbox", None))
        for emulator in ctx.obj.get("emulators", []):
            emulator.setup()

        def cb_device_added(ratbagcli, device):
            if name is None or name in device.name:
                user_config.apply(device, nocommit)
                GLib.idle_add(lambda: mainloop.quit())

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        GLib.timeout_add(1000, lambda: mainloop.quit())
        mainloop.run()
    except KeyboardInterrupt:
        pass


@ratbagcli.command(name="verify-config")
@click.argument("config", type=click.Path(), required=True)
@click.argument("name", type=str, required=False)
@click.pass_context
def ratbagcli_verify_config(ctx, config: Path, name: Optional[str]):
    """
    Compare differences between the given config and the current configuration
    stored on the device.

    If a device name is given, only devices with that name are
    verified. The name may be a part of the name, e.g. "G303" matches the
    "Logitech G303" device.
    """
    try:
        user_config = Config.create_from_file(filename=config)
    except Config.Error as e:
        click.secho(f"Config error in {config}: {str(e)}. Aborting", fg="red")
        sys.exit(1)

    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag.create(blackbox=ctx.obj.get("blackbox", None))
        for emulator in ctx.obj.get("emulators", []):
            emulator.setup()

        def cb_device_added(ratbagcli, device):
            if name is None or name in device.name:
                user_config.verify(device)
                GLib.idle_add(lambda: mainloop.quit())

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        GLib.timeout_add(1000, lambda: mainloop.quit())
        mainloop.run()
    except KeyboardInterrupt:
        pass


@ratbagcli.command(name="show")
@click.argument("name", required=False)
@click.pass_context
def ratbagcli_show(ctx, name: str):
    """
    Show current configuration of a device

    If a device name is given, only devices with that name are
    shown. The name may be a part of the name, e.g. "G303" matches the
    "Logitech G303" device.
    """
    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag.create(blackbox=ctx.obj.get("blackbox", None))
        for e in ctx.obj.get("emulators", []):
            e.setup()

        def cb_device_added(ratbagcli, device):
            if name is None or name in device.name:
                device_dict = {"devices": [device.as_dict()]}
                click.echo(yaml.dump(device_dict, default_flow_style=None))

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        GLib.timeout_add(1000, lambda: mainloop.quit())
        mainloop.run()
    except KeyboardInterrupt:
        pass


@ratbagcli.command(name="list")
@click.pass_context
def ratbagcli_list(ctx):
    """
    List all connected supported devices

    If a device name is given, only devices with that name are
    listed. The name may be a part of the name, e.g. "G303" matches the
    "Logitech G303" device.

    The device must be accessible to the user running this command, in many
    cases this requires the command to be run as root.

    If a device is currently connected but not listed, it is not (yet)
    supported by ratbag.
    """
    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag.create(blackbox=ctx.obj.get("blackbox", None))
        for e in ctx.obj.get("emulators", []):
            e.setup()

        devices = []

        def cb_device_added(ratbagcli, device, devices):
            if not devices:
                click.echo("devices:")
                devices.append(device)
            click.echo(f"- name: {device.name}")

        ratbagd.connect("device-added", cb_device_added, devices)
        ratbagd.start()

        GLib.timeout_add(1000, lambda: mainloop.quit())
        mainloop.run()

        if not devices:
            click.echo("# No supported devices available")
    except KeyboardInterrupt:
        pass


@ratbagcli.command(name="list-supported-devices")
@click.pass_context
def ratbagcli_list_supported(ctx):
    """
    List all known devices. The output of this command is YAML-compatible and
    can be processed with the appropriate tools.
    """
    from ratbag.util import load_data_files

    click.echo("# The following devices are known to ratbag.")
    click.echo("# A device may have multiple entries, one for each USB ID.")
    click.echo("# This list is sorted by device name.")

    devices = []

    files = load_data_files()
    for f in sorted(files, key=lambda x: x.name):
        if not devices:
            click.echo("devices:")
            devices.append(f)

        for match in f.matches:

            def q(s):
                return f"'{s}'"

            click.echo(
                f" - {{ match: {q(match):>22s}, driver: {q(f.driver):>20s}, name: '{f.name}' }}"
            )

    if not devices:
        click.echo("# No supported devices found. This is an installation issue")


@ratbagcli.command(name="help")
@click.pass_context
def ratbagcli_help(ctx):
    """
    Print this help output.
    """
    click.echo(ratbagcli.get_help(ctx))


if __name__ == "__main__":
    ratbagcli()
