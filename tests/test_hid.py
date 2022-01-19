#!usr/bin/env python3

import ratbag.hid


def test_hid_evdev():
    assert ratbag.hid.Key.KEY_ESCAPE.evdev == 1
    assert ratbag.hid.Key.KEY_A.evdev == 30
    assert ratbag.hid.Key.KEY_RESERVED.evdev == 0

    assert ratbag.hid.Key.from_evdev(1) == ratbag.hid.Key.KEY_ESCAPE
    assert ratbag.hid.Key.from_evdev(30) == ratbag.hid.Key.KEY_A
    assert ratbag.hid.Key.from_evdev(12345) is None

    assert ratbag.hid.ConsumerControl.CC_AC_DELETE.evdev == 111
    assert ratbag.hid.ConsumerControl.CC_AC_LOCK.evdev == 0

    assert (
        ratbag.hid.ConsumerControl.from_evdev(111)
        == ratbag.hid.ConsumerControl.CC_AC_DELETE
    )
    assert ratbag.hid.ConsumerControl.from_evdev(12345) is None


# From a  Roccat Kone XTD
ROCCAT_HID_REPORT = bytes(
    int(x, 16)
    for x in """
05 01 09 02 a1 01 85 01 09 01 a1 00 05 09 19 01 29 05
15 00 25 01 95 05 75 01 81 02 75 03 95 01 81 03 05 01 09 30 09 31 16 00 80 26
ff 7f 95 02 75 10 81 06 09 38 15 81 25 7f 75 08 95 01 81 06 05 0c 0a 38 02 81
06 c0 c0 05 0c 09 01 a1 01 85 02 19 00 2a 3c 02 15 00 26 3c 02 95 01 75 10 81
00 c0 05 0a 09 00 a1 01 85 03 19 00 29 00 15 00 25 00 95 04 75 08 81 00 c0 05
0b 09 00 a1 01 85 04 19 00 29 00 15 00 25 00 95 02 75 08 b1 01 85 05 95 02 b1
01 85 06 95 2a b1 01 85 07 95 4c b1 01 85 08 96 21 08 b1 01 85 09 95 05 b1 01
85 0a 95 07 b1 01 85 0c 95 03 b1 01 85 0d 96 03 04 b1 01 85 0e 95 02 b1 01 85
0f 95 05 b1 01 85 10 95 0f b1 01 85 1a 96 04 04 b1 01 85 1b 96 01 04 b1 01 85
1c 95 02 b1 01 c0
""".strip()
    .replace("\n", " ")
    .split(" ")
)


def test_rdesc_parser():
    rdesc = ratbag.hid.ReportDescriptor.from_bytes(ROCCAT_HID_REPORT)
    assert rdesc.input_report_by_id(1) is not None
    assert rdesc.output_report_by_id(1) is None
    assert rdesc.feature_report_by_id(1) is None

    # input_reports is a list
    r = rdesc.input_report_by_id(1)
    assert r in rdesc.input_reports
    assert r not in rdesc.output_reports
    assert r not in rdesc.feature_reports

    # 0x85, 0x02,                    //  Report ID (2)                      79
    # 0x19, 0x00,                    //  Usage Minimum (0)                  81
    # 0x2a, 0x3c, 0x02,              //  Usage Maximum (572)                83
    # 0x15, 0x00,                    //  Logical Minimum (0)                86
    # 0x26, 0x3c, 0x02,              //  Logical Maximum (572)              88
    # 0x95, 0x01,                    //  Report Count (1)                   91
    # 0x75, 0x10,                    //  Report Size (16)                   93
    # 0x81, 0x00,                    //  Input (Data,Arr,Abs)               95
    r = rdesc.input_report_by_id(2)
    assert r is not None
    assert r.report_id == 2
    assert r.size == 3  # 1 byte report ID, 16 bit data

    # 0x85, 0x03,                    //  Report ID (3)                      104
    # 0x19, 0x00,                    //  Usage Minimum (0)                  106
    # 0x29, 0x00,                    //  Usage Maximum (0)                  108
    # 0x15, 0x00,                    //  Logical Minimum (0)                110
    # 0x25, 0x00,                    //  Logical Maximum (0)                112
    # 0x95, 0x04,                    //  Report Count (4)                   114
    # 0x75, 0x08,                    //  Report Size (8)                    116
    # 0x81, 0x00,                    //  Input (Data,Arr,Abs)               118
    r = rdesc.input_report_by_id(3)
    assert r is not None
    assert r.report_id == 3
    assert r.size == 5  # 1 byte report ID, 4 * 8 bit data

    # 0x85, 0x04,                    //  Report ID (4)                      127
    # 0x19, 0x00,                    //  Usage Minimum (0)                  129
    # 0x29, 0x00,                    //  Usage Maximum (0)                  131
    # 0x15, 0x00,                    //  Logical Minimum (0)                133
    # 0x25, 0x00,                    //  Logical Maximum (0)                135
    # 0x95, 0x02,                    //  Report Count (2)                   137
    # 0x75, 0x08,                    //  Report Size (8)                    139
    # 0xb1, 0x01,                    //  Feature (Cnst,Arr,Abs)             141
    # 0x85, 0x05,                    //  Report ID (5)                      143
    # 0x95, 0x02,                    //  Report Count (2)                   145
    # 0xb1, 0x01,                    //  Feature (Cnst,Arr,Abs)             147
    r = rdesc.input_report_by_id(4)
    assert r is None
    r = rdesc.feature_report_by_id(4)
    assert r is not None
    assert r in rdesc.feature_reports
    assert r not in rdesc.input_reports
    assert r not in rdesc.output_reports
    assert r.report_id == 4
    assert r.size == 2 + 1

    # 0x85, 0x06,                    //  Report ID (6)                      149
    # 0x95, 0x2a,                    //  Report Count (42)                  151
    # 0xb1, 0x01,                    //  Feature (Cnst,Arr,Abs)             153
    r = rdesc.input_report_by_id(6)
    assert r is None
    r = rdesc.feature_report_by_id(6)
    assert r is not None
    assert r in rdesc.feature_reports
    assert r not in rdesc.input_reports
    assert r not in rdesc.output_reports
    assert r.report_id == 6
    assert r.size == 42 + 1

    # 0x85, 0x07,                    //  Report ID (7)                      155
    # 0x95, 0x4c,                    //  Report Count (76)                  157
    # 0xb1, 0x01,                    //  Feature (Cnst,Arr,Abs)             159
    r = rdesc.input_report_by_id(7)
    assert r is None
    r = rdesc.feature_report_by_id(7)
    assert r is not None
    assert r in rdesc.feature_reports
    assert r not in rdesc.input_reports
    assert r not in rdesc.output_reports
    assert r.report_id == 7
    assert r.size == 76 + 1

    # 0x85, 0x08,                    //  Report ID (8)                      161
    # 0x96, 0x21, 0x08,              //  Report Count (2081)                163
    # 0xb1, 0x01,                    //  Feature (Cnst,Arr,Abs)             166
    r = rdesc.input_report_by_id(8)
    assert r is None
    r = rdesc.feature_report_by_id(8)
    assert r is not None
    assert r in rdesc.feature_reports
    assert r not in rdesc.input_reports
    assert r not in rdesc.output_reports
    assert r.report_id == 8
    assert r.size == 2081 + 1
