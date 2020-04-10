# pyevactron

![GitHub Workflow Status](https://img.shields.io/github/workflow/status/ppinard/pyevactron/CI)

Interface for the XEI Evactron de-contaminator. 
The interface is build on top of the XEI Evactron de-contaminator API.
It wraps all functions available through the EvactronComm DLL which allow
modification to the configuration (plasma pressure/power/time, etc.) and access
to the measurements (pressure, power, time left, etc.)

The best way to connect to the device is to use Python context manager:

```python

from pyevactron.interface import connect

comm_port = 1 # Communication port
with connect(comm_port) as ev:
    print(ev.pressure_Pa)
```
        
The context manager ensures that the interface is disconnected from the 
device in the event of an error.


## Installation

For development installation from the git repository::

```
git clone git@github.com/ppinard/pyevactron.git
cd pyevactron
pip install -e .
```

## Release notes

### 0.1.0


## Contributors


## License

The library is provided under the MIT license license.

Copyright (c) 2012-, Philippe Pinard





