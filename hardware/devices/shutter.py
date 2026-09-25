"""
shutter.py

Driver for the Thorlabs MFF filter flipper.

Logical interface:

    shutter.open()
    shutter.close()
    shutter.toggle()

The underlying Kinesis state numbers are hidden from the user.

State mapping
-------------
0 = Beam OPEN
1 = Beam CLOSED
"""

from __future__ import annotations

import logging
import time
import warnings

from hardware.devices.base import HardwareDevice, HardwareError

logger = logging.getLogger(__name__)


class BeamShutterError(HardwareError):
    """Beam shutter exception."""


class BeamShutter(HardwareDevice):

    OPEN = 0
    CLOSED = 1

    def __init__(
        self,
        name: str,
        serial: str,
        timeout: float = 5.0,
        poll_time: float = 0.05,
    ):

        super().__init__(name)

        self.serial = serial
        self.timeout = timeout
        self.poll_time = poll_time

        self._device = None

    # ---------------------------------------------------------
    # Connection
    # ---------------------------------------------------------

    def connect(self):

        if self.connected:
            return

        from pylablib.devices import Thorlabs

        logger.info(
            "%s: connecting (%s)",
            self.name,
            self.serial,
        )

        #
        # Suppress the harmless model warning
        #
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            self._device = Thorlabs.MFF(
                self.serial
            )

        self._connected = True

        logger.info(
            "%s connected",
            self.name,
        )

    def disconnect(self):

        if not self.connected:
            return

        logger.info(
            "%s disconnecting",
            self.name,
        )

        try:

            if hasattr(self._device, "close"):
                self._device.close()

        finally:

            self._device = None
            self._connected = False

    # ---------------------------------------------------------
    # State
    # ---------------------------------------------------------

    @property
    def state(self) -> int | None:

        self.require_connection()

        state = self._device.get_state()

        if state is None:
            return None

        return int(state)

    @property
    def is_open(self) -> bool:

        return self.state == self.OPEN

    @property
    def is_closed(self) -> bool:

        return self.state == self.CLOSED

    def check_connection(self) -> bool:
        """Perform one read-only flipper-state query."""

        _ = self.state
        return True

    # ---------------------------------------------------------
    # Waiting
    # ---------------------------------------------------------

    def wait(self):

        self.require_connection()

        self._device.wait_for_status(
            ["moving_fw", "moving_bk"],
            enabled=False,
            timeout=self.timeout,
            period=self.poll_time,
        )

    # ---------------------------------------------------------
    # Motion
    # ---------------------------------------------------------

    def open(self):

        self.require_connection()

        if self.is_open:

            logger.info(
                "%s already open",
                self.name,
            )

            return

        logger.info(
            "%s opening",
            self.name,
        )

        self._device.move_to_state(
            self.OPEN
        )

        self.wait()

    def close(self):

        self.require_connection()

        if self.is_closed:

            logger.info(
                "%s already closed",
                self.name,
            )

            return

        logger.info(
            "%s closing",
            self.name,
        )

        self._device.move_to_state(
            self.CLOSED
        )

        self.wait()

    def toggle(self):

        if self.is_open:

            self.close()

        else:

            self.open()

    # ---------------------------------------------------------
    # Information
    # ---------------------------------------------------------

    def info(self):

        return {

            "name": self.name,

            "serial": self.serial,

            "state": self.state,

            "beam_open": self.is_open,

            "connected": self.connected,

        }
