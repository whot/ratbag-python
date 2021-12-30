#!/usr/bin/env python3

import attr
import enum
import libevdev
import struct

from typing import Dict, Iterator, Tuple


class Collection(enum.IntEnum):
    """
    An enum for the HID Collection types
    """

    PHYSICAL = 0
    APPLICATION = 1
    LOGICAL = 2


class Key(enum.IntEnum):
    """
    An enum for HID keys
    """

    KEY_RESERVED = 0x00  # Reserved (no event indicated)
    KEY_ERRORROLLOVER = 0x01  # ErrorRollOver
    KEY_POSTFAIL = 0x02  # POSTFail
    KEY_ERRORUNDEFINE = 0x03  # ErrorUndefine
    KEY_A = 0x04  # a and A
    KEY_B = 0x05  # b and B
    KEY_C = 0x06  # c and C
    KEY_D = 0x07  # d and D
    KEY_E = 0x08  # e and E
    KEY_F = 0x09  # f and F
    KEY_G = 0x0A  # g and G
    KEY_H = 0x0B  # h and H
    KEY_I = 0x0C  # i and I
    KEY_J = 0x0D  # j and J
    KEY_K = 0x0E  # k and K
    KEY_L = 0x0F  # l and L
    KEY_M = 0x10  # m and M
    KEY_N = 0x11  # n and N
    KEY_O = 0x12  # o and O
    KEY_P = 0x13  # p and P
    KEY_Q = 0x14  # q and Q
    KEY_R = 0x15  # r and R
    KEY_S = 0x16  # s and S
    KEY_T = 0x17  # t and T
    KEY_U = 0x18  # u and U
    KEY_V = 0x19  # v and V
    KEY_W = 0x1A  # w and W
    KEY_X = 0x1B  # x and X
    KEY_Y = 0x1C  # y and Y
    KEY_Z = 0x1D  # z and Z
    KEY_1 = 0x1E  # 1 and !
    KEY_2 = 0x1F  # 2 and @
    KEY_3 = 0x20  # 3 and #
    KEY_4 = 0x21  # 4 and $
    KEY_5 = 0x22  # 5 and %
    KEY_6 = 0x23  # 6 and ^
    KEY_7 = 0x24  # 7 and &
    KEY_8 = 0x25  # 8 and *
    KEY_9 = 0x26  # 9 and (
    KEY_0 = 0x27  # 0 and )
    KEY_RETURN_ENTER = 0x28  # Return (ENTER)
    KEY_ESCAPE = 0x29  # ESCAPE
    KEY_DELETE_BACKSPACE = 0x2A  # DELETE (Backspace)
    KEY_TAB = 0x2B  # Tab
    KEY_SPACEBAR = 0x2C  # Spacebar
    KEY_MINUS_AND_UNDERSCORE = 0x2D  # - and (underscore)
    KEY_EQUAL_AND_PLUS = 0x2E  # = and +
    KEY_CLOSE_BRACKET = 0x2F  # [ and {
    KEY_OPEN_BRACKET = 0x30  # ] and }
    KEY_BACK_SLASH_AND_PIPE = 0x31  # \ and |
    KEY_NON_US_HASH_AND_TILDE = 0x32  # Non-US # and ~
    KEY_SEMICOLON_AND_COLON = 0x33  # ; and :
    KEY_QUOTE_AND_DOUBLEQUOTE = 0x34  # ' and "
    KEY_GRAVE_ACCENT_AND_TILDE = 0x35  # Grave Accent and Tilde
    KEY_COMMA_AND_LESSER_THAN = 0x36  # Keyboard, and <
    KEY_PERIOD_AND_GREATER_THAN = 0x37  # . and >
    KEY_SLASH_AND_QUESTION_MARK = 0x38  # / and ?
    KEY_CAPS_LOCK = 0x39  # Caps Lock
    KEY_F1 = 0x3A  # F1
    KEY_F2 = 0x3B  # F2
    KEY_F3 = 0x3C  # F3
    KEY_F4 = 0x3D  # F4
    KEY_F5 = 0x3E  # F5
    KEY_F6 = 0x3F  # F6
    KEY_F7 = 0x40  # F7
    KEY_F8 = 0x41  # F8
    KEY_F9 = 0x42  # F9
    KEY_F10 = 0x43  # F10
    KEY_F11 = 0x44  # F11
    KEY_F12 = 0x45  # F12
    KEY_PRINTSCREEN = 0x46  # PrintScreen
    KEY_SCROLL_LOCK = 0x47  # Scroll Lock
    KEY_PAUSE = 0x48  # Pause
    KEY_INSERT = 0x49  # Insert
    KEY_HOME = 0x4A  # Home
    KEY_PAGEUP = 0x4B  # PageUp
    KEY_DELETE_FORWARD = 0x4C  # Delete Forward
    KEY_END = 0x4D  # End
    KEY_PAGEDOWN = 0x4E  # PageDown
    KEY_RIGHTARROW = 0x4F  # RightArrow
    KEY_LEFTARROW = 0x50  # LeftArrow
    KEY_DOWNARROW = 0x51  # DownArrow
    KEY_UPARROW = 0x52  # UpArrow
    KEY_KEYPAD_NUM_LOCK_AND_CLEAR = 0x53  # Keypad Num Lock and Clear
    KEY_KEYPAD_SLASH = 0x54  # Keypad /
    KEY_KEYPAD_ASTERISK = 0x55  # Keypad *
    KEY_KEYPAD_MINUS = 0x56  # Keypad -
    KEY_KEYPAD_PLUS = 0x57  # Keypad +
    KEY_KEYPAD_ENTER = 0x58  # Keypad ENTER
    KEY_KEYPAD_1_AND_END = 0x59  # Keypad 1 and End
    KEY_KEYPAD_2_AND_DOWN_ARROW = 0x5A  # Keypad 2 and Down Arrow
    KEY_KEYPAD_3_AND_PAGEDN = 0x5B  # Keypad 3 and PageDn
    KEY_KEYPAD_4_AND_LEFT_ARROW = 0x5C  # Keypad 4 and Left Arrow
    KEY_KEYPAD_5 = 0x5D  # Keypad 5
    KEY_KEYPAD_6_AND_RIGHT_ARROW = 0x5E  # Keypad 6 and Right Arrow
    KEY_KEYPAD_7_AND_HOME = 0x5F  # Keypad 7 and Home
    KEY_KEYPAD_8_AND_UP_ARROW = 0x60  # Keypad 8 and Up Arrow
    KEY_KEYPAD_9_AND_PAGEUP = 0x61  # Keypad 9 and PageUp
    KEY_KEYPAD_0_AND_INSERT = 0x62  # Keypad 0 and Insert
    KEY_KEYPAD_PERIOD_AND_DELETE = 0x63  # Keypad . and Delete
    KEY_NON_US_BACKSLASH_AND_PIPE = 0x64  # Non-US \ and |
    KEY_APPLICATION = 0x65  # Application
    KEY_POWER = 0x66  # Power
    KEY_KEYPAD_EQUAL = 0x67  # Keypad =
    KEY_F13 = 0x68  # F13
    KEY_F14 = 0x69  # F14
    KEY_F15 = 0x6A  # F15
    KEY_F16 = 0x6B  # F16
    KEY_F17 = 0x6C  # F17
    KEY_F18 = 0x6D  # F18
    KEY_F19 = 0x6E  # F19
    KEY_F20 = 0x6F  # F20
    KEY_F21 = 0x70  # F21
    KEY_F22 = 0x71  # F22
    KEY_F23 = 0x72  # F23
    KEY_F24 = 0x73  # F24
    KEY_EXECUTE = 0x74  # Execute
    KEY_HELP = 0x75  # Help
    KEY_MENU = 0x76  # Menu
    KEY_SELECT = 0x77  # Select
    KEY_STOP = 0x78  # Stop
    KEY_AGAIN = 0x79  # Again
    KEY_UNDO = 0x7A  # Undo
    KEY_CUT = 0x7B  # Cut
    KEY_COPY = 0x7C  # Copy
    KEY_PASTE = 0x7D  # Paste
    KEY_FIND = 0x7E  # Find
    KEY_MUTE = 0x7F  # Mute
    KEY_VOLUME_UP = 0x80  # Volume Up
    KEY_VOLUME_DOWN = 0x81  # Volume Down
    KEY_LOCKING_CAPS_LOCK = 0x82  # Locking Caps Lock
    KEY_LOCKING_NUM_LOCK = 0x83  # Locking Num Lock
    KEY_LOCKING_SCROLL_LOCK = 0x84  # Locking Scroll Lock
    KEY_KEYPAD_COMMA = 0x85  # Keypad Comma
    KEY_KEYPAD_EQUAL_SIGN = 0x86  # Keypad Equal Sign
    KEY_KANJI1 = 0x87  # Kanji1
    KEY_KANJI2 = 0x88  # Kanji2
    KEY_KANJI3 = 0x89  # Kanji3
    KEY_KANJI4 = 0x8A  # Kanji4
    KEY_KANJI5 = 0x8B  # Kanji5
    KEY_KANJI6 = 0x8C  # Kanji6
    KEY_KANJI7 = 0x8D  # Kanji7
    KEY_KANJI8 = 0x8E  # Kanji8
    KEY_KANJI9 = 0x8F  # Kanji9
    KEY_LANG1 = 0x90  # LANG1
    KEY_LANG2 = 0x91  # LANG2
    KEY_LANG3 = 0x92  # LANG3
    KEY_LANG4 = 0x93  # LANG4
    KEY_LANG5 = 0x94  # LANG5
    KEY_LANG6 = 0x95  # LANG6
    KEY_LANG7 = 0x96  # LANG7
    KEY_LANG8 = 0x97  # LANG8
    KEY_LANG9 = 0x98  # LANG9
    KEY_ALTERNATE_ERASE = 0x99  # Alternate Erase
    KEY_SYSREQ_ATTENTION = 0x9A  # SysReq/Attention
    KEY_CANCEL = 0x9B  # Cancel
    KEY_CLEAR = 0x9C  # Clear
    KEY_PRIOR = 0x9D  # Prior
    KEY_RETURN = 0x9E  # Return
    KEY_SEPARATOR = 0x9F  # Separator
    KEY_OUT = 0xA0  # Out
    KEY_OPER = 0xA1  # Oper
    KEY_CLEAR_AGAIN = 0xA2  # Clear/Again
    KEY_CRSEL_PROPS = 0xA3  # CrSel/Props
    KEY_EXSEL = 0xA4  # ExSel
    # RESERVED					0xA5-DF	*/ /* Reserved
    KEY_LEFTCONTROL = 0xE0  # LeftControl
    KEY_LEFTSHIFT = 0xE1  # LeftShift
    KEY_LEFTALT = 0xE2  # LeftAlt
    KEY_LEFT_GUI = 0xE3  # Left GUI
    KEY_RIGHTCONTROL = 0xE4  # RightControl
    KEY_RIGHTSHIFT = 0xE5  # RightShift
    KEY_RIGHTALT = 0xE6  # RightAlt
    KEY_RIGHT_GUI = 0xE7  # Right GUI

    @property
    def evdev(self):
        """
        Return the evdev key code for this key or ``0`` if none is defined.
        """
        return _KeyEvdevMapping.mapping.get(self, 0)

    @classmethod
    def from_evdev(cls, keycode):
        """
        Return the enum entry for the given evdev keycode or ``None`` if none is defined.
        """
        try:
            return {v: k for k, v in _KeyEvdevMapping.mapping.items()}[keycode]
        except KeyError:
            return None


class _KeyEvdevMapping:
    mapping = {
        Key.KEY_RESERVED: 0,
        Key.KEY_ERRORROLLOVER: 0,
        Key.KEY_POSTFAIL: 0,
        Key.KEY_ERRORUNDEFINE: 0,
        Key.KEY_A: libevdev.EV_KEY.KEY_A.value,
        Key.KEY_B: libevdev.EV_KEY.KEY_B.value,
        Key.KEY_C: libevdev.EV_KEY.KEY_C.value,
        Key.KEY_D: libevdev.EV_KEY.KEY_D.value,
        Key.KEY_E: libevdev.EV_KEY.KEY_E.value,
        Key.KEY_F: libevdev.EV_KEY.KEY_F.value,
        Key.KEY_G: libevdev.EV_KEY.KEY_G.value,
        Key.KEY_H: libevdev.EV_KEY.KEY_H.value,
        Key.KEY_I: libevdev.EV_KEY.KEY_I.value,
        Key.KEY_J: libevdev.EV_KEY.KEY_J.value,
        Key.KEY_K: libevdev.EV_KEY.KEY_K.value,
        Key.KEY_L: libevdev.EV_KEY.KEY_L.value,
        Key.KEY_M: libevdev.EV_KEY.KEY_M.value,
        Key.KEY_N: libevdev.EV_KEY.KEY_N.value,
        Key.KEY_O: libevdev.EV_KEY.KEY_O.value,
        Key.KEY_P: libevdev.EV_KEY.KEY_P.value,
        Key.KEY_Q: libevdev.EV_KEY.KEY_Q.value,
        Key.KEY_R: libevdev.EV_KEY.KEY_R.value,
        Key.KEY_S: libevdev.EV_KEY.KEY_S.value,
        Key.KEY_T: libevdev.EV_KEY.KEY_T.value,
        Key.KEY_U: libevdev.EV_KEY.KEY_U.value,
        Key.KEY_V: libevdev.EV_KEY.KEY_V.value,
        Key.KEY_W: libevdev.EV_KEY.KEY_W.value,
        Key.KEY_X: libevdev.EV_KEY.KEY_X.value,
        Key.KEY_Y: libevdev.EV_KEY.KEY_Y.value,
        Key.KEY_Z: libevdev.EV_KEY.KEY_Z.value,
        Key.KEY_1: libevdev.EV_KEY.KEY_1.value,
        Key.KEY_2: libevdev.EV_KEY.KEY_2.value,
        Key.KEY_3: libevdev.EV_KEY.KEY_3.value,
        Key.KEY_4: libevdev.EV_KEY.KEY_4.value,
        Key.KEY_5: libevdev.EV_KEY.KEY_5.value,
        Key.KEY_6: libevdev.EV_KEY.KEY_6.value,
        Key.KEY_7: libevdev.EV_KEY.KEY_7.value,
        Key.KEY_8: libevdev.EV_KEY.KEY_8.value,
        Key.KEY_9: libevdev.EV_KEY.KEY_9.value,
        Key.KEY_0: libevdev.EV_KEY.KEY_0.value,
        Key.KEY_RETURN_ENTER: libevdev.EV_KEY.KEY_ENTER.value,
        Key.KEY_ESCAPE: libevdev.EV_KEY.KEY_ESC.value,
        Key.KEY_DELETE_BACKSPACE: libevdev.EV_KEY.KEY_BACKSPACE.value,
        Key.KEY_TAB: libevdev.EV_KEY.KEY_TAB.value,
        Key.KEY_SPACEBAR: libevdev.EV_KEY.KEY_SPACE.value,
        Key.KEY_MINUS_AND_UNDERSCORE: libevdev.EV_KEY.KEY_MINUS.value,
        Key.KEY_EQUAL_AND_PLUS: libevdev.EV_KEY.KEY_EQUAL.value,
        Key.KEY_CLOSE_BRACKET: libevdev.EV_KEY.KEY_LEFTBRACE.value,
        Key.KEY_OPEN_BRACKET: libevdev.EV_KEY.KEY_RIGHTBRACE.value,
        Key.KEY_BACK_SLASH_AND_PIPE: libevdev.EV_KEY.KEY_BACKSLASH.value,
        Key.KEY_NON_US_HASH_AND_TILDE: libevdev.EV_KEY.KEY_BACKSLASH.value,
        Key.KEY_SEMICOLON_AND_COLON: libevdev.EV_KEY.KEY_SEMICOLON.value,
        Key.KEY_QUOTE_AND_DOUBLEQUOTE: libevdev.EV_KEY.KEY_APOSTROPHE.value,
        Key.KEY_GRAVE_ACCENT_AND_TILDE: libevdev.EV_KEY.KEY_GRAVE.value,
        Key.KEY_COMMA_AND_LESSER_THAN: libevdev.EV_KEY.KEY_COMMA.value,
        Key.KEY_PERIOD_AND_GREATER_THAN: libevdev.EV_KEY.KEY_DOT.value,
        Key.KEY_SLASH_AND_QUESTION_MARK: libevdev.EV_KEY.KEY_SLASH.value,
        Key.KEY_CAPS_LOCK: libevdev.EV_KEY.KEY_CAPSLOCK.value,
        Key.KEY_F1: libevdev.EV_KEY.KEY_F1.value,
        Key.KEY_F2: libevdev.EV_KEY.KEY_F2.value,
        Key.KEY_F3: libevdev.EV_KEY.KEY_F3.value,
        Key.KEY_F4: libevdev.EV_KEY.KEY_F4.value,
        Key.KEY_F5: libevdev.EV_KEY.KEY_F5.value,
        Key.KEY_F6: libevdev.EV_KEY.KEY_F6.value,
        Key.KEY_F7: libevdev.EV_KEY.KEY_F7.value,
        Key.KEY_F8: libevdev.EV_KEY.KEY_F8.value,
        Key.KEY_F9: libevdev.EV_KEY.KEY_F9.value,
        Key.KEY_F10: libevdev.EV_KEY.KEY_F10.value,
        Key.KEY_F11: libevdev.EV_KEY.KEY_F11.value,
        Key.KEY_F12: libevdev.EV_KEY.KEY_F12.value,
        Key.KEY_PRINTSCREEN: libevdev.EV_KEY.KEY_SYSRQ.value,
        Key.KEY_SCROLL_LOCK: libevdev.EV_KEY.KEY_SCROLLLOCK.value,
        Key.KEY_PAUSE: libevdev.EV_KEY.KEY_PAUSE.value,
        Key.KEY_INSERT: libevdev.EV_KEY.KEY_INSERT.value,
        Key.KEY_HOME: libevdev.EV_KEY.KEY_HOME.value,
        Key.KEY_PAGEUP: libevdev.EV_KEY.KEY_PAGEUP.value,
        Key.KEY_DELETE_FORWARD: libevdev.EV_KEY.KEY_DELETE.value,
        Key.KEY_END: libevdev.EV_KEY.KEY_END.value,
        Key.KEY_PAGEDOWN: libevdev.EV_KEY.KEY_PAGEDOWN.value,
        Key.KEY_RIGHTARROW: libevdev.EV_KEY.KEY_RIGHT.value,
        Key.KEY_LEFTARROW: libevdev.EV_KEY.KEY_LEFT.value,
        Key.KEY_DOWNARROW: libevdev.EV_KEY.KEY_DOWN.value,
        Key.KEY_UPARROW: libevdev.EV_KEY.KEY_UP.value,
        Key.KEY_KEYPAD_NUM_LOCK_AND_CLEAR: libevdev.EV_KEY.KEY_NUMLOCK.value,
        Key.KEY_KEYPAD_SLASH: libevdev.EV_KEY.KEY_KPSLASH.value,
        Key.KEY_KEYPAD_ASTERISK: libevdev.EV_KEY.KEY_KPASTERISK.value,
        Key.KEY_KEYPAD_MINUS: libevdev.EV_KEY.KEY_KPMINUS.value,
        Key.KEY_KEYPAD_PLUS: libevdev.EV_KEY.KEY_KPPLUS.value,
        Key.KEY_KEYPAD_ENTER: libevdev.EV_KEY.KEY_KPENTER.value,
        Key.KEY_KEYPAD_1_AND_END: libevdev.EV_KEY.KEY_KP1.value,
        Key.KEY_KEYPAD_2_AND_DOWN_ARROW: libevdev.EV_KEY.KEY_KP2.value,
        Key.KEY_KEYPAD_3_AND_PAGEDN: libevdev.EV_KEY.KEY_KP3.value,
        Key.KEY_KEYPAD_4_AND_LEFT_ARROW: libevdev.EV_KEY.KEY_KP4.value,
        Key.KEY_KEYPAD_5: libevdev.EV_KEY.KEY_KP5.value,
        Key.KEY_KEYPAD_6_AND_RIGHT_ARROW: libevdev.EV_KEY.KEY_KP6.value,
        Key.KEY_KEYPAD_7_AND_HOME: libevdev.EV_KEY.KEY_KP7.value,
        Key.KEY_KEYPAD_8_AND_UP_ARROW: libevdev.EV_KEY.KEY_KP8.value,
        Key.KEY_KEYPAD_9_AND_PAGEUP: libevdev.EV_KEY.KEY_KP9.value,
        Key.KEY_KEYPAD_0_AND_INSERT: libevdev.EV_KEY.KEY_KP0.value,
        Key.KEY_KEYPAD_PERIOD_AND_DELETE: libevdev.EV_KEY.KEY_KPDOT.value,
        Key.KEY_NON_US_BACKSLASH_AND_PIPE: libevdev.EV_KEY.KEY_102ND.value,
        Key.KEY_APPLICATION: libevdev.EV_KEY.KEY_COMPOSE.value,
        Key.KEY_POWER: libevdev.EV_KEY.KEY_POWER.value,
        Key.KEY_KEYPAD_EQUAL: libevdev.EV_KEY.KEY_KPEQUAL.value,
        Key.KEY_F13: libevdev.EV_KEY.KEY_F13.value,
        Key.KEY_F14: libevdev.EV_KEY.KEY_F14.value,
        Key.KEY_F15: libevdev.EV_KEY.KEY_F15.value,
        Key.KEY_F16: libevdev.EV_KEY.KEY_F16.value,
        Key.KEY_F17: libevdev.EV_KEY.KEY_F17.value,
        Key.KEY_F18: libevdev.EV_KEY.KEY_F18.value,
        Key.KEY_F19: libevdev.EV_KEY.KEY_F19.value,
        Key.KEY_F20: libevdev.EV_KEY.KEY_F20.value,
        Key.KEY_F21: libevdev.EV_KEY.KEY_F21.value,
        Key.KEY_F22: libevdev.EV_KEY.KEY_F22.value,
        Key.KEY_F23: libevdev.EV_KEY.KEY_F23.value,
        Key.KEY_F24: libevdev.EV_KEY.KEY_F24.value,
        Key.KEY_EXECUTE: 0,
        Key.KEY_HELP: libevdev.EV_KEY.KEY_HELP.value,
        Key.KEY_MENU: libevdev.EV_KEY.KEY_MENU.value,
        Key.KEY_SELECT: libevdev.EV_KEY.KEY_SELECT.value,
        Key.KEY_STOP: libevdev.EV_KEY.KEY_STOP.value,
        Key.KEY_AGAIN: libevdev.EV_KEY.KEY_AGAIN.value,
        Key.KEY_UNDO: libevdev.EV_KEY.KEY_UNDO.value,
        Key.KEY_CUT: libevdev.EV_KEY.KEY_CUT.value,
        Key.KEY_COPY: libevdev.EV_KEY.KEY_COPY.value,
        Key.KEY_PASTE: libevdev.EV_KEY.KEY_PASTE.value,
        Key.KEY_FIND: libevdev.EV_KEY.KEY_FIND.value,
        Key.KEY_MUTE: libevdev.EV_KEY.KEY_MUTE.value,
        Key.KEY_VOLUME_UP: libevdev.EV_KEY.KEY_VOLUMEUP.value,
        Key.KEY_VOLUME_DOWN: libevdev.EV_KEY.KEY_VOLUMEDOWN.value,
        Key.KEY_LOCKING_CAPS_LOCK: 0,
        Key.KEY_LOCKING_NUM_LOCK: 0,
        Key.KEY_LOCKING_SCROLL_LOCK: 0,
        Key.KEY_KEYPAD_COMMA: libevdev.EV_KEY.KEY_KPCOMMA.value,
        Key.KEY_KEYPAD_EQUAL_SIGN: libevdev.EV_KEY.KEY_KPEQUAL.value,
        Key.KEY_KANJI1: 0,
        Key.KEY_KANJI2: 0,
        Key.KEY_KANJI3: 0,
        Key.KEY_KANJI4: 0,
        Key.KEY_KANJI5: 0,
        Key.KEY_KANJI6: 0,
        Key.KEY_KANJI7: 0,
        Key.KEY_KANJI8: 0,
        Key.KEY_KANJI9: 0,
        Key.KEY_LANG1: 0,
        Key.KEY_LANG2: 0,
        Key.KEY_LANG3: 0,
        Key.KEY_LANG4: 0,
        Key.KEY_LANG5: 0,
        Key.KEY_LANG6: 0,
        Key.KEY_LANG7: 0,
        Key.KEY_LANG8: 0,
        Key.KEY_LANG9: 0,
        Key.KEY_ALTERNATE_ERASE: 0,
        Key.KEY_SYSREQ_ATTENTION: libevdev.EV_KEY.KEY_SYSRQ.value,
        Key.KEY_CANCEL: libevdev.EV_KEY.KEY_CANCEL.value,
        Key.KEY_CLEAR: libevdev.EV_KEY.KEY_CLEAR.value,
        Key.KEY_PRIOR: 0,
        Key.KEY_RETURN: 0,
        Key.KEY_SEPARATOR: 0,
        Key.KEY_OUT: 0,
        Key.KEY_OPER: 0,
        Key.KEY_CLEAR_AGAIN: 0,
        Key.KEY_CRSEL_PROPS: 0,
        Key.KEY_EXSEL: 0,
        # [xA5 ... 0xDF] = 0,
        Key.KEY_LEFTCONTROL: libevdev.EV_KEY.KEY_LEFTCTRL.value,
        Key.KEY_LEFTSHIFT: libevdev.EV_KEY.KEY_LEFTSHIFT.value,
        Key.KEY_LEFTALT: libevdev.EV_KEY.KEY_LEFTALT.value,
        Key.KEY_LEFT_GUI: libevdev.EV_KEY.KEY_LEFTMETA.value,
        Key.KEY_RIGHTCONTROL: libevdev.EV_KEY.KEY_RIGHTCTRL.value,
        Key.KEY_RIGHTSHIFT: libevdev.EV_KEY.KEY_RIGHTSHIFT.value,
        Key.KEY_RIGHTALT: libevdev.EV_KEY.KEY_RIGHTALT.value,
        Key.KEY_RIGHT_GUI: libevdev.EV_KEY.KEY_RIGHTMETA.value,
        # [0xe8 ... 0xff] = 0,
    }


class ConsumerControl(enum.IntEnum):
    CC_CONSUMER_CONTROL = 0x01
    CC_NUMERIC_KEY_PAD = 0x02
    CC_PROGRAMMABLE_BUTTONS = 0x03
    CC_MICROPHONE = 0x04
    CC_HEADPHONE = 0x05
    CC_GRAPHIC_EQUALIZER = 0x06
    CC_PLUS_10 = 0x20
    CC_PLUS_100 = 0x21
    CC_AM_PM = 0x22
    CC_POWER = 0x30
    CC_RESET = 0x31
    CC_SLEEP = 0x32
    CC_SLEEP_AFTER = 0x33
    CC_SLEEP_MODE = 0x34
    CC_ILLUMINATION = 0x35
    CC_FUNCTION_BUTTONS = 0x36
    CC_MENU = 0x40
    CC_MENU_PICK = 0x41
    CC_MENU_UP = 0x42
    CC_MENU_DOWN = 0x43
    CC_MENU_LEFT = 0x44
    CC_MENU_RIGHT = 0x45
    CC_MENU_ESCAPE = 0x46
    CC_MENU_VALUE_INCREASE = 0x47
    CC_MENU_VALUE_DECREASE = 0x48
    CC_DATA_ON_SCREEN = 0x60
    CC_CLOSED_CAPTION = 0x61
    CC_CLOSED_CAPTION_SELECT = 0x62
    CC_VCR_TV = 0x63
    CC_BROADCAST_MODE = 0x64
    CC_SNAPSHOT = 0x65
    CC_STILL = 0x66
    CC_ASPECT = 0x6D
    CC_3D_MODE_SELECT = 0x6E
    CC_DISPLAY_BRIGHTNESS_INCREMENT = 0x6F
    CC_DISPLAY_BRIGHTNESS_DECREMENT = 0x70
    CC_DISPLAY_BRIGHTNESS = 0x71
    CC_DISPLAY_BACKLIGHT_TOGGLE = 0x72
    # CC_DISPLAY_SET_BRIGHTNESS_TO_MINIMUM	0x73
    # CC_DISPLAY_SET_BRIGHTNESS_TO_MAXIMUM	0x74
    CC_DISPLAY_SET_AUTO_BRIGHTNESS = 0x75
    CC_SELECTION = 0x80
    CC_ASSIGN_SELECTION = 0x81
    CC_MODE_STEP = 0x82
    CC_RECALL_LAST = 0x83
    CC_ENTER_CHANNEL = 0x84
    CC_ORDER_MOVIE = 0x85
    CC_CHANNEL = 0x86
    CC_MEDIA_SELECTION = 0x87
    CC_MEDIA_SELECT_COMPUTER = 0x88
    CC_MEDIA_SELECT_TV = 0x89
    CC_MEDIA_SELECT_WWW = 0x8A
    CC_MEDIA_SELECT_DVD = 0x8B
    CC_MEDIA_SELECT_TELEPHONE = 0x8C
    CC_MEDIA_SELECT_PROGRAM_GUIDE = 0x8D
    CC_MEDIA_SELECT_VIDEO_PHONE = 0x8E
    CC_MEDIA_SELECT_GAMES = 0x8F
    CC_MEDIA_SELECT_MESSAGES = 0x90
    CC_MEDIA_SELECT_CD = 0x91
    CC_MEDIA_SELECT_VCR = 0x92
    CC_MEDIA_SELECT_TUNER = 0x93
    CC_QUIT = 0x94
    CC_HELP = 0x95
    CC_MEDIA_SELECT_TAPE = 0x96
    CC_MEDIA_SELECT_CABLE = 0x97
    CC_MEDIA_SELECT_SATELLITE = 0x98
    CC_MEDIA_SELECT_SECURITY = 0x99
    CC_MEDIA_SELECT_HOME = 0x9A
    CC_MEDIA_SELECT_CALL = 0x9B
    CC_CHANNEL_INCREMENT = 0x9C
    CC_CHANNEL_DECREMENT = 0x9D
    CC_MEDIA_SELECT_SAP = 0x9E
    CC_VCR_PLUS = 0xA0
    CC_ONCE = 0xA1
    CC_DAILY = 0xA2
    CC_WEEKLY = 0xA3
    CC_MONTHLY = 0xA4
    CC_PLAY = 0xB0
    CC_PAUSE = 0xB1
    CC_RECORD = 0xB2
    CC_FAST_FORWARD = 0xB3
    CC_REWIND = 0xB4
    CC_SCAN_NEXT_TRACK = 0xB5
    CC_SCAN_PREVIOUS_TRACK = 0xB6
    CC_STOP = 0xB7
    CC_EJECT = 0xB8
    CC_RANDOM_PLAY = 0xB9
    CC_SELECT_DISC = 0xBA
    CC_ENTER_DISC = 0xBB
    CC_REPEAT = 0xBC
    CC_TRACKING = 0xBD
    CC_TRACK_NORMAL = 0xBE
    CC_SLOW_TRACKING = 0xBF
    CC_FRAME_FORWARD = 0xC0
    CC_FRAME_BACK = 0xC1
    CC_MARK = 0xC2
    CC_CLEAR_MARK = 0xC3
    CC_REPEAT_FROM_MARK = 0xC4
    CC_RETURN_TO_MARK = 0xC5
    CC_SEARCH_MARK_FORWARD = 0xC6
    CC_SEARCH_MARK_BACKWARDS = 0xC7
    CC_COUNTER_RESET = 0xC8
    CC_SHOW_COUNTER = 0xC9
    CC_TRACKING_INCREMENT = 0xCA
    CC_TRACKING_DECREMENT = 0xCB
    CC_STOP_EJECT = 0xCC
    CC_PLAY_PAUSE = 0xCD
    CC_PLAY_SKIP = 0xCE
    CC_VOICE_COMMAND = 0xCF
    CC_VOLUME = 0xE0
    CC_BALANCE = 0xE1
    CC_MUTE = 0xE2
    CC_BASS = 0xE3
    CC_TREBLE = 0xE4
    CC_BASS_BOOST = 0xE5
    CC_SURROUND_MODE = 0xE6
    CC_LOUDNESS = 0xE7
    CC_MPX = 0xE8
    CC_VOLUME_UP = 0xE9
    CC_VOLUME_DOWN = 0xEA
    CC_SPEED_SELECT = 0xF0
    CC_PLAYBACK_SPEED = 0xF1
    CC_STANDARD_PLAY = 0xF2
    CC_LONG_PLAY = 0xF3
    CC_EXTENDED_PLAY = 0xF4
    CC_SLOW = 0xF5
    CC_FAN_ENABLE = 0x100
    CC_FAN_SPEED = 0x101
    CC_LIGHT_ENABLE = 0x102
    CC_LIGHT_ILLUMINATION_LEVEL = 0x103
    CC_CLIMATE_CONTROL_ENABLE = 0x104
    CC_ROOM_TEMPERATURE = 0x105
    CC_SECURITY_ENABLE = 0x106
    CC_FIRE_ALARM = 0x107
    CC_POLICE_ALARM = 0x108
    CC_PROXIMITY = 0x109
    CC_MOTION = 0x10A
    CC_DURESS_ALARM = 0x10B
    CC_HOLDUP_ALARM = 0x10C
    CC_MEDICAL_ALARM = 0x10D
    CC_BALANCE_RIGHT = 0x150
    CC_BALANCE_LEFT = 0x151
    CC_BASS_INCREMENT = 0x152
    CC_BASS_DECREMENT = 0x153
    CC_TREBLE_INCREMENT = 0x154
    CC_TREBLE_DECREMENT = 0x155
    CC_SPEAKER_SYSTEM = 0x160
    CC_CHANNEL_LEFT = 0x161
    CC_CHANNEL_RIGHT = 0x162
    CC_CHANNEL_CENTER = 0x163
    CC_CHANNEL_FRONT = 0x164
    CC_CHANNEL_CENTER_FRONT = 0x165
    CC_CHANNEL_SIDE = 0x166
    CC_CHANNEL_SURROUND = 0x167
    CC_CHANNEL_LOW_FREQ_ENHANCEMENT = 0x168
    CC_CHANNEL_TOP = 0x169
    CC_CHANNEL_UNKNOWN = 0x16A
    CC_SUB_CHANNEL = 0x170
    CC_SUB_CHANNEL_INCREMENT = 0x171
    CC_SUB_CHANNEL_DECREMENT = 0x172
    CC_ALTERNATE_AUDIO_INCREMENT = 0x173
    CC_ALTERNATE_AUDIO_DECREMENT = 0x174
    CC_APPLICATION_LAUNCH_BUTTONS = 0x180
    CC_AL_LAUNCH_BUTTON_CONFIG_TOOL = 0x181
    CC_AL_PROGRAMMABLE_BUTTON_CONFIG = 0x182
    CC_AL_CONSUMER_CONTROL_CONFIG = 0x183
    CC_AL_WORD_PROCESSOR = 0x184
    CC_AL_TEXT_EDITOR = 0x185
    CC_AL_SPREADSHEET = 0x186
    CC_AL_GRAPHICS_EDITOR = 0x187
    CC_AL_PRESENTATION_APP = 0x188
    CC_AL_DATABASE_APP = 0x189
    CC_AL_EMAIL_READER = 0x18A
    CC_AL_NEWSREADER = 0x18B
    CC_AL_VOICEMAIL = 0x18C
    CC_AL_CONTACTS_ADDRESS_BOOK = 0x18D
    CC_AL_CALENDAR_SCHEDULE = 0x18E
    CC_AL_TASK_PROJECT_MANAGER = 0x18F
    CC_AL_LOG_JOURNAL_TIMECARD = 0x190
    CC_AL_CHECKBOOK_FINANCE = 0x191
    CC_AL_CALCULATOR = 0x192
    CC_AL_A_VCAPTURE_PLAYBACK = 0x193
    CC_AL_LOCAL_MACHINE_BROWSER = 0x194
    CC_AL_LAN_WANBROWSER = 0x195
    CC_AL_INTERNET_BROWSER = 0x196
    CC_AL_REMOTE_NETWORKING_ISPCONNECT = 0x197
    CC_AL_NETWORK_CONFERENCE = 0x198
    CC_AL_NETWORK_CHAT = 0x199
    CC_AL_TELEPHONY_DIALER = 0x19A
    CC_AL_LOGON = 0x19B
    CC_AL_LOGOFF = 0x19C
    CC_AL_LOGON_LOGOFF = 0x19D
    CC_AL_TERMINAL_LOCK_SCREENSAVER = 0x19E
    CC_AL_CONTROL_PANEL = 0x19F
    CC_AL_COMMAND_LINE_PROCESSOR_RUN = 0x1A0
    CC_AL_PROCESS_TASK_MANAGER = 0x1A1
    CC_AL_SELECT_TASK_APPLICATION = 0x1A2
    CC_AL_NEXT_TASK_APPLICATION = 0x1A3
    CC_AL_PREVIOUS_TASK_APPLICATION = 0x1A4
    CC_AL_PREEMPT_HALT_TASK_APPLICATION = 0x1A5
    CC_AL_INTEGRATED_HELP_CENTER = 0x1A6
    CC_AL_DOCUMENTS = 0x1A7
    CC_AL_THESAURUS = 0x1A8
    CC_AL_DICTIONARY = 0x1A9
    CC_AL_DESKTOP = 0x1AA
    CC_AL_SPELL_CHECK = 0x1AB
    CC_AL_GRAMMAR_CHECK = 0x1AC
    CC_AL_WIRELESS_STATUS = 0x1AD
    CC_AL_KEYBOARD_LAYOUT = 0x1AE
    CC_AL_VIRUS_PROTECTION = 0x1AF
    CC_AL_ENCRYPTION = 0x1B0
    CC_AL_SCREEN_SAVER = 0x1B1
    CC_AL_ALARMS = 0x1B2
    CC_AL_CLOCK = 0x1B3
    CC_AL_FILE_BROWSER = 0x1B4
    CC_AL_POWER_STATUS = 0x1B5
    CC_AL_IMAGE_BROWSER = 0x1B6
    CC_AL_AUDIO_BROWSER = 0x1B7
    CC_AL_MOVIE_BROWSER = 0x1B8
    CC_AL_DIGITAL_RIGHTS_MANAGER = 0x1B9
    CC_AL_DIGITAL_WALLET = 0x1BA
    CC_AL_INSTANT_MESSAGING = 0x1BC
    CC_AL_OEMFEATURES_TIPS_TUTO_BROWSER = 0x1BD
    CC_AL_OEMHELP = 0x1BE
    CC_AL_ONLINE_COMMUNITY = 0x1BF
    CC_AL_ENTERTAINMENT_CONTENT_BROWSER = 0x1C0
    CC_AL_ONLINE_SHOPPING_BROWSER = 0x1C1
    CC_AL_SMART_CARD_INFORMATION_HELP = 0x1C2
    # CC_AL_MARKET_MONITOR_FINANCE_BROWSER	0x1C3
    CC_AL_CUSTOMIZED_CORP_NEWS_BROWSER = 0x1C4
    CC_AL_ONLINE_ACTIVITY_BROWSER = 0x1C5
    CC_AL_RESEARCH_SEARCH_BROWSER = 0x1C6
    CC_AL_AUDIO_PLAYER = 0x1C7
    CC_GENERIC_GUIAPPLICATION_CONTROLS = 0x200
    CC_AC_NEW = 0x201
    CC_AC_OPEN = 0x202
    CC_AC_CLOSE = 0x203
    CC_AC_EXIT = 0x204
    CC_AC_MAXIMIZE = 0x205
    CC_AC_MINIMIZE = 0x206
    CC_AC_SAVE = 0x207
    CC_AC_PRINT = 0x208
    CC_AC_PROPERTIES = 0x209
    CC_AC_UNDO = 0x21A
    CC_AC_COPY = 0x21B
    CC_AC_CUT = 0x21C
    CC_AC_PASTE = 0x21D
    CC_AC_SELECT_ALL = 0x21E
    CC_AC_FIND = 0x21F
    CC_AC_FINDAND_REPLACE = 0x220
    CC_AC_SEARCH = 0x221
    CC_AC_GO_TO = 0x222
    CC_AC_HOME = 0x223
    CC_AC_BACK = 0x224
    CC_AC_FORWARD = 0x225
    CC_AC_STOP = 0x226
    CC_AC_REFRESH = 0x227
    CC_AC_PREVIOUS_LINK = 0x228
    CC_AC_NEXT_LINK = 0x229
    CC_AC_BOOKMARKS = 0x22A
    CC_AC_HISTORY = 0x22B
    CC_AC_SUBSCRIPTIONS = 0x22C
    CC_AC_ZOOM_IN = 0x22D
    CC_AC_ZOOM_OUT = 0x22E
    CC_AC_ZOOM = 0x22F
    CC_AC_FULL_SCREEN_VIEW = 0x230
    CC_AC_NORMAL_VIEW = 0x231
    CC_AC_VIEW_TOGGLE = 0x232
    CC_AC_SCROLL_UP = 0x233
    CC_AC_SCROLL_DOWN = 0x234
    CC_AC_SCROLL = 0x235
    CC_AC_PAN_LEFT = 0x236
    CC_AC_PAN_RIGHT = 0x237
    CC_AC_PAN = 0x238
    CC_AC_NEW_WINDOW = 0x239
    CC_AC_TILE_HORIZONTALLY = 0x23A
    CC_AC_TILE_VERTICALLY = 0x23B
    CC_AC_FORMAT = 0x23C
    CC_AC_EDIT = 0x23D
    CC_AC_BOLD = 0x23E
    CC_AC_ITALICS = 0x23F
    CC_AC_UNDERLINE = 0x240
    CC_AC_STRIKETHROUGH = 0x241
    CC_AC_SUBSCRIPT = 0x242
    CC_AC_SUPERSCRIPT = 0x243
    CC_AC_ALL_CAPS = 0x244
    CC_AC_ROTATE = 0x245
    CC_AC_RESIZE = 0x246
    CC_AC_FLIPHORIZONTAL = 0x247
    CC_AC_FLIP_VERTICAL = 0x248
    CC_AC_MIRROR_HORIZONTAL = 0x249
    CC_AC_MIRROR_VERTICAL = 0x24A
    CC_AC_FONT_SELECT = 0x24B
    CC_AC_FONT_COLOR = 0x24C
    CC_AC_FONT_SIZE = 0x24D
    CC_AC_JUSTIFY_LEFT = 0x24E
    CC_AC_JUSTIFY_CENTER_H = 0x24F
    CC_AC_JUSTIFY_RIGHT = 0x250
    CC_AC_JUSTIFY_BLOCK_H = 0x251
    CC_AC_JUSTIFY_TOP = 0x252
    CC_AC_JUSTIFY_CENTER_V = 0x253
    CC_AC_JUSTIFY_BOTTOM = 0x254
    CC_AC_JUSTIFY_BLOCK_V = 0x255
    CC_AC_INDENT_DECREASE = 0x256
    CC_AC_INDENT_INCREASE = 0x257
    CC_AC_NUMBERED_LIST = 0x258
    CC_AC_RESTART_NUMBERING = 0x259
    CC_AC_BULLETED_LIST = 0x25A
    CC_AC_PROMOTE = 0x25B
    CC_AC_DEMOTE = 0x25C
    CC_AC_YES = 0x25D
    CC_AC_NO = 0x25E
    CC_AC_CANCEL = 0x25F
    CC_AC_CATALOG = 0x260
    CC_AC_BUY_CHECKOUT = 0x261
    CC_AC_ADDTO_CART = 0x262
    CC_AC_EXPAND = 0x263
    CC_AC_EXPAND_ALL = 0x264
    CC_AC_COLLAPSE = 0x265
    CC_AC_COLLAPSE_ALL = 0x266
    CC_AC_PRINT_PREVIEW = 0x267
    CC_AC_PASTE_SPECIAL = 0x268
    CC_AC_INSERT_MODE = 0x269
    CC_AC_DELETE = 0x26A
    CC_AC_LOCK = 0x26B
    CC_AC_UNLOCK = 0x26C
    CC_AC_PROTECT = 0x26D
    CC_AC_UNPROTECT = 0x26E
    CC_AC_ATTACH_COMMENT = 0x26F
    CC_AC_DELETE_COMMENT = 0x270
    CC_AC_VIEW_COMMENT = 0x271
    CC_AC_SELECT_WORD = 0x272
    CC_AC_SELECT_SENTENCE = 0x273
    CC_AC_SELECT_PARAGRAPH = 0x274
    CC_AC_SELECT_COLUMN = 0x275
    CC_AC_SELECT_ROW = 0x276
    CC_AC_SELECT_TABLE = 0x277
    CC_AC_SELECT_OBJECT = 0x278
    CC_AC_REDO_REPEAT = 0x279
    CC_AC_SORT = 0x27A
    CC_AC_SORT_ASCENDING = 0x27B
    CC_AC_SORT_DESCENDING = 0x27C
    CC_AC_FILTER = 0x27D
    CC_AC_SET_CLOCK = 0x27E
    CC_AC_VIEW_CLOCK = 0x27F
    CC_AC_SELECT_TIME_ZONE = 0x280
    CC_AC_EDIT_TIME_ZONES = 0x281
    CC_AC_SET_ALARM = 0x282
    CC_AC_CLEAR_ALARM = 0x283
    CC_AC_SNOOZE_ALARM = 0x284
    CC_AC_RESET_ALARM = 0x285
    CC_AC_SYNCHRONIZE = 0x286
    CC_AC_SEND_RECEIVE = 0x287
    CC_AC_SEND_TO = 0x288
    CC_AC_REPLY = 0x289
    CC_AC_REPLY_ALL = 0x28A
    CC_AC_FORWARD_MSG = 0x28B
    CC_AC_SEND = 0x28C
    CC_AC_ATTACH_FILE = 0x28D
    CC_AC_UPLOAD = 0x28E
    # CC_AC_DOWNLOAD(SAVE_TARGET_AS)		0x28F
    CC_AC_SET_BORDERS = 0x290
    CC_AC_INSERT_ROW = 0x291
    CC_AC_INSERT_COLUMN = 0x292
    CC_AC_INSERT_FILE = 0x293
    CC_AC_INSERT_PICTURE = 0x294
    CC_AC_INSERT_OBJECT = 0x295
    CC_AC_INSERT_SYMBOL = 0x296
    CC_AC_SAVEAND_CLOSE = 0x297
    CC_AC_RENAME = 0x298
    CC_AC_MERGE = 0x299
    CC_AC_SPLIT = 0x29A
    CC_AC_DISRIBUTE_HORIZONTALLY = 0x29B
    CC_AC_DISTRIBUTE_VERTICALLY = 0x29C

    @property
    def evdev(self):
        """
        Return the evdev key code for this consumer control or ``0`` if none
        is defined.
        """
        return _ConsumerControlEvdevMapping.mapping.get(self, 0)

    @classmethod
    def from_evdev(cls, keycode):
        """
        Return the enum entry for the given evdev keycode or ``None`` if none is defined.
        """
        try:
            return {v: k for k, v in _ConsumerControlEvdevMapping.mapping.items()}[
                keycode
            ]
        except KeyError:
            return None


class _ConsumerControlEvdevMapping:
    mapping = {
        # [0x00] = 0,
        # [0x07 ... 0x1F] = 0,
        # [0x23 ... 0x2F] = 0,
        # [0x37 ... 0x3F] = 0,
        # [0x49 ... 0x5F] = 0,
        # [0x67 ... 0x6C] = 0,
        # [0x76 ... 0x7F] = 0,
        # [0x9F ... 0x9F] = 0,
        # [0xA5 ... 0xAF] = 0,
        # [0xD0 ... 0xDF] = 0,
        # [0xEB ... 0xEF] = 0,
        # [0xF6 ... 0xFF] = 0,
        # [0x10E ... 0x14F] = 0,
        # [0x156 ... 0x15F] = 0,
        # [0x16B ... 0x16F] = 0,
        # [0x175 ... 0x17F] = 0,
        # [0x1BB ... 0x1BB] = 0,
        # [0x1C8 ... 0x1FF] = 0,
        # [0x20A ... 0x219] = 0,
        # [0x29D ... 0xFFF] = 0,
        ConsumerControl.CC_CONSUMER_CONTROL: 0,
        ConsumerControl.CC_NUMERIC_KEY_PAD: 0,
        ConsumerControl.CC_PROGRAMMABLE_BUTTONS: 0,
        ConsumerControl.CC_MICROPHONE: 0,
        ConsumerControl.CC_HEADPHONE: 0,
        ConsumerControl.CC_GRAPHIC_EQUALIZER: 0,
        ConsumerControl.CC_PLUS_10: 0,
        ConsumerControl.CC_PLUS_100: 0,
        ConsumerControl.CC_AM_PM: 0,
        ConsumerControl.CC_POWER: libevdev.EV_KEY.KEY_POWER.value,
        ConsumerControl.CC_RESET: 0,
        ConsumerControl.CC_SLEEP: libevdev.EV_KEY.KEY_SLEEP.value,
        ConsumerControl.CC_SLEEP_AFTER: 0,
        ConsumerControl.CC_SLEEP_MODE: 0,
        ConsumerControl.CC_ILLUMINATION: 0,
        ConsumerControl.CC_FUNCTION_BUTTONS: 0,
        ConsumerControl.CC_MENU: libevdev.EV_KEY.KEY_MENU.value,
        ConsumerControl.CC_MENU_PICK: 0,
        ConsumerControl.CC_MENU_UP: 0,
        ConsumerControl.CC_MENU_DOWN: 0,
        ConsumerControl.CC_MENU_LEFT: 0,
        ConsumerControl.CC_MENU_RIGHT: 0,
        ConsumerControl.CC_MENU_ESCAPE: 0,
        ConsumerControl.CC_MENU_VALUE_INCREASE: 0,
        ConsumerControl.CC_MENU_VALUE_DECREASE: 0,
        ConsumerControl.CC_DATA_ON_SCREEN: 0,
        ConsumerControl.CC_CLOSED_CAPTION: 0,
        ConsumerControl.CC_CLOSED_CAPTION_SELECT: 0,
        ConsumerControl.CC_VCR_TV: 0,
        ConsumerControl.CC_BROADCAST_MODE: 0,
        ConsumerControl.CC_SNAPSHOT: 0,
        ConsumerControl.CC_STILL: 0,
        ConsumerControl.CC_ASPECT: 0,
        ConsumerControl.CC_3D_MODE_SELECT: 0,
        ConsumerControl.CC_DISPLAY_BRIGHTNESS_INCREMENT: 0,
        ConsumerControl.CC_DISPLAY_BRIGHTNESS_DECREMENT: 0,
        ConsumerControl.CC_DISPLAY_BRIGHTNESS: 0,
        ConsumerControl.CC_DISPLAY_BACKLIGHT_TOGGLE: 0,
        # CC_DISPLAY_SET_BRIGHTNESS_TO_MINIMUM: 0,
        # CC_DISPLAY_SET_BRIGHTNESS_TO_MAXIMUM: 0,
        ConsumerControl.CC_DISPLAY_SET_AUTO_BRIGHTNESS: 0,
        ConsumerControl.CC_SELECTION: 0,
        ConsumerControl.CC_ASSIGN_SELECTION: 0,
        ConsumerControl.CC_MODE_STEP: 0,
        ConsumerControl.CC_RECALL_LAST: 0,
        ConsumerControl.CC_ENTER_CHANNEL: 0,
        ConsumerControl.CC_ORDER_MOVIE: 0,
        ConsumerControl.CC_CHANNEL: 0,
        ConsumerControl.CC_MEDIA_SELECTION: 0,
        ConsumerControl.CC_MEDIA_SELECT_COMPUTER: 0,
        ConsumerControl.CC_MEDIA_SELECT_TV: 0,
        ConsumerControl.CC_MEDIA_SELECT_WWW: 0,
        ConsumerControl.CC_MEDIA_SELECT_DVD: 0,
        ConsumerControl.CC_MEDIA_SELECT_TELEPHONE: 0,
        ConsumerControl.CC_MEDIA_SELECT_PROGRAM_GUIDE: 0,
        ConsumerControl.CC_MEDIA_SELECT_VIDEO_PHONE: 0,
        ConsumerControl.CC_MEDIA_SELECT_GAMES: 0,
        ConsumerControl.CC_MEDIA_SELECT_MESSAGES: 0,
        ConsumerControl.CC_MEDIA_SELECT_CD: 0,
        ConsumerControl.CC_MEDIA_SELECT_VCR: 0,
        ConsumerControl.CC_MEDIA_SELECT_TUNER: 0,
        ConsumerControl.CC_QUIT: 0,
        ConsumerControl.CC_HELP: libevdev.EV_KEY.KEY_HELP.value,
        ConsumerControl.CC_MEDIA_SELECT_TAPE: 0,
        ConsumerControl.CC_MEDIA_SELECT_CABLE: 0,
        ConsumerControl.CC_MEDIA_SELECT_SATELLITE: 0,
        ConsumerControl.CC_MEDIA_SELECT_SECURITY: 0,
        ConsumerControl.CC_MEDIA_SELECT_HOME: 0,
        ConsumerControl.CC_MEDIA_SELECT_CALL: 0,
        ConsumerControl.CC_CHANNEL_INCREMENT: 0,
        ConsumerControl.CC_CHANNEL_DECREMENT: 0,
        ConsumerControl.CC_MEDIA_SELECT_SAP: 0,
        ConsumerControl.CC_VCR_PLUS: 0,
        ConsumerControl.CC_ONCE: 0,
        ConsumerControl.CC_DAILY: 0,
        ConsumerControl.CC_WEEKLY: 0,
        ConsumerControl.CC_MONTHLY: 0,
        ConsumerControl.CC_PLAY: libevdev.EV_KEY.KEY_PLAY.value,
        ConsumerControl.CC_PAUSE: libevdev.EV_KEY.KEY_PAUSE.value,
        ConsumerControl.CC_RECORD: libevdev.EV_KEY.KEY_RECORD.value,
        ConsumerControl.CC_FAST_FORWARD: libevdev.EV_KEY.KEY_FASTFORWARD.value,
        ConsumerControl.CC_REWIND: libevdev.EV_KEY.KEY_REWIND.value,
        ConsumerControl.CC_SCAN_NEXT_TRACK: libevdev.EV_KEY.KEY_NEXTSONG.value,
        ConsumerControl.CC_SCAN_PREVIOUS_TRACK: libevdev.EV_KEY.KEY_PREVIOUSSONG.value,
        ConsumerControl.CC_STOP: libevdev.EV_KEY.KEY_STOP.value,
        ConsumerControl.CC_EJECT: libevdev.EV_KEY.KEY_EJECTCD.value,
        ConsumerControl.CC_RANDOM_PLAY: 0,
        ConsumerControl.CC_SELECT_DISC: 0,
        ConsumerControl.CC_ENTER_DISC: 0,
        ConsumerControl.CC_REPEAT: 0,
        ConsumerControl.CC_TRACKING: 0,
        ConsumerControl.CC_TRACK_NORMAL: 0,
        ConsumerControl.CC_SLOW_TRACKING: 0,
        ConsumerControl.CC_FRAME_FORWARD: 0,
        ConsumerControl.CC_FRAME_BACK: 0,
        ConsumerControl.CC_MARK: 0,
        ConsumerControl.CC_CLEAR_MARK: 0,
        ConsumerControl.CC_REPEAT_FROM_MARK: 0,
        ConsumerControl.CC_RETURN_TO_MARK: 0,
        ConsumerControl.CC_SEARCH_MARK_FORWARD: 0,
        ConsumerControl.CC_SEARCH_MARK_BACKWARDS: 0,
        ConsumerControl.CC_COUNTER_RESET: 0,
        ConsumerControl.CC_SHOW_COUNTER: 0,
        ConsumerControl.CC_TRACKING_INCREMENT: 0,
        ConsumerControl.CC_TRACKING_DECREMENT: 0,
        ConsumerControl.CC_STOP_EJECT: 0,
        ConsumerControl.CC_PLAY_PAUSE: libevdev.EV_KEY.KEY_PLAYPAUSE.value,
        ConsumerControl.CC_PLAY_SKIP: 0,
        ConsumerControl.CC_VOICE_COMMAND: libevdev.EV_KEY.KEY_VOICECOMMAND.value,
        ConsumerControl.CC_VOLUME: 0,
        ConsumerControl.CC_BALANCE: 0,
        ConsumerControl.CC_MUTE: libevdev.EV_KEY.KEY_MUTE.value,
        ConsumerControl.CC_BASS: 0,
        ConsumerControl.CC_TREBLE: 0,
        ConsumerControl.CC_BASS_BOOST: libevdev.EV_KEY.KEY_BASSBOOST.value,
        ConsumerControl.CC_SURROUND_MODE: 0,
        ConsumerControl.CC_LOUDNESS: 0,
        ConsumerControl.CC_MPX: 0,
        ConsumerControl.CC_VOLUME_UP: libevdev.EV_KEY.KEY_VOLUMEUP.value,
        ConsumerControl.CC_VOLUME_DOWN: libevdev.EV_KEY.KEY_VOLUMEDOWN.value,
        ConsumerControl.CC_SPEED_SELECT: 0,
        ConsumerControl.CC_PLAYBACK_SPEED: 0,
        ConsumerControl.CC_STANDARD_PLAY: 0,
        ConsumerControl.CC_LONG_PLAY: 0,
        ConsumerControl.CC_EXTENDED_PLAY: 0,
        ConsumerControl.CC_SLOW: libevdev.EV_KEY.KEY_SLOW.value,
        ConsumerControl.CC_FAN_ENABLE: 0,
        ConsumerControl.CC_FAN_SPEED: 0,
        ConsumerControl.CC_LIGHT_ENABLE: 0,
        ConsumerControl.CC_LIGHT_ILLUMINATION_LEVEL: 0,
        ConsumerControl.CC_CLIMATE_CONTROL_ENABLE: 0,
        ConsumerControl.CC_ROOM_TEMPERATURE: 0,
        ConsumerControl.CC_SECURITY_ENABLE: 0,
        ConsumerControl.CC_FIRE_ALARM: 0,
        ConsumerControl.CC_POLICE_ALARM: 0,
        ConsumerControl.CC_PROXIMITY: 0,
        ConsumerControl.CC_MOTION: 0,
        ConsumerControl.CC_DURESS_ALARM: 0,
        ConsumerControl.CC_HOLDUP_ALARM: 0,
        ConsumerControl.CC_MEDICAL_ALARM: 0,
        ConsumerControl.CC_BALANCE_RIGHT: 0,
        ConsumerControl.CC_BALANCE_LEFT: 0,
        ConsumerControl.CC_BASS_INCREMENT: 0,
        ConsumerControl.CC_BASS_DECREMENT: 0,
        ConsumerControl.CC_TREBLE_INCREMENT: 0,
        ConsumerControl.CC_TREBLE_DECREMENT: 0,
        ConsumerControl.CC_SPEAKER_SYSTEM: 0,
        ConsumerControl.CC_CHANNEL_LEFT: 0,
        ConsumerControl.CC_CHANNEL_RIGHT: 0,
        ConsumerControl.CC_CHANNEL_CENTER: 0,
        ConsumerControl.CC_CHANNEL_FRONT: 0,
        ConsumerControl.CC_CHANNEL_CENTER_FRONT: 0,
        ConsumerControl.CC_CHANNEL_SIDE: 0,
        ConsumerControl.CC_CHANNEL_SURROUND: 0,
        ConsumerControl.CC_CHANNEL_LOW_FREQ_ENHANCEMENT: 0,
        ConsumerControl.CC_CHANNEL_TOP: 0,
        ConsumerControl.CC_CHANNEL_UNKNOWN: 0,
        ConsumerControl.CC_SUB_CHANNEL: 0,
        ConsumerControl.CC_SUB_CHANNEL_INCREMENT: 0,
        ConsumerControl.CC_SUB_CHANNEL_DECREMENT: 0,
        ConsumerControl.CC_ALTERNATE_AUDIO_INCREMENT: 0,
        ConsumerControl.CC_ALTERNATE_AUDIO_DECREMENT: 0,
        ConsumerControl.CC_APPLICATION_LAUNCH_BUTTONS: 0,
        ConsumerControl.CC_AL_LAUNCH_BUTTON_CONFIG_TOOL: 0,
        ConsumerControl.CC_AL_PROGRAMMABLE_BUTTON_CONFIG: 0,
        ConsumerControl.CC_AL_CONSUMER_CONTROL_CONFIG: libevdev.EV_KEY.KEY_CONFIG.value,
        ConsumerControl.CC_AL_WORD_PROCESSOR: libevdev.EV_KEY.KEY_WORDPROCESSOR.value,
        ConsumerControl.CC_AL_TEXT_EDITOR: libevdev.EV_KEY.KEY_EDITOR.value,
        ConsumerControl.CC_AL_SPREADSHEET: libevdev.EV_KEY.KEY_SPREADSHEET.value,
        ConsumerControl.CC_AL_GRAPHICS_EDITOR: libevdev.EV_KEY.KEY_GRAPHICSEDITOR.value,
        ConsumerControl.CC_AL_PRESENTATION_APP: libevdev.EV_KEY.KEY_PRESENTATION.value,
        ConsumerControl.CC_AL_DATABASE_APP: libevdev.EV_KEY.KEY_DATABASE.value,
        ConsumerControl.CC_AL_EMAIL_READER: libevdev.EV_KEY.KEY_EMAIL.value,
        ConsumerControl.CC_AL_NEWSREADER: libevdev.EV_KEY.KEY_NEWS.value,
        ConsumerControl.CC_AL_VOICEMAIL: libevdev.EV_KEY.KEY_VOICEMAIL.value,
        ConsumerControl.CC_AL_CONTACTS_ADDRESS_BOOK: libevdev.EV_KEY.KEY_ADDRESSBOOK.value,
        ConsumerControl.CC_AL_CALENDAR_SCHEDULE: 0,
        ConsumerControl.CC_AL_TASK_PROJECT_MANAGER: 0,
        ConsumerControl.CC_AL_LOG_JOURNAL_TIMECARD: 0,
        ConsumerControl.CC_AL_CHECKBOOK_FINANCE: libevdev.EV_KEY.KEY_FINANCE.value,
        ConsumerControl.CC_AL_CALCULATOR: libevdev.EV_KEY.KEY_CALC.value,
        ConsumerControl.CC_AL_A_VCAPTURE_PLAYBACK: 0,
        ConsumerControl.CC_AL_LOCAL_MACHINE_BROWSER: libevdev.EV_KEY.KEY_FILE.value,
        ConsumerControl.CC_AL_LAN_WANBROWSER: 0,
        ConsumerControl.CC_AL_INTERNET_BROWSER: libevdev.EV_KEY.KEY_WWW.value,
        ConsumerControl.CC_AL_REMOTE_NETWORKING_ISPCONNECT: 0,
        ConsumerControl.CC_AL_NETWORK_CONFERENCE: 0,
        ConsumerControl.CC_AL_NETWORK_CHAT: 0,
        ConsumerControl.CC_AL_TELEPHONY_DIALER: libevdev.EV_KEY.KEY_PHONE.value,
        ConsumerControl.CC_AL_LOGON: 0,
        ConsumerControl.CC_AL_LOGOFF: 0,
        ConsumerControl.CC_AL_LOGON_LOGOFF: 0,
        ConsumerControl.CC_AL_TERMINAL_LOCK_SCREENSAVER: libevdev.EV_KEY.KEY_COFFEE.value,
        ConsumerControl.CC_AL_CONTROL_PANEL: 0,
        ConsumerControl.CC_AL_COMMAND_LINE_PROCESSOR_RUN: 0,
        ConsumerControl.CC_AL_PROCESS_TASK_MANAGER: 0,
        ConsumerControl.CC_AL_SELECT_TASK_APPLICATION: 0,
        ConsumerControl.CC_AL_NEXT_TASK_APPLICATION: 0,
        ConsumerControl.CC_AL_PREVIOUS_TASK_APPLICATION: 0,
        ConsumerControl.CC_AL_PREEMPT_HALT_TASK_APPLICATION: 0,
        ConsumerControl.CC_AL_INTEGRATED_HELP_CENTER: libevdev.EV_KEY.KEY_HELP.value,
        ConsumerControl.CC_AL_DOCUMENTS: 0,
        ConsumerControl.CC_AL_THESAURUS: 0,
        ConsumerControl.CC_AL_DICTIONARY: 0,
        ConsumerControl.CC_AL_DESKTOP: 0,
        ConsumerControl.CC_AL_SPELL_CHECK: 0,
        ConsumerControl.CC_AL_GRAMMAR_CHECK: 0,
        ConsumerControl.CC_AL_WIRELESS_STATUS: 0,
        ConsumerControl.CC_AL_KEYBOARD_LAYOUT: 0,
        ConsumerControl.CC_AL_VIRUS_PROTECTION: 0,
        ConsumerControl.CC_AL_ENCRYPTION: 0,
        ConsumerControl.CC_AL_SCREEN_SAVER: libevdev.EV_KEY.KEY_SCREENSAVER.value,
        ConsumerControl.CC_AL_ALARMS: 0,
        ConsumerControl.CC_AL_CLOCK: 0,
        ConsumerControl.CC_AL_FILE_BROWSER: libevdev.EV_KEY.KEY_FILE.value,
        ConsumerControl.CC_AL_POWER_STATUS: 0,
        ConsumerControl.CC_AL_IMAGE_BROWSER: libevdev.EV_KEY.KEY_IMAGES.value,
        ConsumerControl.CC_AL_AUDIO_BROWSER: libevdev.EV_KEY.KEY_AUDIO.value,
        ConsumerControl.CC_AL_MOVIE_BROWSER: libevdev.EV_KEY.KEY_VIDEO.value,
        ConsumerControl.CC_AL_DIGITAL_RIGHTS_MANAGER: 0,
        ConsumerControl.CC_AL_DIGITAL_WALLET: 0,
        ConsumerControl.CC_AL_INSTANT_MESSAGING: libevdev.EV_KEY.KEY_MESSENGER.value,
        ConsumerControl.CC_AL_OEMFEATURES_TIPS_TUTO_BROWSER: libevdev.EV_KEY.KEY_INFO.value,
        ConsumerControl.CC_AL_OEMHELP: 0,
        ConsumerControl.CC_AL_ONLINE_COMMUNITY: 0,
        ConsumerControl.CC_AL_ENTERTAINMENT_CONTENT_BROWSER: 0,
        ConsumerControl.CC_AL_ONLINE_SHOPPING_BROWSER: 0,
        ConsumerControl.CC_AL_SMART_CARD_INFORMATION_HELP: 0,
        # CC_AL_MARKET_MONITOR_FINANCE_BROWSER: 0,
        ConsumerControl.CC_AL_CUSTOMIZED_CORP_NEWS_BROWSER: 0,
        ConsumerControl.CC_AL_ONLINE_ACTIVITY_BROWSER: 0,
        ConsumerControl.CC_AL_RESEARCH_SEARCH_BROWSER: 0,
        ConsumerControl.CC_AL_AUDIO_PLAYER: 0,
        ConsumerControl.CC_GENERIC_GUIAPPLICATION_CONTROLS: 0,
        ConsumerControl.CC_AC_NEW: libevdev.EV_KEY.KEY_NEW.value,
        ConsumerControl.CC_AC_OPEN: libevdev.EV_KEY.KEY_OPEN.value,
        ConsumerControl.CC_AC_CLOSE: libevdev.EV_KEY.KEY_CLOSE.value,
        ConsumerControl.CC_AC_EXIT: libevdev.EV_KEY.KEY_EXIT.value,
        ConsumerControl.CC_AC_MAXIMIZE: 0,
        ConsumerControl.CC_AC_MINIMIZE: 0,
        ConsumerControl.CC_AC_SAVE: libevdev.EV_KEY.KEY_SAVE.value,
        ConsumerControl.CC_AC_PRINT: libevdev.EV_KEY.KEY_PRINT.value,
        ConsumerControl.CC_AC_PROPERTIES: libevdev.EV_KEY.KEY_PROPS.value,
        ConsumerControl.CC_AC_UNDO: libevdev.EV_KEY.KEY_UNDO.value,
        ConsumerControl.CC_AC_COPY: libevdev.EV_KEY.KEY_COPY.value,
        ConsumerControl.CC_AC_CUT: libevdev.EV_KEY.KEY_CUT.value,
        ConsumerControl.CC_AC_PASTE: libevdev.EV_KEY.KEY_PASTE.value,
        ConsumerControl.CC_AC_SELECT_ALL: libevdev.EV_KEY.KEY_SELECT.value,
        ConsumerControl.CC_AC_FIND: libevdev.EV_KEY.KEY_FIND.value,
        ConsumerControl.CC_AC_FINDAND_REPLACE: 0,
        ConsumerControl.CC_AC_SEARCH: libevdev.EV_KEY.KEY_SEARCH.value,
        ConsumerControl.CC_AC_GO_TO: libevdev.EV_KEY.KEY_GOTO.value,
        ConsumerControl.CC_AC_HOME: libevdev.EV_KEY.KEY_HOMEPAGE.value,
        ConsumerControl.CC_AC_BACK: libevdev.EV_KEY.KEY_BACK.value,
        ConsumerControl.CC_AC_FORWARD: libevdev.EV_KEY.KEY_FORWARD.value,
        ConsumerControl.CC_AC_STOP: libevdev.EV_KEY.KEY_STOP.value,
        ConsumerControl.CC_AC_REFRESH: libevdev.EV_KEY.KEY_REFRESH.value,
        ConsumerControl.CC_AC_PREVIOUS_LINK: libevdev.EV_KEY.KEY_PREVIOUS.value,
        ConsumerControl.CC_AC_NEXT_LINK: libevdev.EV_KEY.KEY_NEXT.value,
        ConsumerControl.CC_AC_BOOKMARKS: libevdev.EV_KEY.KEY_BOOKMARKS.value,
        ConsumerControl.CC_AC_HISTORY: 0,
        ConsumerControl.CC_AC_SUBSCRIPTIONS: 0,
        ConsumerControl.CC_AC_ZOOM_IN: libevdev.EV_KEY.KEY_ZOOMIN.value,
        ConsumerControl.CC_AC_ZOOM_OUT: libevdev.EV_KEY.KEY_ZOOMOUT.value,
        ConsumerControl.CC_AC_ZOOM: libevdev.EV_KEY.KEY_ZOOMRESET.value,
        ConsumerControl.CC_AC_FULL_SCREEN_VIEW: 0,
        ConsumerControl.CC_AC_NORMAL_VIEW: 0,
        ConsumerControl.CC_AC_VIEW_TOGGLE: 0,
        ConsumerControl.CC_AC_SCROLL_UP: libevdev.EV_KEY.KEY_SCROLLUP.value,
        ConsumerControl.CC_AC_SCROLL_DOWN: libevdev.EV_KEY.KEY_SCROLLDOWN.value,
        ConsumerControl.CC_AC_SCROLL: 0,
        ConsumerControl.CC_AC_PAN_LEFT: 0,
        ConsumerControl.CC_AC_PAN_RIGHT: 0,
        ConsumerControl.CC_AC_PAN: 0,
        ConsumerControl.CC_AC_NEW_WINDOW: 0,
        ConsumerControl.CC_AC_TILE_HORIZONTALLY: 0,
        ConsumerControl.CC_AC_TILE_VERTICALLY: 0,
        ConsumerControl.CC_AC_FORMAT: 0,
        ConsumerControl.CC_AC_EDIT: libevdev.EV_KEY.KEY_EDIT.value,
        ConsumerControl.CC_AC_BOLD: 0,
        ConsumerControl.CC_AC_ITALICS: 0,
        ConsumerControl.CC_AC_UNDERLINE: 0,
        ConsumerControl.CC_AC_STRIKETHROUGH: 0,
        ConsumerControl.CC_AC_SUBSCRIPT: 0,
        ConsumerControl.CC_AC_SUPERSCRIPT: 0,
        ConsumerControl.CC_AC_ALL_CAPS: 0,
        ConsumerControl.CC_AC_ROTATE: 0,
        ConsumerControl.CC_AC_RESIZE: 0,
        ConsumerControl.CC_AC_FLIPHORIZONTAL: 0,
        ConsumerControl.CC_AC_FLIP_VERTICAL: 0,
        ConsumerControl.CC_AC_MIRROR_HORIZONTAL: 0,
        ConsumerControl.CC_AC_MIRROR_VERTICAL: 0,
        ConsumerControl.CC_AC_FONT_SELECT: 0,
        ConsumerControl.CC_AC_FONT_COLOR: 0,
        ConsumerControl.CC_AC_FONT_SIZE: 0,
        ConsumerControl.CC_AC_JUSTIFY_LEFT: 0,
        ConsumerControl.CC_AC_JUSTIFY_CENTER_H: 0,
        ConsumerControl.CC_AC_JUSTIFY_RIGHT: 0,
        ConsumerControl.CC_AC_JUSTIFY_BLOCK_H: 0,
        ConsumerControl.CC_AC_JUSTIFY_TOP: 0,
        ConsumerControl.CC_AC_JUSTIFY_CENTER_V: 0,
        ConsumerControl.CC_AC_JUSTIFY_BOTTOM: 0,
        ConsumerControl.CC_AC_JUSTIFY_BLOCK_V: 0,
        ConsumerControl.CC_AC_INDENT_DECREASE: 0,
        ConsumerControl.CC_AC_INDENT_INCREASE: 0,
        ConsumerControl.CC_AC_NUMBERED_LIST: 0,
        ConsumerControl.CC_AC_RESTART_NUMBERING: 0,
        ConsumerControl.CC_AC_BULLETED_LIST: 0,
        ConsumerControl.CC_AC_PROMOTE: 0,
        ConsumerControl.CC_AC_DEMOTE: 0,
        ConsumerControl.CC_AC_YES: 0,
        ConsumerControl.CC_AC_NO: 0,
        ConsumerControl.CC_AC_CANCEL: libevdev.EV_KEY.KEY_CANCEL.value,
        ConsumerControl.CC_AC_CATALOG: 0,
        ConsumerControl.CC_AC_BUY_CHECKOUT: 0,
        ConsumerControl.CC_AC_ADDTO_CART: 0,
        ConsumerControl.CC_AC_EXPAND: 0,
        ConsumerControl.CC_AC_EXPAND_ALL: 0,
        ConsumerControl.CC_AC_COLLAPSE: 0,
        ConsumerControl.CC_AC_COLLAPSE_ALL: 0,
        ConsumerControl.CC_AC_PRINT_PREVIEW: 0,
        ConsumerControl.CC_AC_PASTE_SPECIAL: 0,
        ConsumerControl.CC_AC_INSERT_MODE: 0,
        ConsumerControl.CC_AC_DELETE: libevdev.EV_KEY.KEY_DELETE.value,
        ConsumerControl.CC_AC_LOCK: 0,
        ConsumerControl.CC_AC_UNLOCK: 0,
        ConsumerControl.CC_AC_PROTECT: 0,
        ConsumerControl.CC_AC_UNPROTECT: 0,
        ConsumerControl.CC_AC_ATTACH_COMMENT: 0,
        ConsumerControl.CC_AC_DELETE_COMMENT: 0,
        ConsumerControl.CC_AC_VIEW_COMMENT: 0,
        ConsumerControl.CC_AC_SELECT_WORD: 0,
        ConsumerControl.CC_AC_SELECT_SENTENCE: 0,
        ConsumerControl.CC_AC_SELECT_PARAGRAPH: 0,
        ConsumerControl.CC_AC_SELECT_COLUMN: 0,
        ConsumerControl.CC_AC_SELECT_ROW: 0,
        ConsumerControl.CC_AC_SELECT_TABLE: 0,
        ConsumerControl.CC_AC_SELECT_OBJECT: 0,
        ConsumerControl.CC_AC_REDO_REPEAT: libevdev.EV_KEY.KEY_REDO.value,
        ConsumerControl.CC_AC_SORT: 0,
        ConsumerControl.CC_AC_SORT_ASCENDING: 0,
        ConsumerControl.CC_AC_SORT_DESCENDING: 0,
        ConsumerControl.CC_AC_FILTER: 0,
        ConsumerControl.CC_AC_SET_CLOCK: 0,
        ConsumerControl.CC_AC_VIEW_CLOCK: 0,
        ConsumerControl.CC_AC_SELECT_TIME_ZONE: 0,
        ConsumerControl.CC_AC_EDIT_TIME_ZONES: 0,
        ConsumerControl.CC_AC_SET_ALARM: 0,
        ConsumerControl.CC_AC_CLEAR_ALARM: 0,
        ConsumerControl.CC_AC_SNOOZE_ALARM: 0,
        ConsumerControl.CC_AC_RESET_ALARM: 0,
        ConsumerControl.CC_AC_SYNCHRONIZE: 0,
        ConsumerControl.CC_AC_SEND_RECEIVE: 0,
        ConsumerControl.CC_AC_SEND_TO: 0,
        ConsumerControl.CC_AC_REPLY: libevdev.EV_KEY.KEY_REPLY.value,
        ConsumerControl.CC_AC_REPLY_ALL: 0,
        ConsumerControl.CC_AC_FORWARD_MSG: libevdev.EV_KEY.KEY_FORWARDMAIL.value,
        ConsumerControl.CC_AC_SEND: libevdev.EV_KEY.KEY_SEND.value,
        ConsumerControl.CC_AC_ATTACH_FILE: 0,
        ConsumerControl.CC_AC_UPLOAD: 0,
        # [HID_CC_AC_DOWNLOAD(SAVE_TARGET_AS)		] = 0,
        ConsumerControl.CC_AC_SET_BORDERS: 0,
        ConsumerControl.CC_AC_INSERT_ROW: 0,
        ConsumerControl.CC_AC_INSERT_COLUMN: 0,
        ConsumerControl.CC_AC_INSERT_FILE: 0,
        ConsumerControl.CC_AC_INSERT_PICTURE: 0,
        ConsumerControl.CC_AC_INSERT_OBJECT: 0,
        ConsumerControl.CC_AC_INSERT_SYMBOL: 0,
        ConsumerControl.CC_AC_SAVEAND_CLOSE: 0,
        ConsumerControl.CC_AC_RENAME: 0,
        ConsumerControl.CC_AC_MERGE: 0,
        ConsumerControl.CC_AC_SPLIT: 0,
        ConsumerControl.CC_AC_DISRIBUTE_HORIZONTALLY: 0,
        ConsumerControl.CC_AC_DISTRIBUTE_VERTICALLY: 0,
    }


@attr.frozen
class Item:
    class Type(enum.IntEnum):
        MAIN = 0b0000
        GLOBAL = 0b0100
        LOCAL = 0b1000
        RESERVED = 0b1100

    """
    One item as described in a HID Report Descriptor.
    """
    size: int = attr.ib(validator=attr.validators.in_((0, 1, 2, 4)))
    """
    The size in bytes, always one of 0, 1, 2, or 4
    """
    hid: int = attr.ib()
    """
    The HID usage of this field (the upper 6 bits of the prefix byte)
    """
    value: int = attr.ib()

    @hid.validator
    def _hid_validator(self, attribute, value):
        if value & 0x3:
            raise ValueError("Lowest two bits must be zero")

    @property
    def bTag(self) -> int:
        """
        The upper 4 bits of the prefix byte, "bTag" in the HID spec. Note that
        this includes the lower 4 bits set to zero, so the value is
        always >= 16.
        """
        return self.hid & 0b11110000

    @property
    def bType(self):
        """
        Returns one of :class:`Item.Type`
        """
        return Item.Type(self.hid & 0b00001100)


@attr.s
class Report:
    class Type(enum.IntEnum):
        INPUT = 0b10000000
        OUTPUT = 0b10010000
        FEATURE = 0b10110000

    """
    A HID Report as described in the Report Descriptor
    """

    report_id: int = attr.ib()
    type: Type = attr.ib()
    _bitsize: int = attr.ib(default=8)  # 1 byte default size for report ID

    @property
    def size(self):
        """
        Size in bytes
        """
        return self._bitsize // 8


@attr.s
class ReportDescriptor:
    """
    A minimal report descriptor parser, sufficient for the use of ratbag.
    """

    _reports: Dict[Report.Type, Dict[int, Report]] = attr.ib()
    """
    A tuple of the HID :class:`Report` described in this Report Descriptor
    """

    @property
    def input_reports(self):
        return self._reports[Report.Type.INPUT].values()

    @property
    def output_reports(self):
        return self._reports[Report.Type.OUTPUT].values()

    @property
    def feature_reports(self):
        return self._reports[Report.Type.FEATURE].values()

    @staticmethod
    def items(data: bytes) -> Iterator[Item]:
        """
        Iterate ``data``, yielding all :class:`Item` within this report
        descriptor.
        """
        idx = 0
        datalen = len(data)
        while idx < datalen:
            header = data[idx]
            sz = (0, 1, 2, 4)[header & 0x3]
            assert idx + sz < datalen

            fmt = (None, "B", ">H", None, ">I")[sz]
            if fmt is not None:
                value = struct.unpack_from(fmt, data, idx + 1)[0]
            else:
                value = 0

            yield Item(size=sz, hid=header & 0xFC, value=value)
            idx += 1 + sz

    @staticmethod
    def from_bytes(data: bytes) -> "ReportDescriptor":
        """
        Create a new report descriptor from the given bytes array.
        """
        rsize = 0
        rcount = 0
        current_report_id = None
        reports: Dict[Report.Type, Dict[int, Report]] = {
            Report.Type.INPUT: {},
            Report.Type.OUTPUT: {},
            Report.Type.FEATURE: {},
        }
        for item in ReportDescriptor.items(data):
            if item.hid == 0b10000100:  # HID Report ID
                current_report_id = item.value
            elif item.hid == 0b10010100:  # HID Report Count
                rcount = item.value
            elif item.hid == 0b01110100:  # HID Report Size
                rsize = item.value
            elif item.hid in (0b10000000, 0b10010000, 0b10110000):  # Hid Main Input
                if current_report_id is None:
                    raise NotImplementedError("This HID parser requires HID report IDs")
                rtype = Report.Type(item.hid)
                r = reports[rtype].get(
                    current_report_id,
                    Report(current_report_id, type=Report.Type(item.hid)),
                )
                r._bitsize += rcount * rsize
                reports[rtype][current_report_id] = r

        return ReportDescriptor(reports=reports)
