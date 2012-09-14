#!/usr/bin/env python
"""
================================================================================
:mod:`interface` -- Interface for the XEI Evactron de-contaminator
================================================================================

.. module:: interface
   :synopsis: Interface for the XEI Evactron de-contaminator

.. inheritance-diagram:: pyevactron.interface

The interface is build on top of the XEI Evactron de-contaminator API.
It wraps all functions available through the EvactronComm DLL which allow
modification to the configuration (plasma pressure/power/time, etc.) and access
to the measurements (pressure, power, time left, etc.)

The best way to connect to the device is to use Python context manager::

    from pyevactron.interface import connect
    
    comm_port = 1 # Communication port
    with connect(comm_port) as ev:
        print ev.pressure_Pa
        
The context manager ensures that the interface is disconnected from the 
device in the event of an error.

"""

# Script information for the file.
__author__ = "Philippe T. Pinard"
__email__ = "philippe.pinard@gmail.com"
__version__ = "0.1"
__copyright__ = "Copyright (c) 2012 Philippe T. Pinard"
__license__ = "GPL v3"

# Standard library modules.
import os
import sys
import time
import logging
import datetime
import ctypes as c

# Third party modules.

# Local modules.

# Globals and constants variables.
TORR2PA = 133.322

EVR_OK = 0
EVR_COMMANDIGNORED = 1403

class EvactronException(Exception):
    pass

class EvactronFault(Exception):
    pass

LowPressureFault = EvactronFault('The unit has encountered a low pressure fault.')
HighPressureFault = EvactronFault('The unit has encountered a high pressure fault.')
PlasmaFault = EvactronFault('The unit has encountered a plasma fault.')
PlasmaOutFault = EvactronFault('The unit has detected that the plasma went out during the plasma state.')
CableFault = EvactronFault('The RF cable is not connected.')
PressureGaugeFault = EvactronFault('The pressure gauge is not connected.')
EepromConfigFault = EvactronFault('The EEPROM configuration has become corrupted. It will be reset to factory defaults once acknowledged.')
EventLogFault = EvactronFault('The event log has become corrupted. It will be cleared and reformatted once the fault has been acknowledged.')
InternalFault = EvactronFault('An internal error has occurred.')
PressureTableFault = EvactronFault('An invalid pressure conversion table has been detected.')

_FAULTS = {1: LowPressureFault,
           2: HighPressureFault,
           3: PlasmaFault,
           4: PlasmaOutFault,
           7: CableFault,
           8: PressureGaugeFault,
           9: EepromConfigFault,
           10: EventLogFault,
           11: InternalFault,
           12: PressureTableFault}

class EvactronState(object):
    def __init__(self, message):
        self._message = message

    def __repr__(self):
        return "EvactronState('%s')" % self.message

    def __str__(self):
        return self.message

    @property
    def message(self):
        return self._message

InvalidState = EvactronState('Invalid state')
StartupState = EvactronState('Starting up')
InitializedState = EvactronState('Initialized')
ReadyState = EvactronState('Ready')
StabilizingPressureState = EvactronState('Stabiliing pressure')
WaitForIgnitionState = EvactronState('Waiting for ignition')
CleaningState = EvactronState('Cleaning')
PurgingState = EvactronState('Purging')
PumpDownState = EvactronState('Pumping down')
ConfigurationState = EvactronState('Front panel configuration on')

_STATES = {-1: InvalidState,
            0: StartupState,
            1: InitializedState,
           10: ReadyState,
           11: StabilizingPressureState,
           12: WaitForIgnitionState,
           13: CleaningState,
           14: PurgingState,
           15: PumpDownState,
           32: ConfigurationState}

_PRESSURE_UNITS = {0: 'Torr',
                   1: 'Pa',
                   2: 'mbar'}

def connect(comm_port):
    """
    Connect to the device and returns the :class:`EvactronInterface`
    """
    return EvactronInterface(comm_port)

class EvactronInterface(object):

    def __init__(self, comm_port):
        """
        Creates the interface to the Evactron device.
        
        :arg comm_port: number of the port to connect to the device
        :type comm_port: :class:`int`
        """
        self._comm_port = comm_port

        dirname = os.path.dirname(sys.modules[__name__].__file__)
        path = os.path.join(dirname, 'EvactronComm_VB6.dll')
        self._dll = c.WinDLL(path)

        self._handle = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

#- Action methods

    def connect(self):
        """
        .. warning::

           It is recommended to use the context manager ("with" statement) instead.

        Connects to the device.
        """
        retval = c.c_int()
        handle = self._dll.evbConnect(c.c_int(self._comm_port), c.byref(retval))
        if retval.value != EVR_OK:
            raise EvactronException, 'Cannot connect to device on port %i' % self._comm_port

        logging.debug('Connected to handle=%s' % handle)
        self._handle = c.c_long(handle)

    def disconnect(self):
        """
        .. warning::

           It is recommended to use the context manager ("with" statement) instead.

        Disconnects from the device.
        """
        if self._handle is None:
            return

        retval = self._dll.evbDisconnect(self._handle)
        if retval != EVR_OK:
            raise EvactronException, 'Cannot disconnect from device'

        logging.debug('Disconnected')
        self._handle = None

    def is_connected(self):
        """
        Returns whether the interface is connected to the device.
        """
        retval = c.c_int()

        is_connected = self._dll.evbIsConnected(self._handle, c.byref(retval))
        if retval.value != EVR_OK:
            raise EvactronException

        return bool(is_connected)

    def enable(self, enable=True):
        """
        Enables the device.
        """
        retval = self._dll.evbEnableUnit(self._handle, c.c_int(enable))
        if retval != EVR_OK:
            raise EvactronException

    def disable(self):
        """
        Disables the device.
        """
        self.enable(False)

#- Faults

    @property
    def faults(self):
        """
        Returns a :class:`tuple` of the dynamic and latched faults.
        Faults object are derived from Python's :class:`Exception`.
        They can be raised if needed.
        If no fault, ``None`` is returned.

        The faults can be cleared as follows::

            >>> with EvactronInterface(comm_port) as ev:
            ...     del ev.faults
        
        .. info::
        
           The Evactron maintains two flags for each fault: "dynamic" and 
           "latched".
           The first flag is called the "dynamic fault flag". 
           It denotes the status of the underlying fault condition. 
           This flag is set as long as the corresponding fault condition
           persists. 
           In the case of a cable fault, the f_Cable flag will remain set as 
           long as the Evactron
           application software detects that the RF cable is disconnected.
           The second flag is called the "latched fault flag"; it is named after 
           a device commonly used in digital electronics. 
           This flag is set by the Evactron application software when the fault 
           is first detected, 
           at the same time the dynamic flag is set. 
           It remains set until the underlying fault condition has cleared and 
           the fault is acknowledged by an operator via the Evactron front panel 
           or via the communications interface.
           In the case of a cable fault, both flags Dynamic.f_Cable and 
           Latched.f_Cable will be set when the application software detects 
           that the RF cable has been disconnected. 
           The application software will clear Dynamic.f_Cable when it detects
           that the RF cable has been reconnected. 
           Latched.f_Cable will remain set until the fault is acknowledged at 
           the front panel of the Evactron or via a command to clear faults via 
           the communications interface.
        """
        dynamic_bit = c.c_long()
        latched_bit = c.c_long()

        retval = self._dll.evbGetFaults(self._handle, c.byref(latched_bit),
                                        c.byref(dynamic_bit))
        if retval != EVR_OK:
            raise EvactronException

        dynamic = _FAULTS.get(dynamic_bit.value)
        latched = _FAULTS.get(latched_bit.value)

        return dynamic, latched

    @faults.deleter
    def faults(self):
        retval = self._dll.evbClearFaults(self._handle)
        if retval != EVR_OK and retval != EVR_COMMANDIGNORED:
            raise EvactronException

#- Read only

    def _get_status(self):
        """
        Returns the status of the device.
        """
        state = c.c_int()
        cycle = c.c_int()
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()
        units = c.c_int()
        status = c.c_long()

        retval = \
            self._dll.evbGetStatusEx(self._handle, c.byref(state), c.byref(cycle),
                                     c.byref(hour), c.byref(minute), c.byref(second),
                                     c.byref(units), c.byref(status))
        if retval != EVR_OK:
            raise EvactronException

        return (_STATES.get(state.value, state.value), cycle.value,
                datetime.time(hour.value, minute.value, second.value),
                _PRESSURE_UNITS[units.value], status.value)

    @property
    def dll_version(self):
        """
        Returns a :class:`tuple` of the major and minor version number of the DLL.
        """
        major = c.c_int()
        minor = c.c_int()

        retval = self._dll.evbGetDLLVersion(c.byref(major), c.byref(minor))
        if retval != EVR_OK:
            raise EvactronException

        return major.value, minor.value

    @property
    def firmware_version(self):
        """
        Returns a :class:`tuple` of the major and minor version number of the firmware.
        """
        major = c.c_int()
        minor = c.c_int()

        retval = self._dll.evbGetFirmwareVersion(self._handle,
                                                 c.byref(major), c.byref(minor))
        if retval != EVR_OK:
            raise EvactronException

        return major.value, minor.value

    @property
    def application_version(self):
        """
        Returns a :class:`tuple` of the major and minor version number of the 
        application.
        """
        major = c.c_int()
        minor = c.c_int()

        retval = self._dll.evbGetApplicationVersion(self._handle,
                                                    c.byref(major), c.byref(minor))
        if retval != EVR_OK:
            raise EvactronException

        return major.value, minor.value

    @property
    def last_clean(self):
        """
        Returns the last date and time at which the last cleaning state had 
        commenced.
        The date and time are returned as a Python :class:`datetime.datetime` 
        object.
        """
        day = c.c_int()
        month = c.c_int()
        year = c.c_int()
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()

        retval = \
            self._dll.evbGetLastCleanTime(self._handle,
                                          c.byref(month), c.byref(day), c.byref(year),
                                          c.byref(hour), c.byref(minute), c.byref(second))
        if retval != EVR_OK:
            raise EvactronException

        return datetime.datetime(year.value, month.value, day.value,
                                 hour.value, minute.value, second.value)

    @property
    def pressure_Pa(self):
        """
        Returns the measured pressure in Pascals.
        """
        pressure = c.c_float()

        retval = self._dll.evbGetPressure(self._handle, c.byref(pressure))
        if retval != EVR_OK:
            raise EvactronException

        return pressure.value * TORR2PA # Torr to Pa

    @property
    def forward_power_W(self):
        """
        Returns the measured forward power in Watts.
        """
        power = c.c_float()

        retval = self._dll.evbGetForwardPower(self._handle, c.byref(power))
        if retval != EVR_OK:
            raise EvactronException

        return power.value

    @property
    def reverse_power_W(self):
        """
        Returns the measured reverse power in Watts.
        """
        power = c.c_float()

        retval = self._dll.evbGetReversePower(self._handle, c.byref(power))
        if retval != EVR_OK:
            raise EvactronException

        return power.value

    @property
    def metering_valve_voltage_V(self):
        """
        Returns the measured metering valve voltage (in volts).
        """
        voltage = c.c_float()

        retval = self._dll.evbGetMeteringValveVoltage(self._handle, c.byref(voltage))
        if retval != EVR_OK:
            raise EvactronException

        return voltage.value

    @property
    def timer(self):
        """
        Returns the current run timer.
        The time is set and returned as a Python :class:`datetime.time` object.
        The timer reports the amount of time remianing in the current plasma or 
        purge state.
        If the device is not in the plasma or purge state, a time of 0 is 
        returned.
        """
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()

        retval = self._dll.evbGetRunTimer(self._handle, c.byref(hour),
                                          c.byref(minute), c.byref(second))
        if retval != EVR_OK:
            raise EvactronException

        return datetime.time(hour.value, minute.value, second.value)

#- General configuration

    @property
    def clock(self):
        """
        Returns/sets the clock on the device.
        The clock is set and returned as a Python :class:`datetime.datetime` 
        object.
        """
        day = c.c_int()
        month = c.c_int()
        year = c.c_int()
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()

        retval = self._dll.evbGetDate(self._handle, c.byref(month),
                                      c.byref(day), c.byref(year))
        if retval != EVR_OK:
            raise EvactronException

        retval = self._dll.evbGetTime(self._handle, c.byref(hour),
                                      c.byref(minute), c.byref(second))
        if retval != EVR_OK:
            raise EvactronException

        return datetime.datetime(year.value, month.value, day.value,
                                 hour.value, minute.value, second.value)

    @clock.setter
    def clock(self, dt):
        self.disable()
        time.sleep(0.1) # required

        day = c.c_int(dt.day)
        month = c.c_int(dt.month)
        year = c.c_int(dt.year)
        hour = c.c_int(dt.hour)
        minute = c.c_int(dt.minute)
        second = c.c_int(dt.second)

        retval = self._dll.evbSetDate(self._handle, month, day, year)
        if retval != EVR_OK:
            raise EvactronException

        retval = self._dll.evbSetTime(self._handle, hour, minute, second)
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

#- Plasma configuration

    @property
    def cycles(self):
        """
        Returns/sets the total number of process iterations.
        """
        cycles = c.c_int()

        retval = self._dll.evbGetCycleCount(self._handle, c.byref(cycles))
        if retval != EVR_OK:
            raise EvactronException

        return cycles.value

    @cycles.setter
    def cycles(self, cycles):
        self.disable()
        time.sleep(0.1)

        retval = self._dll.evbSetCycleCount(self._handle, c.c_int(cycles))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def ignite_pressure_setpoint_Pa(self):
        """
        Returns/sets the programmed pressure set-point for the plasma ignition 
        (in Pascals).
        """
        pressure = c.c_float()

        retval = self._dll.evbGetIgnitePressureSetpoint(self._handle,
                                                        c.byref(pressure))
        if retval != EVR_OK:
            raise EvactronException

        return pressure.value * TORR2PA # Torr to Pa

    @ignite_pressure_setpoint_Pa.setter
    def ignite_pressure_setpoint_Pa(self, pressure):
        self.disable()
        time.sleep(0.1)

        retval = \
            self._dll.evbSetIgnitePressureSetpoint(self._handle,
                                                   c.c_float(pressure / TORR2PA))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def plasma_pressure_setpoint_Pa(self):
        """
        Returns/sets the programmed pressure set-point for the plasma state (in Pascals).
        """
        pressure = c.c_float()

        retval = self._dll.evbGetPlasmaPressureSetpoint(self._handle,
                                                        c.byref(pressure))
        if retval != EVR_OK:
            raise EvactronException

        return pressure.value * TORR2PA # Torr to Pa

    @plasma_pressure_setpoint_Pa.setter
    def plasma_pressure_setpoint_Pa(self, pressure):
        self.disable()
        time.sleep(0.1)

        retval = \
            self._dll.evbSetPlasmaPressureSetpoint(self._handle,
                                                   c.c_float(pressure / TORR2PA))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def plasma_power_setpoint_W(self):
        """
        Returns/sets the power set-point for the plasmae (in watts).
        """
        power = c.c_float()

        retval = self._dll.evbGetPlasmaPowerSetpoint(self._handle, c.byref(power))
        if retval != EVR_OK:
            raise EvactronException

        return power.value

    @plasma_power_setpoint_W.setter
    def plasma_power_setpoint_W(self, power):
        self.disable()
        time.sleep(0.1)

        retval = self._dll.evbSetPlasmaPowerSetpoint(self._handle, c.c_float(power))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def plasma_time(self):
        """
        Returns/sets the plasma time.
        The time is set and returned as a Python :class:`datetime.time` object.

        .. warning::

           Seconds may be set to any of the following values: 0, 10, 20, 30, 
           40, 50, 60.
           Other values will be rounded down to the nearest ten.
        """
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()

        retval = self._dll.evbGetPlasmaTime(self._handle, c.byref(hour),
                                            c.byref(minute), c.byref(second))
        if retval != EVR_OK:
            raise EvactronException

        return datetime.time(hour.value, minute.value, second.value)

    @plasma_time.setter
    def plasma_time(self, t):
        self.disable()
        time.sleep(0.1)

        hour = c.c_int(t.hour)
        minute = c.c_int(t.minute)
        second = c.c_int((t.second / 10) * 10) # round down to closest ten

        retval = self._dll.evbSetPlasmaTime(self._handle, hour, minute, second)
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def purge(self):
        """
        Returns/sets whether the purge is enabled.
        """
        enabled = c.c_int()

        retval = self._dll.evbGetPurgeEnable(self._handle, c.byref(enabled))
        if retval != EVR_OK:
            raise EvactronException

        return bool(enabled.value)

    @purge.setter
    def purge(self, enabled):
        self.disable()
        time.sleep(0.1)

        retval = self._dll.evbEnablePurge(self._handle, c.c_int(enabled))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def purge_pressure_setpoint_Pa(self):
        """
        Returns/sets the programmed pressure set-point for the purge state 
        (in Pascals).
        """
        pressure = c.c_float()

        retval = self._dll.evbGetPurgePressureSetpoint(self._handle,
                                                       c.byref(pressure))
        if retval != EVR_OK:
            raise EvactronException

        return pressure.value * TORR2PA # Torr to Pa

    @purge_pressure_setpoint_Pa.setter
    def purge_pressure_setpoint_Pa(self, pressure):
        self.disable()
        time.sleep(0.1)

        retval = \
            self._dll.evbSetPurgePressureSetpoint(self._handle,
                                                  c.c_float(pressure / TORR2PA))
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

    @property
    def purge_time(self):
        """
        Returns/sets the purge time.
        The time is set and returned as a Python :class:`datetime.time` object.

        .. warning::

           Seconds may be set to any of the following values: 0, 10, 20, 30, 
           40, 50, 60.
           Other values will be rounded down to the nearest ten.
        """
        hour = c.c_int()
        minute = c.c_int()
        second = c.c_int()

        retval = self._dll.evbGetPurgeTime(self._handle, c.byref(hour),
                                           c.byref(minute), c.byref(second))
        if retval != EVR_OK:
            raise EvactronException

        return datetime.time(hour.value, minute.value, second.value)

    @purge_time.setter
    def purge_time(self, t):
        self.disable()
        time.sleep(0.1)

        hour = c.c_int(t.hour)
        minute = c.c_int(t.minute)
        second = c.c_int((t.second / 10) * 10) # round down to closest ten

        retval = self._dll.evbSetPurgeTime(self._handle, hour, minute, second)
        if retval != EVR_OK:
            raise EvactronException

        self.enable()

