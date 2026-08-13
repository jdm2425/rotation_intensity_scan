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
    POWER_METER,
    POWER_METER_STAGE,
)

from hardware.devices.rotation import RotationStage
from hardware.devices.shutter import BeamShutter
from hardware.devices.base import HardwareError
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

    def __init__(
        self,
        *,
        enable_power_meter: bool = False,
        manage_power_meter_stage: bool | None = None,
        power_meter_wavelength_option: str | None = None,
        power_meter_range_option: str | None = None,
    ):

        self.enable_power_meter = bool(enable_power_meter)
        self.manage_power_meter_stage = (
            POWER_METER_STAGE.installed
            if manage_power_meter_stage is None
            else bool(manage_power_meter_stage)
        )

        self.waveplate = RotationStage(
            serial=WAVEPLATE.serial,
            name=WAVEPLATE.name,
            maximum_velocity_deg_s=WAVEPLATE.maximum_velocity_deg_s,
        )

        self.sample = RotationStage(
            serial=SAMPLE_STAGE.serial,
            name=SAMPLE_STAGE.name,
            maximum_velocity_deg_s=SAMPLE_STAGE.maximum_velocity_deg_s,
        )

        self.shutter = BeamShutter(
            serial=SHUTTER.serial,
            name=SHUTTER.name,
        )

        self.spectrometer = OceanSR(
            serial=SPECTROMETER.serial,
            integration_time_ms=SPECTROMETER.integration_time_ms,
        )

        self.power_meter_stage = None
        self.power_meter = None
        self.power_probe = None

        if self.enable_power_meter and not self.manage_power_meter_stage:
            raise ValueError(
                "Power metering cannot be enabled while the insertion stage "
                "is configured as not installed."
            )

        if self.manage_power_meter_stage:
            # Optional vendor libraries remain lazily imported by the drivers.
            from hardware.devices.linear import PILinearStage
            from hardware.power_probe import RetractablePowerProbe

            self.power_meter_stage = PILinearStage.from_project_config(
                POWER_METER_STAGE
            )

            if self.enable_power_meter:
                from hardware.devices.power_meter import OphirJunoPowerMeter

                self.power_meter = OphirJunoPowerMeter(
                    controller_serial=POWER_METER.controller_serial,
                    sensor_serial=POWER_METER.sensor_serial,
                    wavelength_name=power_meter_wavelength_option,
                    fixed_range_name=power_meter_range_option,
                    name=POWER_METER.name,
                )

            self.power_probe = RetractablePowerProbe(
                shutter=self.shutter,
                insertion_stage=self.power_meter_stage,
                power_meter=self.power_meter,
                in_position_mm=POWER_METER_STAGE.in_position_mm,
                out_position_mm=POWER_METER_STAGE.out_position_mm,
                position_tolerance_mm=(
                    POWER_METER_STAGE.position_tolerance_mm
                ),
            )

            # Fail before any physical connection if the installed probe's
            # safe positions have not been established.
            self.power_probe.require_configured_positions()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):

        self.connect_all()

        return self

    def __exit__(self, exc_type, exc, tb):

        try:
            self.disconnect_all()
        except Exception:
            if exc is None:
                raise
            logger.exception(
                "Hardware cleanup also failed while preserving the original "
                "experiment exception."
            )

        return False

    # ------------------------------------------------------------------
    # Hardware control
    # ------------------------------------------------------------------

    def connect_all(self):

        logger.info("Connecting all hardware...")

        connected_devices = []

        try:
            # Establish the optical interlock before connecting any motor.
            self.shutter.connect()
            connected_devices.append(self.shutter)
            self.shutter.close()

            for device in (
                self.waveplate,
                self.sample,
            ):
                device.connect()
                connected_devices.append(device)

            self.spectrometer.connect()
            connected_devices.append(self.spectrometer)

            if self.power_meter_stage is not None:
                self.power_meter_stage.connect()
                connected_devices.append(self.power_meter_stage)
                self.power_meter_stage.prepare_for_closed_loop()

                # The stage is physically installed even when power sampling
                # is disabled. Always establish a verified unobstructed beam
                # path before an experiment can acquire spectra.
                self.power_probe.safe_retract()
                self.power_meter_stage.refresh_snapshot()

            if self.power_meter is not None:
                self.power_meter.connect()
                connected_devices.append(self.power_meter)

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

            if (
                self.power_probe is not None
                and self.power_meter_stage is not None
                and self.power_meter_stage.connected
            ):
                if self.shutter.connected:
                    try:
                        self.power_probe.safe_retract()
                    except Exception:
                        logger.exception(
                            "Failed to retract power meter during connection "
                            "cleanup."
                        )
                else:
                    logger.critical(
                        "Shutter unavailable during insertion-stage cleanup; "
                        "halting stage without commanding retraction."
                    )
                    try:
                        self.power_meter_stage.halt()
                    except Exception:
                        logger.exception("Failed to halt insertion stage.")

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

        safety_errors: list[BaseException] = []

        if self.shutter.connected:
            try:
                self.shutter.close()
            except Exception:
                safety_errors.append(
                    HardwareError("Beam shutter could not be closed.")
                )
                logger.exception(
                    "Failed to close beam shutter before disconnecting."
                )

        if (
            self.power_probe is not None
            and self.power_meter_stage is not None
            and self.power_meter_stage.connected
        ):
            if self.shutter.connected:
                try:
                    self.power_probe.safe_retract()
                    self.power_meter_stage.refresh_snapshot()
                except Exception:
                    safety_errors.append(
                        HardwareError(
                            "Power-meter out position could not be verified."
                        )
                    )
                    logger.exception(
                        "Failed to verify power-meter out position before "
                        "disconnecting hardware."
                    )
            else:
                safety_errors.append(
                    HardwareError(
                        "Insertion stage remains connected but the shutter "
                        "is unavailable; retraction was not attempted."
                    )
                )
                logger.critical(
                    "Cannot safely retract the power meter because shutter "
                    "closure is unavailable. Halting insertion stage."
                )
                try:
                    self.power_meter_stage.halt()
                except Exception:
                    logger.exception("Failed to halt insertion stage.")

        #
        # Disconnect in reverse order.
        #

        devices = [
            self.power_meter,
            self.power_meter_stage,
            self.spectrometer,
            self.shutter,
            self.sample,
            self.waveplate,
        ]

        for device in devices:

            if device is None:
                continue

            try:
                device.disconnect()

            except Exception:

                logger.exception(
                    "Error disconnecting %s",
                    device.name,
                )

        logger.info("All hardware disconnected.")

        if safety_errors:
            raise HardwareError(
                "Hardware disconnected after one or more safe-state "
                "verification failures; inspect the shutter and power-meter "
                "stage before enabling the laser."
            ) from safety_errors[0]

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def open_beam(self):

        self.require_sample_beam_path_clear()
        self.shutter.open()

    def close_beam(self):

        self.shutter.close()

    def require_sample_beam_path_clear(self):
        """Guard every sample-spectrum shutter opening with a live out check."""

        if self.power_probe is not None:
            self.power_probe.require_out()

    # ------------------------------------------------------------------
    # Device collection
    # ------------------------------------------------------------------

    @property
    def devices(self):

        devices = {
            "waveplate": self.waveplate,
            "sample": self.sample,
            "shutter": self.shutter,
            "spectrometer": self.spectrometer,
        }
        if self.power_meter_stage is not None:
            devices["power_meter_stage"] = self.power_meter_stage
        if self.power_meter is not None:
            devices["power_meter"] = self.power_meter
        return devices
    # ------------------------------------------------------------------

    def info(self):

        if (
            self.power_meter_stage is not None
            and self.power_meter_stage.connected
        ):
            self.power_meter_stage.refresh_snapshot()

        information = {
            name: device.info()
            for name, device in self.devices.items()
        }
        if self.power_probe is not None:
            information["power_probe"] = self.power_probe.info()
        return information

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
