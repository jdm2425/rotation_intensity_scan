"""
rotation_stage.py

Generic rotation stage driver.

This driver provides a single implementation of the
BaseRotationStage interface using the PyLabLib Kinesis backend.

All PRM1-Z8 rotation stages in the project should use this class.
"""

from __future__ import annotations

import logging
import time

from pylablib.devices import Thorlabs

from hardware.devices.base import HardwareError
from hardware.devices.rotation.base import BaseRotationStage
from hardware.config import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TIMEOUT,
)

logger = logging.getLogger(__name__)


class RotationStage(BaseRotationStage):
    """
    Generic PyLabLib rotation stage.
    """

    def __init__(
        self,
        serial: str,
        name: str = "Rotation Stage",
        *,
        scale: str = "PRM1-Z8",
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):

        super().__init__(
            serial=serial,
            name=name,
        )

        self.scale = scale
        self.timeout = timeout
        self.poll_interval = poll_interval

        self._device = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):

        if self.connected:
            return

        logger.info(
            "%s: connecting (%s)...",
            self.name,
            self.serial,
        )

        try:

            self._device = Thorlabs.KinesisMotor(
                self.serial,
                scale=self.scale,
            )

        except Exception as exc:

            raise HardwareError(
                f"Failed to connect to {self.name}"
            ) from exc

        self._set_connected(True)

        logger.info(
            "%s connected.",
            self.name,
        )

    def disconnect(self):

        if not self.connected:
            return

        logger.info(
            "%s disconnecting...",
            self.name,
        )

        try:

            if self._device is not None:
                self._device.close()

        finally:

            self._device = None
            self._set_connected(False)

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------

    def home(self):

        self.require_connection()

        logger.info("%s homing...", self.name)

        self._device.home()

        self.wait()

    def move_to(
        self,
        angle_deg: float,
    ):

        self.require_connection()

        logger.info(
            "%s -> %.4f°",
            self.name,
            angle_deg,
        )

        self._device.move_to(float(angle_deg))

        self.wait()

    def move_by(
        self,
        angle_deg: float,
    ):

        self.require_connection()

        logger.info(
            "%s %+0.4f°",
            self.name,
            angle_deg,
        )

        self.move_to(
            self.position + float(angle_deg)
        )

    def stop(self):

        self.require_connection()

        if hasattr(self._device, "stop"):

            self._device.stop()

    def wait(self):

        self.require_connection()

        start = time.time()

        while self.is_moving:

            if time.time() - start > self.timeout:

                raise TimeoutError(
                    f"{self.name} failed to finish moving."
                )

            time.sleep(
                self.poll_interval
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def position(self) -> float:

        self.require_connection()

        return float(
            self._device.get_position()
        )

    @property
    def is_moving(self) -> bool:

        self.require_connection()

        return bool(
            self._device.is_moving()
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self):

        if self.connected:

            return (
                f"<RotationStage "
                f"serial='{self.serial}' "
                f"position={self.position:.4f}°>"
            )

        return (
            f"<RotationStage "
            f"serial='{self.serial}' "
            f"(disconnected)>"
        )