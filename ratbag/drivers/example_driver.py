#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

# This driver shows off the interface drivers have to meet. For real-world
# implementations and hints on how to get to one, see the actual drivers.
#

import logging

import ratbag
import ratbag.hid
import ratbag.drivers

# Create your own logger for this driver so we can nicely filter it
logger = logging.getLogger(__name__)


# This is the entry point, load_driver() must return a ratbag.drivers.Driver
# instance or throw an exception.
def load_driver(driver_name):
    assert driver_name == "example-driver"
    return ExampleDriver()


class ExampleDriver(ratbag.drivers.Driver):
    def __init__(self):
        # If you have your own constructor, you must call the super
        # constructor first (or asap) to set up the GObject
        super().__init__()
        # driver-specific generic setup goes here

    def probe(self, device, info, config):
        # device is either a string/pathlib.Path
        # or a device object. For basic devices (hidraw or just an fd), the
        # Rodent class simplifies setup:
        physical_device = ratbag.drivers.Rodent.from_device(device)

        # We want to be able to record data to/from our device, so let's
        # connect it. The Rodent class makes this easy:
        for rec in self.recorders:
            # This connects the varous data handlers
            physical_device.connect_to_recorder(rec)
            # Initialize the recorder
            rec.init(
                {
                    "name": self.physical_device.name,
                    "driver": "example-drive",
                    "path": self.physical_device.path,
                    # this field is available in Rodent if the device is a
                    # hidraw device
                    "report_descriptor": self.physical_device.report_descriptor,
                }
            )

        # Recorder is set up, now we can actually talk to the device
        device = ratbag.Device(self, physical_device.path, physical_device.name)
        device.connect("commit", self._on_commit)

        for profile_idx in range(3):  # three profiles
            profile = ratbag.Profile(device, profile_idx, name="unnamed profile")

            for dpi_idx in range(5):
                # Init all profiles to 800 dpi (x and y)
                dpi = (800, 800)
                # Let's say we support 400, 500, 600, ... 2000
                supported_dpi = list(range(400, 2000 + 1, 100))
                caps = [ratbag.Resolution.Capability.SEPARATE_XY_RESOLUTION]
                ratbag.Resolution(
                    profile, dpi_idx, dpi, capabilities=caps, dpi_list=supported_dpi
                )

            for btn_idx in range(8):
                caps = [
                    ratbag.Action.Type.BUTTON,
                    ratbag.Action.Type.SPECIAL,
                    ratbag.Action.Type.MACRO,
                ]
                # This is a simple driver, so we can pass None as parent
                # object
                action = ratbag.ActionButton(
                    None, btn_idx + 1
                )  # button events are 1 indexed
                ratbag.Button(profile, btn_idx, types=caps, action=action)

        # Notify the caller that we have a new device available. The next
        # interaction with this device will be the _on_commit callback
        self.emit("device-added", device)

    def _on_commit(self, device):
        for p in device.profiles.values():
            if not p.dirty:
                continue

            logger.debug(f"Profile {p.index} has changes to be written")
            for res in p.resolutions.value():
                if not res.dirty:
                    continue
                x, y = res.dpi
                logger.debug(f"Writing out resolution {res.index} for dpi {x},{y}")

            # etc.
