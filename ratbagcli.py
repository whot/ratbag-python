#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import argparse
import logging
import logging.config
import os
import yaml

from pathlib import Path

import ratbag
import ratbag.emulator
import ratbag.recorder

from gi.repository import GLib


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
        filter = logging.Filter(name="ratbag")
    # hidtools uses parse which spams at debug level, so as soon as we
    # import hidtools, we get logspam.
    logging.getLogger("parse").setLevel(logging.CRITICAL)


def _init_recorders(outfile):
    return [ratbag.recorder.YamlDeviceRecorder({"logfile": outfile})]

def _init_emulators(infile):
    return [ratbag.emulator.YamlDevice(infile)]

if __name__ == "__main__":
    parser = argparse.ArgumentParser("A ratbag daemon")
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
    parser.add_argument("devices", nargs="*", default=[])
    ns = parser.parse_args()

    _init_logger(ns.logger_config, ns.verbose)

    config = {}
    if ns.devices:
        config["device-paths"] = ns.devices
    if ns.replay:
        config["emulators"]  = _init_emulators(ns.replay)
    if ns.record:
        config["recorders"] = _init_recorders(ns.record)

    try:
        mainloop = GLib.MainLoop()
        ratbagd = ratbag.Ratbag(config)

        def cb_device_added(ratbagd, device):
            print(device.dump())

        ratbagd.connect("device-added", cb_device_added)
        ratbagd.start()

        mainloop.run()
    except KeyboardInterrupt:
        pass
