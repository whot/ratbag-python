#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black
#

from click.testing import CliRunner
from ratbag.cli.ratbagcli import ratbagcli

import yaml


def test_ratbagcli_help():
    runner = CliRunner()
    result = runner.invoke(ratbagcli, "help")
    assert result.exit_code == 0


def test_ratbagcli_list_supported():
    runner = CliRunner()
    result = runner.invoke(ratbagcli, "list-supported-devices")
    assert result.exit_code == 0
    output = result.stdout
    assert output

    yml = yaml.safe_load(output)
    assert yml["devices"]

    # We have more than that, but 20 should pick up any bugs
    assert len(yml["devices"]) > 20

    for device in yml["devices"]:
        assert "match" in device
        assert "name" in device
        assert "driver" in device

    # Some random devices we check for
    g900 = {"match": "usb:046d:4053", "driver": "hidpp20", "name": "Logitech G900"}
    kinzu = {
        "match": "usb:1038:1388",
        "driver": "steelseries",
        "name": "SteelSeries Kinzu V3",
    }
    etekcity = {
        "match": "usb:1ea7:4011",
        "driver": "etekcity",
        "name": "Etekcity Scroll Alpha",
    }

    assert g900 in yml["devices"]
    assert kinzu in yml["devices"]
    assert etekcity in yml["devices"]


# FIXME: this should use an emulator so we can test it actually works
# Right now this only catches usage errors
def test_ratbagcli_list():
    runner = CliRunner()
    result = runner.invoke(ratbagcli, "list")
    assert result.exit_code == 0


# FIXME: this should use an emulator so we can test it actually works
# Right now this only catches usage errors
def test_ratbagcli_show():
    runner = CliRunner()
    result = runner.invoke(ratbagcli, "show")
    assert result.exit_code == 0
