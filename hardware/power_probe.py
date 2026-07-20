"""Safety interlock for a shutter-upstream retractable power meter.

This module describes the laboratory role of otherwise reusable device
drivers. The PI stage and Ophir meter do not know about the optical layout;
this coordinator enforces that the shutter is closed and verified before any
insertion-stage motion.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Callable

from hardware.devices.base import HardwareError

logger = logging.getLogger(__name__)


class PowerProbeError(HardwareError):
    """Base error for the retractable incident-power probe."""


class PowerProbeConfigurationError(PowerProbeError):
    """Raised before motion when in/out positions are not safely configured."""


class PowerProbeMeasurementError(PowerProbeError):
    """Meter acquisition failed, but the probe was safely retracted."""


class PowerProbeSafetyError(PowerProbeError):
    """The shutter or insertion-stage safe state could not be verified."""


class RetractablePowerProbe:
    """Coordinate shutter, insertion stage, and power meter.

    The fixed sequence is:

    ``close -> move in -> open -> settle -> sample -> close -> move out``.

    A meter error is recoverable only after the shutter-closed out position
    has been verified. Shutter or stage failures are always safety failures.
    """

    def __init__(
        self,
        *,
        shutter,
        insertion_stage,
        power_meter,
        in_position_mm: float | None,
        out_position_mm: float | None,
        position_tolerance_mm: float = 0.01,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.shutter = shutter
        self.insertion_stage = insertion_stage
        self.power_meter = power_meter
        self.in_position_mm = self._position_or_none(in_position_mm)
        self.out_position_mm = self._position_or_none(out_position_mm)
        self.position_tolerance_mm = float(position_tolerance_mm)
        if (
            not math.isfinite(self.position_tolerance_mm)
            or self.position_tolerance_mm <= 0
        ):
            raise ValueError(
                "Power-probe position tolerance must be finite and positive."
            )
        self._sleep = sleep

    @staticmethod
    def _position_or_none(value: float | None) -> float | None:
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Power-probe positions must be finite.")
        return value

    def require_configured_positions(self) -> tuple[float, float]:
        if self.in_position_mm is None or self.out_position_mm is None:
            raise PowerProbeConfigurationError(
                "Power-meter stage in_position_mm and out_position_mm must "
                "both be established physically in hardware.config before "
                "incident-power acquisition can be enabled."
            )
        if math.isclose(
            self.in_position_mm,
            self.out_position_mm,
            abs_tol=self.position_tolerance_mm,
            rel_tol=0.0,
        ):
            raise PowerProbeConfigurationError(
                "Power-meter in and out positions must be distinct by more "
                "than the configured position tolerance."
            )
        return self.in_position_mm, self.out_position_mm

    def acquire_trace(
        self,
        *,
        duration_s: float,
        settle_time_s: float = 0.0,
        poll_interval_s: float = 0.1,
    ):
        """Acquire one trace, guaranteeing a shutter-closed retract attempt."""

        in_position, out_position = self.require_configured_positions()
        duration_s = float(duration_s)
        settle_time_s = float(settle_time_s)
        if not math.isfinite(duration_s) or duration_s <= 0:
            raise ValueError("Power measurement duration must be positive.")
        if not math.isfinite(settle_time_s) or settle_time_s < 0:
            raise ValueError("Power measurement settle time cannot be negative.")

        operation = "closing shutter before insertion"
        primary_error: BaseException | None = None
        trace = None
        try:
            self._close_and_verify_shutter()

            operation = "moving power meter into the beam path"
            self._move_and_verify(in_position)

            operation = "opening shutter for power acquisition"
            self._open_and_verify_shutter()

            operation = "waiting for the power sensor to settle"
            if settle_time_s > 0:
                self._sleep(settle_time_s)

            operation = "acquiring power-meter data"
            trace = self.power_meter.acquire_trace(
                duration_s,
                poll_interval_s=poll_interval_s,
            )
        except BaseException as error:
            primary_error = error
        finally:
            cleanup_error = self._close_then_retract(out_position)

        if cleanup_error is not None:
            message = (
                "Could not verify a safe shutter-closed, power-meter-out "
                f"state after {operation}: {cleanup_error}"
            )
            if primary_error is not None:
                message += f" (original error: {primary_error})"
            raise PowerProbeSafetyError(message) from cleanup_error

        if primary_error is not None:
            if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
                raise primary_error
            if operation == "acquiring power-meter data":
                raise PowerProbeMeasurementError(
                    "Incident-power acquisition failed; the shutter was "
                    "closed and the probe was returned to its verified out "
                    f"position. No power value was inferred: {primary_error}"
                ) from primary_error
            raise PowerProbeSafetyError(
                f"Power-probe operation failed while {operation}: "
                f"{primary_error}"
            ) from primary_error

        return trace

    def safe_retract(self) -> None:
        """Close the shutter and place the meter at its verified out position."""

        _, out_position = self.require_configured_positions()
        error = self._close_then_retract(out_position)
        if error is not None:
            raise PowerProbeSafetyError(
                "Could not establish the shutter-closed power-meter-out "
                f"state: {error}"
            ) from error

    def require_out(self) -> None:
        """Refuse sample illumination unless the live out position is verified."""

        _, out_position = self.require_configured_positions()
        actual = self._stage_position_mm()
        if not math.isclose(
            actual,
            out_position,
            abs_tol=self.position_tolerance_mm,
            rel_tol=0.0,
        ):
            raise PowerProbeSafetyError(
                "Sample-beam opening refused because the power meter is not "
                "at its verified out position: "
                f"expected={out_position:.6g} mm, actual={actual:.6g} mm."
            )

    def _close_then_retract(self, out_position: float) -> BaseException | None:
        try:
            self._close_and_verify_shutter()
        except BaseException as error:
            # Never command stage motion when upstream shutter closure is not
            # positively verified.
            return error

        try:
            self._move_and_verify(out_position)
        except BaseException as error:
            return error
        return None

    def _close_and_verify_shutter(self) -> None:
        self.shutter.close()
        if not bool(self.shutter.is_closed):
            raise PowerProbeSafetyError(
                "Beam shutter did not report the closed state."
            )

    def _open_and_verify_shutter(self) -> None:
        self.shutter.open()
        if not bool(self.shutter.is_open):
            raise PowerProbeSafetyError(
                "Beam shutter did not report the open state."
            )

    def _move_and_verify(self, target_mm: float) -> None:
        self.insertion_stage.move_absolute_mm(target_mm)
        position = self._stage_position_mm()
        if not math.isclose(
            position,
            target_mm,
            abs_tol=self.position_tolerance_mm,
            rel_tol=0.0,
        ):
            raise PowerProbeSafetyError(
                "Power-meter stage did not reach its requested position: "
                f"target={target_mm:.6g} mm, actual={position:.6g} mm."
            )

    def _stage_position_mm(self) -> float:
        for attribute_name in ("position_mm", "current_position_mm"):
            if hasattr(self.insertion_stage, attribute_name):
                value = getattr(self.insertion_stage, attribute_name)
                if callable(value):
                    value = value()
                position = float(value)
                if not math.isfinite(position):
                    break
                return position
        raise PowerProbeSafetyError(
            "Insertion stage does not expose a finite verified position in mm."
        )

    @property
    def is_out(self) -> bool:
        if self.out_position_mm is None:
            return False
        try:
            return math.isclose(
                self._stage_position_mm(),
                self.out_position_mm,
                abs_tol=self.position_tolerance_mm,
                rel_tol=0.0,
            )
        except (HardwareError, TypeError, ValueError):
            return False

    def info(self) -> dict:
        return {
            "in_position_mm": self.in_position_mm,
            "out_position_mm": self.out_position_mm,
            "position_tolerance_mm": self.position_tolerance_mm,
            "is_out": self.is_out,
            "optical_layout": "shutter_upstream_of_power_meter",
        }
