#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

# This driver shows off the interface drivers have to meet. For real-world
# implementations and hints on how to get to one, see the actual drivers.
#

from typing import List

import logging

import ratbag
import ratbag.hid
import ratbag.driver

# Create your own logger for this driver so we can nicely filter it
logger = logging.getLogger(__name__)


# This decorator marks this class as the actual driver implementation.
@ratbag.driver.ratbag_driver("example-driver")
class ExampleDriver(ratbag.driver.Driver):
    # the actual entry point
    @classmethod
    def new_with_devicelist(
        cls,
        ratbagctx: ratbag.Ratbag,
        supported_devices: List[ratbag.driver.DeviceConfig],
    ) -> ratbag.driver.Driver:
        # Create an instance of our driver
        driver = cls()
        # Now connect to the start signal so we know when we can get going
        ratbagctx.connect("start", lambda ctx: driver.start())
        # return our driver instance

        # This is an example driver only so we ignore the supported_devices
        # list. Otherwise we'd want to pass this on to the driver so we can
        # filter any devices we discover.
        return driver

    def __init__(self):
        # If you have your own constructor, you must call the super
        # constructor first (or asap) to set up the GObject
        super().__init__()
        # driver-specific generic setup goes here

    def start(self):
        # Here you could set up a UdevHirawMonitor or something similar to
        # perform the actual device discovery. Ideally together with the
        # supported_devices list to filter.
        self.probe("my device", "/some/path")

    def probe(self, name, path):
        device = ratbag.Device.create(self, path, name)
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

    def _on_commit(self, device: ratbag.Device, transaction: ratbag.CommitTransaction):
        for p in device.profiles:
            if not p.dirty:
                continue

            logger.debug(f"Profile {p.index} has changes to be written")
            for res in p.resolutions:
                if not res.dirty:
                    continue
                x, y = res.dpi
                logger.debug(f"Writing out resolution {res.index} for dpi {x},{y}")

            # etc.

        # Once we are done we push our success status up
        transaction.complete(success=True)
