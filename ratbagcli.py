#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import argparse
import logging
import logging.config
import os
import re
import sys
import yaml

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

logger = None


class Config(object):
    class Error(Exception):
        pass

    def __init__(self, filename, nocommit=False):
        # An empty config object so we don't have to ifdef the caller
        self.empty = filename is None
        if self.empty:
            return

        self.nocommit = nocommit

        with open(filename) as fd:
            yml = yaml.safe_load(fd)
        self._parse(yml)

    def _parse(self, yml):
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

    def apply(self, device):
        if self.empty or not self._matches(device):
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

        if not self.nocommit:

            def cb_commit_complete(device, success, cookie):
                if not success:
                    logger.error("Failed to write changes to the device")
                else:
                    logger.debug("done")

            device.commit(callback=cb_commit_complete)
            logger.debug("Waiting for device to commit")

    def verify(self, device):
        logger.info(f"Verifying config against {device.name}")
        if self.empty or not self._matches(device):
            return

        for pconf in self.profiles:
            pidx = pconf["index"]
            try:
                profile = device.profiles[pidx]
            except IndexError:
                print(f"Config references nonexisting profile {pidx}")
                continue

            if pconf.get("disable", False) and profile.enabled:
                print(f"Profile {pidx} expected disabled, is enabled")

            report_rate = pconf.get("report-rate", profile.report_rate)
            if report_rate != profile.report_rate:
                print(
                    f"Profile {pidx} report rate expected {pconf['report-rate']}, is {profile.report_rate}"
                )

            for rconf in pconf.get("resolutions", []):
                ridx = rconf["index"]
                try:
                    resolution = profile.resolutions[ridx]
                except IndexError:
                    print(f"Config references nonexisting resolution {pidx}.{ridx}")
                    continue

                if rconf.get("disable", False) and resolution.enabled:
                    print(f"Resolution {pidx}.{ridx} expected disabled, is enabled")
                    continue

                dpis = rconf.get("dpi", None)
                if dpis and tuple(dpis) != resolution.dpi:
                    print(
                        f"Resolution {pidx}.{ridx} expected dpi ({dpis[0]}, {dpis[1]}), is ({resolution.dpi[0]}, {resolution.dpi[1]})"
                    )

            for bconf in pconf.get("buttons", []):
                bidx = bconf["index"]
                try:
                    button = profile.buttons[bidx]
                except IndexError:
                    print(f"Config references nonexisting button {pidx}.{bidx}")
                    continue

                if (
                    bconf.get("disable", False)
                    and button.action.type != ratbag.Action.Type.NONE
                ):
                    print(f"Button {pidx}.{bidx} expected disabled, is enabled")
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
                    print(
                        f"Button {pidx}.{bidx} expected button {bnumber}, is {bstring}"
                    )
                    continue

                special = bconf.get("special", None)
                if special and button.action != ratbag.ActionSpecial(None, special):
                    print(
                        f"Button {pidx}.{bidx} expected button {bnumber}, is {bstring}"
                    )
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
                        print(
                            f"Button {pidx}.{bidx} expected macro {events}, is {bstring}"
                        )
                        continue


def _init_logger(conf=None, verbose=False):
    if conf is None:
        conf = Path("config-logger.yml")
        if not conf.exists():
            xdg = os.getenv("XDG_CONFIG_HOME")
            if xdg is None:
                xdg = Path.home() / ".config"
            conf = Path(xdg) / "ratbagd" / "config-logger.yml"
    if Path(conf).exists():
        with open(conf) as fd:
            yml = yaml.safe_load(fd)
        logging.config.dictConfig(yml)
    else:
        lvl = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(format="%(levelname)s: %(name)s: %(message)s", level=lvl)
    # hidtools uses parse which spams at debug level, so as soon as we
    # import hidtools, we get logspam.
    logging.getLogger("parse").setLevel(logging.CRITICAL)


def _init_recorders(outfile):
    return [ratbag.recorder.YamlDeviceRecorder({"logfile": outfile})]


def _init_emulators(infile):
    return [ratbag.emulator.YamlDevice(infile)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser("A ratbag commandline tool")
    parser.add_argument(
        "--verbose", help="Enable debug logging", action="store_true", default=False
    )
    parser.add_argument(
        "--logger-config", help="Path to the logger config file", type=str, default=None
    )
    parser.add_argument(
        "--record", help="Path to the file to record to", type=str, default=None
    )
    parser.add_argument(
        "--replay", help="Path to a device recording", type=str, default=None
    )
    parser.add_argument(
        "--apply-config",
        help="Apply the given config to all matching devices",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--verify-config",
        help="Verify the given config was applied to all matching devices",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--nocommit",
        help="Never invoke commit() on the device",
        action="store_true",
        default=False,
    )

    parser.add_argument("devices", nargs="*", default=[])
    ns = parser.parse_args()

    _init_logger(ns.logger_config, ns.verbose)
    logger = logging.getLogger("ratbagcli")

    config = {}
    if ns.devices:
        config["device-paths"] = ns.devices
    if ns.replay:
        config["emulators"] = _init_emulators(ns.replay)
    if ns.record:
        config["recorders"] = _init_recorders(ns.record)

    try:
        user_config = Config(ns.apply_config, ns.nocommit)
    except Config.Error as e:
        print(f"Config error in {ns.apply_config}: {str(e)}. Aborting")
        sys.exit(1)

    try:
        verify_config = Config(ns.verify_config, ns.nocommit)
    except Config.Error as e:
        print(f"Config error in {ns.verify_config}: {str(e)}. Aborting")
        sys.exit(1)

    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag(config)

        def cb_device_added(ratbagcli, device):
            device_dict = device.as_dict()
            print(yaml.dump(device_dict, default_flow_style=None))
            user_config.apply(device)
            verify_config.verify(device)

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        mainloop.run()
    except KeyboardInterrupt:
        pass
