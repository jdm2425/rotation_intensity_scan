"""Safety interlock for a shutter-upstream retractable power meter.

The PI stage and Ophir meter are reusable device drivers which do not know
where they sit in the optical layout.  This coordinator owns the laboratory
sequence and ensures that insertion-stage motion occurs only with the shutter
closed and verified.

Two acquisition styles are supported:

``acquire_trace(...)``
    One-shot sequence: close, insert, measure, close, retract.

``measurement_session()``
    Persistent insertion for a bounded feedback block.  The probe is inserted
    once, each trace opens and re-closes the shutter, and the probe is retracted
    once when the context exits.  Waveplate motion should occur only after
    ``session.prepare_for_motion()`` has verified the shutter closed and the
    probe still at the configured in position.
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
    """Raised before motion when the probe cannot be used safely."""


class PowerProbeMeasurementError(PowerProbeError):
    """Meter acquisition failed, but a safe optical state was recovered."""


class PowerProbeSafetyError(PowerProbeError):
    """The shutter or insertion-stage safe state could not be verified."""


class PowerProbeMeasurementSession:
    """Keep the probe inserted across several shutter-gated power traces.

    Instances are created by :meth:`RetractablePowerProbe.measurement_session`.
    The session is intentionally single-use and must be entered as a context
    manager.
    """

    def __init__(self, probe: RetractablePowerProbe) -> None:
        self._probe = probe
        self._active = False
        self._in_position_mm: float | None = None
        self._out_position_mm: float | None = None

    @property
    def active(self) -> bool:
        """Whether the probe is currently held in the measurement position."""

        return self._active

    def __enter__(self) -> PowerProbeMeasurementSession:
        if self._active:
            raise PowerProbeSafetyError("Power-probe session is already active.")
        if self._probe._session_active:
            raise PowerProbeSafetyError(
                "Another power-probe measurement session is already active."
            )

        in_position, out_position = self._probe.require_configured_positions()
        self._in_position_mm = in_position
        self._out_position_mm = out_position

        operation = "closing shutter before probe insertion"
        primary_error: BaseException | None = None
        try:
            self._probe._close_and_verify_shutter()
            operation = "moving power meter into the beam path"
            self._probe._move_and_verify(in_position)
            self._probe._require_position(in_position, role="in")
        except BaseException as error:
            primary_error = error

        if primary_error is not None:
            cleanup_error = self._probe._close_then_retract(out_position)
            if cleanup_error is not None:
                raise PowerProbeSafetyError(
                    "Could not recover a shutter-closed, power-meter-out state "
                    f"after {operation}: {cleanup_error} "
                    f"(original error: {primary_error})"
                ) from cleanup_error
            if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
                raise primary_error
            raise PowerProbeSafetyError(
                f"Power-probe session failed while {operation}: {primary_error}"
            ) from primary_error

        self._probe._session_active = True
        self._active = True
        logger.info(
            "Power probe inserted at %.6g mm for a persistent measurement session.",
            in_position,
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not self._active:
            return False

        out_position = self._out_position_mm
        cleanup_error: BaseException | None = None
        try:
            if out_position is None:
                cleanup_error = PowerProbeConfigurationError(
                    "Power-probe session lost its configured out position."
                )
            else:
                cleanup_error = self._probe._close_then_retract(out_position)
        finally:
            self._active = False
            self._probe._session_active = False

        if cleanup_error is not None:
            message = (
                "Could not verify a shutter-closed, power-meter-out state "
                f"while ending the persistent measurement session: {cleanup_error}"
            )
            if exc is not None:
                message += f" (original error: {exc})"
            raise PowerProbeSafetyError(message) from cleanup_error

        logger.info("Persistent power-probe session ended with the probe retracted.")
        return False

    def prepare_for_motion(self) -> None:
        """Verify the state required before moving the waveplate.

        The probe remains inserted, but the shutter must be closed so the
        waveplate cannot sweep through unobserved optical powers while exposed.
        """

        self._require_active()
        self._probe._close_and_verify_shutter()
        assert self._in_position_mm is not None
        self._probe._require_position(self._in_position_mm, role="in")

    def acquire_trace(
        self,
        *,
        duration_s: float,
        settle_time_s: float = 0.0,
        poll_interval_s: float = 0.1,
    ):
        """Acquire one trace without retracting the probe afterwards.

        The method begins and ends with the shutter closed and verifies that
        the probe is still at its configured in position.  Retraction remains
        the responsibility of the surrounding context manager.
        """

        self._require_active()
        duration_s, settle_time_s, poll_interval_s = (
            self._probe._validate_trace_settings(
                duration_s=duration_s,
                settle_time_s=settle_time_s,
                poll_interval_s=poll_interval_s,
            )
        )
        if self._probe.power_meter is None:
            raise PowerProbeConfigurationError(
                "A power meter is required for a measurement session."
            )

        self.prepare_for_motion()

        operation = "opening shutter for power acquisition"
        primary_error: BaseException | None = None
        trace = None
        try:
            self._probe._open_and_verify_shutter()
            operation = "waiting for the power sensor to settle"
            if settle_time_s > 0:
                self._probe._sleep(settle_time_s)
            operation = "acquiring power-meter data"
            trace = self._probe.power_meter.acquire_trace(
                duration_s,
                poll_interval_s=poll_interval_s,
            )
        except BaseException as error:
            primary_error = error
        finally:
            try:
                self._probe._close_and_verify_shutter()
            except BaseException as error:
                close_error = error
            else:
                close_error = None

        if close_error is not None:
            message = (
                "Could not verify shutter closure after a persistent power "
                f"measurement while {operation}: {close_error}"
            )
            if primary_error is not None:
                message += f" (original error: {primary_error})"
            raise PowerProbeSafetyError(message) from close_error

        if primary_error is not None:
            if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
                raise primary_error
            if operation == "acquiring power-meter data":
                raise PowerProbeMeasurementError(
                    "Incident-power acquisition failed; the shutter was closed "
                    "and the probe remains at its verified in position for "
                    f"session cleanup. No power was inferred: {primary_error}"
                ) from primary_error
            raise PowerProbeSafetyError(
                f"Persistent power-probe operation failed while {operation}: "
                f"{primary_error}"
            ) from primary_error

        assert self._in_position_mm is not None
        self._probe._require_position(self._in_position_mm, role="in")
        return trace

    def _require_active(self) -> None:
        if not self._active:
            raise PowerProbeSafetyError(
                "Power-probe measurement session is not active. Use it inside "
                "a 'with probe.measurement_session() as session:' block."
            )


class RetractablePowerProbe:
    """Coordinate shutter, insertion stage, and power meter.

    A one-shot trace uses ``close -> move in -> open -> sample -> close -> out``.
    A persistent session inserts only once and retracts only once, while every
    individual trace remains shutter-gated.
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
        if not callable(sleep):
            raise TypeError("sleep must be callable.")
        self._sleep = sleep
        self._session_active = False

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

    def measurement_session(self) -> PowerProbeMeasurementSession:
        """Create a context which keeps the probe inserted across traces."""

        return PowerProbeMeasurementSession(self)

    def acquire_trace(
        self,
        *,
        duration_s: float,
        settle_time_s: float = 0.0,
        poll_interval_s: float = 0.1,
    ):
        """Acquire one trace with one insertion and one verified retraction."""

        with self.measurement_session() as session:
            return session.acquire_trace(
                duration_s=duration_s,
                settle_time_s=settle_time_s,
                poll_interval_s=poll_interval_s,
            )

    def safe_retract(self) -> None:
        """Close the shutter and place the meter at its verified out position."""

        if self._session_active:
            raise PowerProbeSafetyError(
                "Cannot call safe_retract() while a measurement session is active; "
                "exit the session context so it can perform verified cleanup."
            )
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
        self._require_position(out_position, role="out")

    def require_in(self) -> None:
        """Verify that the probe is at the configured measurement position."""

        in_position, _ = self.require_configured_positions()
        self._require_position(in_position, role="in")

    def _close_then_retract(self, out_position: float) -> BaseException | None:
        try:
            self._close_and_verify_shutter()
        except BaseException as error:
            # Never command stage motion when upstream shutter closure is not
            # positively verified.
            return error

        try:
            actual = self._stage_position_mm()
            if math.isclose(
                actual,
                out_position,
                abs_tol=self.position_tolerance_mm,
                rel_tol=0.0,
            ):
                self._require_position(out_position, role="out")
                return None
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
        self._require_position(target_mm, role="requested")

    def _require_position(self, target_mm: float, *, role: str) -> None:
        actual = self._stage_position_mm()
        if not math.isclose(
            actual,
            target_mm,
            abs_tol=self.position_tolerance_mm,
            rel_tol=0.0,
        ):
            raise PowerProbeSafetyError(
                "Power-meter stage did not reach its verified "
                f"{role} position: target={target_mm:.6g} mm, "
                f"actual={actual:.6g} mm."
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

    @staticmethod
    def _validate_trace_settings(
        *,
        duration_s: float,
        settle_time_s: float,
        poll_interval_s: float,
    ) -> tuple[float, float, float]:
        duration = float(duration_s)
        settle = float(settle_time_s)
        poll = float(poll_interval_s)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Power measurement duration must be positive.")
        if not math.isfinite(settle) or settle < 0:
            raise ValueError("Power measurement settle time cannot be negative.")
        if not math.isfinite(poll) or poll <= 0:
            raise ValueError("Power measurement poll interval must be positive.")
        return duration, settle, poll

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

    @property
    def is_in(self) -> bool:
        if self.in_position_mm is None:
            return False
        try:
            return math.isclose(
                self._stage_position_mm(),
                self.in_position_mm,
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
            "is_in": self.is_in,
            "is_out": self.is_out,
            "session_active": self._session_active,
            "optical_layout": "shutter_upstream_of_power_meter",
        }
