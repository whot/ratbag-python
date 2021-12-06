#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import logging

import ratbag

logger = logging.getLogger(__name__)

class Hidpp10Driver(ratbag.Driver):
    NAME = "Logitech HID++1.0"

    def probe(self, device):
        profile = ratbag.Profile(device, 0)
        device.add_profile(profile)

    def commit(self, device, callback, arg):
        callback(arg, success=True)


def load_driver(driver_name, device_info, driver_config):
    """
    Driver entry point

    :meta private:
    """
    assert driver_name == "hidpp10"
    logger.debug(device_info)
    logger.debug(driver_config)
    return Hidpp10Driver()

