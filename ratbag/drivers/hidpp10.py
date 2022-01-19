#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

import logging

import ratbag
import ratbag.driver

logger = logging.getLogger(__name__)


@ratbag.driver.ratbag_driver("hidpp10")
class Hidpp10Driver(ratbag.driver.HidrawDriver):
    def probe(self, rodent, config):
        pass
