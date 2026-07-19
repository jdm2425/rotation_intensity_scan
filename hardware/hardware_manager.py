"""
hardware_manager.py

Creates and manages all laboratory hardware.

The HardwareManager owns every physical device and provides a
single interface to connect/disconnect the complete experiment.

Experiment code should only interact with HardwareManager rather
than constructing individual hardware drivers.
"""

from __future__ import annotations

import logging

from hardware.config import (
    WAVEPLATE,
    SAMPLE_STAGE,
    SHUTTER,
    SPECTROMETER,
)

from hardware.devices.rotation import RotationStage
from hardware.devices.shutter import BeamShutter
from hardware.devices.spectrometer.ocean_sr import OceanSR

logger = logging.getLogger(__name__)


class HardwareManager:
    """
    Owns every hardware device.

    Example
    -------

    with HardwareManager() as hw:

        hw.waveplate.move_to(45)

        hw.sample.move_by(10)

        hw.shutter.open()
    """

    def __init__(self):

        self.waveplate = RotationStage(
            serial=WAVEPLATE.serial,
            name=WAVEPLATE.name,
        )

        self.sample = RotationStage(
            serial=SAMPLE_STAGE.serial,
            name=SAMPLE_STAGE.name,
        )

        self.shutter = BeamShutter(
            serial=SHUTTER.serial,
            name=SHUTTER.name,
        )

        self.spectrometer = OceanSR(
            serial=SPECTROMETER.serial,
            integration_time_ms=SPECTROMETER.integration_time_ms,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):

        self.connect_all()

        return self

    def __exit__(self, exc_type, exc, tb):

        self.disconnect_all()

        return False

    # ------------------------------------------------------------------
    # Hardware control
    # ------------------------------------------------------------------

    def connect_all(self):

        logger.info("Connecting all hardware...")

        connected_devices = []

        try:
            for device in (
                self.waveplate,
                self.sample,
                self.shutter,
            ):
                device.connect()
                connected_devices.append(device)

            # Establish the safe optical state as soon as the shutter is
            # available, before connecting the remaining hardware.
            self.shutter.close()

            self.spectrometer.connect()
            connected_devices.append(self.spectrometer)

        except Exception:
            logger.exception(
                "Hardware connection failed; cleaning up connected devices."
            )

            if self.shutter.connected:
                try:
                    self.shutter.close()
                except Exception:
                    logger.exception(
                        "Failed to close beam shutter during connection cleanup."
                    )

            for device in reversed(connected_devices):
                try:
                    device.disconnect()
                except Exception:
                    logger.exception(
                        "Error disconnecting %s after connection failure.",
                        device.name,
                    )

            raise

        logger.info("All hardware connected.")

    def disconnect_all(self):

        logger.info("Disconnecting hardware...")

        if self.shutter.connected:
            try:
                self.shutter.close()
            except Exception:
                logger.exception(
                    "Failed to close beam shutter before disconnecting."
                )

        #
        # Disconnect in reverse order.
        #

        for device in (
            self.spectrometer,
            self.shutter,
            self.sample,
            self.waveplate,
        ):

            try:
                device.disconnect()

            except Exception:

                logger.exception(
                    "Error disconnecting %s",
                    device.name,
                )

        logger.info("All hardware disconnected.")

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def open_beam(self):

        self.shutter.open()

    def close_beam(self):

        self.shutter.close()

    # ------------------------------------------------------------------
    # Device collection
    # ------------------------------------------------------------------

    @property
    def devices(self):

        return {
            "waveplate": self.waveplate,
            "sample": self.sample,
            "shutter": self.shutter,
            "spectrometer": self.spectrometer,
        }
    # ------------------------------------------------------------------

    def info(self):

        return {
            name: device.info()
            for name, device in self.devices.items()
        }

    def summary(self):

        return self.info()

    # ------------------------------------------------------------------

    def __repr__(self):

        return (
            "<HardwareManager "
            f"waveplate={self.waveplate.connected} "
            f"sample={self.sample.connected} "
            f"shutter={self.shutter.connected}>"
        )
