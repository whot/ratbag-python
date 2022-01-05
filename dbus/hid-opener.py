#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#
# This file is formatted with Python Black

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, dbus_property, signal
from pathlib import Path


import asyncio
import errno


POLKIT_XML = """
<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<!-- GDBus 2.70.1 -->
<node>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="s" name="property_name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="GetAll">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="a{sv}" name="properties" direction="out"/>
    </method>
    <method name="Set">
      <arg type="s" name="interface_name" direction="in"/>
      <arg type="s" name="property_name" direction="in"/>
      <arg type="v" name="value" direction="in"/>
    </method>
    <signal name="PropertiesChanged">
      <arg type="s" name="interface_name"/>
      <arg type="a{sv}" name="changed_properties"/>
      <arg type="as" name="invalidated_properties"/>
    </signal>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect">
      <arg type="s" name="xml_data" direction="out"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Peer">
    <method name="Ping"/>
    <method name="GetMachineId">
      <arg type="s" name="machine_uuid" direction="out"/>
    </method>
  </interface>
  <interface name="org.freedesktop.PolicyKit1.Authority">
    <method name="EnumerateActions">
      <arg type="s" name="locale" direction="in">
      </arg>
      <arg type="a(ssssssuuua{ss})" name="action_descriptions" direction="out">
      </arg>
    </method>
    <method name="CheckAuthorization">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
      <arg type="s" name="action_id" direction="in">
      </arg>
      <arg type="a{ss}" name="details" direction="in">
      </arg>
      <arg type="u" name="flags" direction="in">
      </arg>
      <arg type="s" name="cancellation_id" direction="in">
      </arg>
      <arg type="(bba{ss})" name="result" direction="out">
      </arg>
    </method>
    <method name="CancelCheckAuthorization">
      <arg type="s" name="cancellation_id" direction="in">
      </arg>
    </method>
    <method name="RegisterAuthenticationAgent">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
      <arg type="s" name="locale" direction="in">
      </arg>
      <arg type="s" name="object_path" direction="in">
      </arg>
    </method>
    <method name="RegisterAuthenticationAgentWithOptions">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
      <arg type="s" name="locale" direction="in">
      </arg>
      <arg type="s" name="object_path" direction="in">
      </arg>
      <arg type="a{sv}" name="options" direction="in">
      </arg>
    </method>
    <method name="UnregisterAuthenticationAgent">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
      <arg type="s" name="object_path" direction="in">
      </arg>
    </method>
    <method name="AuthenticationAgentResponse">
      <arg type="s" name="cookie" direction="in">
      </arg>
      <arg type="(sa{sv})" name="identity" direction="in">
      </arg>
    </method>
    <method name="AuthenticationAgentResponse2">
      <arg type="u" name="uid" direction="in">
      </arg>
      <arg type="s" name="cookie" direction="in">
      </arg>
      <arg type="(sa{sv})" name="identity" direction="in">
      </arg>
    </method>
    <method name="EnumerateTemporaryAuthorizations">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
      <arg type="a(ss(sa{sv})tt)" name="temporary_authorizations" direction="out">
      </arg>
    </method>
    <method name="RevokeTemporaryAuthorizations">
      <arg type="(sa{sv})" name="subject" direction="in">
      </arg>
    </method>
    <method name="RevokeTemporaryAuthorizationById">
      <arg type="s" name="id" direction="in">
      </arg>
    </method>
    <signal name="Changed">
    </signal>
    <property type="s" name="BackendName" access="read">
    </property>
    <property type="s" name="BackendVersion" access="read">
    </property>
    <property type="u" name="BackendFeatures" access="read">
    </property>
  </interface>
</node>
"""


class HidrawOpener(ServiceInterface):
    """
    A DBus service that takes a /dev/hidraw path to open and responds with the
    file descriptor for that device, after checking with polkit.
    """

    def __init__(self):
        super().__init__("org.freedesktop.ratbag.Opener")
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self.dispatch(self._queue))

    @method()
    def Open(self, path: "s") -> "i":
        """
        Open the /dev/hidrawN device. The actual file descriptor is returned
        later in the Opened() signal.

        Returns 0 on success or a negative errno if the path is invalid.
        """
        if not path.startswith("/dev/hidraw"):
            return -errno.EINVAL
        if not Path(path).exists():
            return -errno.ENOENT
        self._queue.put_nowait(path)
        return 0

    @signal()
    def Opened(self, path, fd) -> "sh":
        """
        Emits the path and the file descriptor for this path, as requested earlier.
        """
        return [path, fd.fileno()]

    @signal()
    def FailedToOpen(self, path, status) -> "si":
        """
        Notify that the path failed to be opened (and the neg errno)
        """
        return [path, status]

    async def dispatch(self, queue):
        while True:
            path = await queue.get()
            if await self.check_polkit(path):
                self.Opened(path, open(path))
            else:
                self.FailedToOpen(path, errno.EACCES)
            queue.task_done()

    async def check_polkit(self, path: str) -> bool:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        proxy_obj = bus.get_proxy_object(
            "org.freedesktop.PolicyKit1",
            "/org/freedesktop/PolicyKit1/Authority",
            POLKIT_XML,
        )
        interface = proxy_obj.get_interface("org.freedesktop.PolicyKit1.Authority")

        subject = [
            "system-bus-name",
            {
                "name": Variant("s", bus.unique_name),
            },
        ]
        action_id = "org.freedesktop.ratbag.open-hidraw-device"
        details = {}
        flags = 0x01  # Interactive

        result = await interface.call_check_authorization(
            subject, action_id, details, flags, ""
        )
        is_authorized, is_challenge, details = result

        bus.disconnect()
        await bus.wait_for_disconnect()

        return is_authorized


async def main():

    bus = await MessageBus().connect()
    interface = HidrawOpener()
    bus.export("/org/freedesktop/ratbag/opener", interface)
    await bus.request_name("org.freedesktop.ratbag2")

    await bus.wait_for_disconnect()


asyncio.run(main())
