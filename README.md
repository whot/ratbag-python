# ratbag-python

A Python implementation of libratbag, possibly replacing the actual libratbag
eventually.

## Architecture

The public API, i.e. the bits to be consumed by various tools and ratbagd is
in the `ratbag` module (`ratbag/__init__.py`). This provides the various
high-level entities like `Device`, `Profile` and `Resolution`.

The drivers are in the `ratbag.drivers` module
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
