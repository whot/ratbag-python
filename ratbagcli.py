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

from pathlib import Path

import ratbag
import ratbag.emulator
import ratbag.recorder

from gi.repository import GLib

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
        # - index is converted to int
        # - button special are converted to the ratbag.ActionSpecial type
        # - resolution dpi is converted to an int tuple
        for pidx, p in enumerate(self.profiles):
            if "index" not in p:
                raise Config.Error(f"Profile entry {pidx+1} has no 'index'")
            p["index"] = int(p["index"])
            pidx = p["index"]
            if not p.get("disable", True):
                raise Config.Error(f"Profile {pidx}: disable must be 'true'")

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
            device.commit()


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
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag(config)

        def cb_device_added(ratbagcli, device):
            device_dict = device.as_dict()
            # dpi_list is too long, spams the output, let's replace it
            for p in device_dict["profiles"]:
                for r in p["resolutions"]:
                    if len(r.get("dpi_list", [])) > 6:
                        dpis = r["dpi_list"]
                        dpis = dpis[:3] + dpis[-3:]
                        r["dpi_list"] = dpis

            print(yaml.dump(device_dict))
            user_config.apply(device)

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        mainloop.run()
    except KeyboardInterrupt:
        pass
