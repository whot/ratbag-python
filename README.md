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

The public API, i.e. the bits to be consumed by various tools and ratbagd is
in the `ratbag` module (`ratbag/__init__.py`). This provides the various
high-level entities like `Device`, `Profile` and `Resolution`.

The drivers are in the `ratbag.driver` module
(`ratbag/drivers/drivername.py`) and the API for drivers and helpers are in
`ratbag/drivers/__init__.py`.

A driver has a `probe()` function that is called when that driver is assigned
to a physical device. This function should set up (one or more)
`ratbag.Device` or throw an exception on error. How the driver does this is
left to the driver.

The rest is largely handled by GObject signals - changes from user tools
are signalled back to the driver which then writes to the device. And signals
the status back to the frontend API.

Start at the `ratbag.Ratbag` documentation here:
https://whot.github.io/ratbag-python/ratbag.html#ratbag.Ratbag


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
