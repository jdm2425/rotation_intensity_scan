"""
rotation_intensity_scan.py

Core rotation + intensity experiment.

This class defines what a single measurement is.

It does not connect hardware, save data or perform analysis.
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from analysis.measurement import Measurement
from data.power_measurement import PowerMeasurementAttempt

logger = logging.getLogger(__name__)


class IncidentPowerLimitError(RuntimeError):
    """Measured incident power exceeded the configured sample-safe limit."""


class RotationIntensityExperiment:
    """
    Rotation + intensity experiment.

    Hardware and acquisition are supplied by the
    ExperimentController immediately before the scan begins.
    """

    def __init__(self):

        self.hardware = None
        self.acquisition = None
        self.averages = 1
        self.power_meter_config = None
        self.power_attempt_callback = None
        self._current_waveplate_angle: float | None = None
        self._power_state: dict = {}

    # ------------------------------------------------------------------

    def scan_started(self) -> None:
        """Reset run-local power state without operating any hardware."""

        self._current_waveplate_angle = None
        self._power_state = {}

    def prepare_intensity(self, *, waveplate_angle: float) -> None:
        """Set one intensity and perform its configured incident-power read."""

        if self.hardware is None:
            raise RuntimeError("Hardware has not been attached.")

        waveplate_angle = float(waveplate_angle)
        logger.info("Setting waveplate to %.3f deg.", waveplate_angle)
        self.hardware.waveplate.move_to(waveplate_angle)
        self._current_waveplate_angle = waveplate_angle

        config = self.power_meter_config
        if config is None or not config.enabled or config.cadence == "disabled":
            self._power_state = {}
            return

        if config.cadence == "per_intensity":
            self._take_power_measurement()
        elif config.cadence == "per_measurement":
            # The individual measurement performs its read after the
            # waveplate has been prepared.
            self._power_state = {}
        else:  # Defensive guard for a dynamically supplied config object.
            raise ValueError(
                f"Unsupported power-measurement cadence: {config.cadence!r}"
            )

    # ------------------------------------------------------------------

    def measure(
        self,
        *,
        waveplate_angle: float,
        sample_angle: float,
    ) -> Measurement:
        """
        Perform one complete measurement.
        """

        if self.hardware is None:
            raise RuntimeError(
                "Hardware has not been attached."
            )

        if self.acquisition is None:
            raise RuntimeError(
                "Acquisition has not been attached."
            )

        logger.info(
            "Measurement: waveplate %.3f°, sample %.3f°",
            waveplate_angle,
            sample_angle,
        )

        if (
            self._current_waveplate_angle is None
            or self._current_waveplate_angle != float(waveplate_angle)
        ):
            self.prepare_intensity(waveplate_angle=waveplate_angle)

        config = self.power_meter_config
        if (
            config is not None
            and config.enabled
            and config.cadence == "per_measurement"
        ):
            self._take_power_measurement()

        self.hardware.sample.move_to(
            sample_angle
        )

        #
        # Acquire spectrum.
        #

        spectrum = self.acquisition.acquire(
            averages=self.averages,
        )

        #
        # Build measurement.
        #

        measurement_metadata = {}
        if self._power_state:
            measurement_metadata["incident_power"] = {
                "status": self._power_state.get("status"),
                "attempt_id": self._power_state.get("attempt_id"),
                "trace_id": self._power_state.get("trace_id"),
                "error": self._power_state.get("error"),
                "cadence": getattr(config, "cadence", None),
                "fundamental_wavelength_nm": getattr(
                    config,
                    "wavelength_nm",
                    None,
                ),
            }

        measurement = Measurement(
            timestamp=time.time(),
            waveplate_angle_deg=waveplate_angle,
            sample_angle_deg=sample_angle,
            power_mw=self._power_state.get("power_mw"),
            power_rms_mw=self._power_state.get("power_rms_mw"),
            power_std_mw=self._power_state.get("power_std_mw"),
            power_measurement_duration_s=self._power_state.get(
                "duration_s"
            ),
            power_measurement_id=self._power_state.get("attempt_id"),
            power_trace_id=self._power_state.get("trace_id"),
            power_measurement_status=self._power_state.get("status"),
            power_measurement_error=self._power_state.get("error"),
            power_valid_sample_count=self._power_state.get(
                "valid_sample_count"
            ),
            power_total_sample_count=self._power_state.get(
                "total_sample_count"
            ),
            power_trace=self._power_state.get("trace"),
            spectrum=spectrum,
            metadata=measurement_metadata,
        )

        #
        # Compute simple statistics immediately.
        #

        measurement.compute_statistics()

        return measurement

    def _take_power_measurement(self) -> None:
        """Acquire a real trace or record an explicit missing-power state."""

        from hardware.power_probe import PowerProbeMeasurementError

        config = self.power_meter_config
        if config is None or not config.enabled:
            self._power_state = {}
            return
        power_probe = getattr(self.hardware, "power_probe", None)
        if power_probe is None:
            raise RuntimeError(
                "Power measurement is enabled but HardwareManager did not "
                "provide a retractable power probe."
            )

        logger.info(
            "Acquiring %.3f s incident-power trace at %.3f nm.",
            config.measurement_duration_s,
            config.wavelength_nm,
        )
        attempt_id = str(uuid4())
        attempted_at = time.time()
        try:
            trace = power_probe.acquire_trace(
                duration_s=config.measurement_duration_s,
                settle_time_s=config.pre_measurement_settle_s,
            )
        except PowerProbeMeasurementError as error:
            logger.error("%s", error)
            self._power_state = {
                "status": "failed",
                "attempt_id": attempt_id,
                "error": str(error),
                "trace": None,
                "trace_id": None,
                "power_mw": None,
                "power_std_mw": None,
                "power_rms_mw": None,
                "duration_s": None,
                "valid_sample_count": None,
                "total_sample_count": None,
            }
            self._publish_power_attempt(attempted_at)
            if not config.continue_without_power_on_meter_error:
                raise
            return

        if trace is None:
            # A conforming driver returns PowerTrace. Preserve an explicit
            # failure if a third-party/future driver instead returns None.
            no_trace_error = PowerProbeMeasurementError(
                "Power-meter driver returned no trace; no power value was "
                "predicted or substituted."
            )
            self._power_state = {
                "status": "failed",
                "attempt_id": attempt_id,
                "error": (
                    "Power-meter driver returned no trace; no power value "
                    "was predicted or substituted."
                ),
                "trace": None,
                "trace_id": None,
                "power_mw": None,
                "power_std_mw": None,
                "power_rms_mw": None,
                "duration_s": None,
                "valid_sample_count": None,
                "total_sample_count": None,
            }
            self._publish_power_attempt(attempted_at)
            if not config.continue_without_power_on_meter_error:
                raise no_trace_error
            return

        statistics = trace.statistics
        if not statistics.valid_sample_count:
            status = "invalid"
        elif statistics.invalid_sample_count:
            status = "measured_with_invalid_samples"
        else:
            status = "measured"
        error = None
        reasons = ", ".join(
            f"{name}={count}"
            for name, count in statistics.invalid_reason_counts
        ) or "no samples returned"
        if status == "invalid":
            error = (
                "Power trace contained no valid positive samples "
                f"({reasons}); raw values were retained and no power was "
                "predicted or substituted."
            )
            logger.warning("%s", error)
        elif status == "measured_with_invalid_samples":
            error = (
                "Power trace contained invalid samples "
                f"({reasons}). They were retained in the raw trace and "
                "excluded from mean, standard deviation, and RMS."
            )
            logger.warning("%s", error)

        self._power_state = {
            "status": status,
            "attempt_id": attempt_id,
            "error": error,
            "trace": trace,
            "trace_id": trace.trace_id,
            "power_mw": statistics.arithmetic_mean_power_mw,
            "power_std_mw": statistics.population_standard_deviation_mw,
            "power_rms_mw": statistics.absolute_root_mean_square_power_mw,
            "duration_s": trace.elapsed_duration_s,
            "valid_sample_count": statistics.valid_sample_count,
            "total_sample_count": statistics.total_sample_count,
        }
        unsafe_reasons = sorted(
            {
                reason
                for sample in trace.invalid_samples
                for reason in sample.invalid_reasons
                if reason.startswith("status_")
                or reason in {"value_not_finite"}
            }
        )
        finite_positive_raw_mw = [
            sample.power_mw
            for sample in trace.samples
            if sample.power_mw is not None
            and sample.power_mw > 0
            and sample.power_mw != float("inf")
        ]
        raw_maximum = (
            max(finite_positive_raw_mw) if finite_positive_raw_mw else None
        )
        limit = config.maximum_allowed_power_mw
        maximum = raw_maximum
        if unsafe_reasons:
            self._power_state["status"] = "unsafe_meter_status"
            self._power_state["error"] = (
                "Power trace contained a status/non-finite flag that makes "
                "safe exposure uncertain ("
                + ", ".join(unsafe_reasons)
                + "). The shutter remains closed and no spectrum will be "
                "acquired."
            )
        if limit is not None and maximum is not None and maximum > limit:
            self._power_state["status"] = "over_limit"
            self._power_state["error"] = (
                f"Measured incident power reached {maximum:.6g} mW, above "
                f"the configured {limit:.6g} mW maximum. The shutter remains "
                "closed and no spectrum will be acquired."
            )

        self._publish_power_attempt(attempted_at)

        if self._power_state["status"] == "unsafe_meter_status":
            raise PowerProbeMeasurementError(self._power_state["error"])
        if self._power_state["status"] == "invalid" and not (
            config.continue_without_power_on_meter_error
        ):
            raise PowerProbeMeasurementError(self._power_state["error"])
        if self._power_state["status"] == "over_limit":
            raise IncidentPowerLimitError(self._power_state["error"])

    def _publish_power_attempt(self, attempted_at: float) -> None:
        """Persist an attempt immediately, before any spectrum acquisition."""

        callback = self.power_attempt_callback
        if callback is None:
            return
        config = self.power_meter_config
        attempt = PowerMeasurementAttempt(
            attempt_id=self._power_state["attempt_id"],
            attempted_at_unix_s=attempted_at,
            waveplate_angle_deg=float(self._current_waveplate_angle),
            cadence=config.cadence,
            status=self._power_state["status"],
            fundamental_wavelength_nm=config.wavelength_nm,
            trace_id=self._power_state.get("trace_id"),
            error=self._power_state.get("error"),
            maximum_allowed_power_mw=config.maximum_allowed_power_mw,
            metadata={
                "configured_wavelength_option": config.wavelength_option,
                "configured_range_option": config.range_option,
            },
        )
        callback(attempt, self._power_state.get("trace"))

    # ------------------------------------------------------------------

    def home(self):
        """
        Home both stages.
        """

        if self.hardware is None:
            raise RuntimeError(
                "Hardware has not been attached."
            )

        logger.info(
            "Homing rotation stages..."
        )

        self.hardware.waveplate.home()

        self.hardware.sample.home()
