#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import logging

import ratbag

logger = logging.getLogger(__name__)


class Hidpp10Driver(ratbag.drivers.Driver):
    NAME = "Logitech HID++1.0"

    def probe(self, device):
        profile = ratbag.Profile(device, 0)
        device.add_profile(profile)

    def commit(self, device, callback, arg):
        callback(arg, success=True)


def load_driver(driver_name: str) -> type[ratbag.drivers.Driver]:
    """
    Driver entry point

    :meta private:
    """
    assert driver_name == "hidpp10"
    return Hidpp10Driver
