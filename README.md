# ratbag-python

A Python implementation of libratbag, intended to replace libratbag
eventually. Some of the motivation is discussed in
https://github.com/libratbag/libratbag/issues/1247

## Setup

This repository needs the libratbag data files to work, usually in
/usr/share/libratbag after installing libratbag. Alternatively, symlink to the
`data/` directory in the libratbag git tree in the root directory of this
repository.

## Architecture

The public API, i.e. the bits to be consumed by various tools is in the
`ratbag` module (`ratbag/__init__.py`). This provides the various high-level
entities like `Device`, `Profile` and `Resolution` and the `Ratbag` context to
tie them all together.

The drivers are in the `ratbag.drivers` subpackage
(`ratbag/drivers/drivername.py`) and the API for drivers and helpers are in
`ratbag/driver.py`.

A driver has a `new_from_devicelist()` class method that is called when that
driver is loaded. This function is called with a list of all known supported
devices and should detect any devices in the system. These should be set up as
one or more `ratbag.Device`.  How the driver does this is left to the driver.
Since most of the drivers deal with hidraw devices, there is a
convenience class `HidrawDriver` that does most of the above so the driver
only needs to implement device-specifics.

The rest is largely handled by GObject signals - changes from user tools
are signalled back to the driver which then writes to the device. And signals
the status back to the frontend API.

Start at the `ratbag.Ratbag` documentation here:
https://whot.github.io/ratbag-python/ratbag.html#ratbag.Ratbag

### Control Flow

The overview of the control flow:

```
caller       |   Ratbag                 |    driver
----------------------------------------|---------------
Ratbag()     |                          |
           ---->  load data files       |
             |    instantiate drivers  ----> search/monitor devices
.............. GLib.MainLoop doing its thing ...............
             |                          |    probe new device
             |                          |    create ratbagd.Device
             |        receive         <---  'device-added' signal
receive    <---  'device-added' signal  |
refresh UI   |                          |
.............. GLib.MainLoop doing its thing ...............
change dpi   |                          |
change btn   |                          |
dev.commit()----->  "commit" signal ------->  receive
             |                          |  write changes to device
.............. GLib.MainLoop doing its thing ...............
             |                          |
receive  <------------------------------  "complete" signal on commit transaction
refresh UI   |                          |
```

The `Ratbag` context object merely separates the public API from the driver
implementation. It has little logic beyond what is necessary to load the data
files and instantiate all available drivers.

### Usage of GObject

We're using GObject/GLib for convenience, however this has some notable
effects on the implementation:

- a ``GLib.MainLoop`` is required
- the API uses `set_foo` instead of `@property.setter` because we cannot throw
  exceptions in a GObject property setter.

Only properties that are expected to change are of type GObject.Property -
callers *may* want to subscribe to notifications on those properties.
Properties that are read-only and constant for the lifetime of the object are
regular Python properties.

Eventually we may get rid of GObject and then this will have been a great
idea.
