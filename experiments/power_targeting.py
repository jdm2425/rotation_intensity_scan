"""Closed-loop waveplate targeting using measured incident power.

The controller is hardware-independent.  A caller supplies a function which
moves the waveplate, acquires a real power trace, and returns the achieved
mean power in milliwatts.  The controller then searches only inside one
explicitly configured monotonic waveplate branch.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable


class TargetPowerError(RuntimeError):
    """Base error for target-power feedback."""


class TargetPowerBracketError(TargetPowerError):
    """The configured waveplate branch does not bracket the target power."""


class TargetPowerConvergenceError(TargetPowerError):
    """The feedback loop could not reach the requested tolerance."""


@dataclass(frozen=True, slots=True)
class PowerObservation:
    """One measured power at one waveplate angle."""

    waveplate_angle_deg: float
    power_mw: float


@dataclass(frozen=True, slots=True)
class TargetPowerResult:
    """Final verified result from one target-power search."""

    target_power_mw: float
    achieved_power_mw: float
    waveplate_angle_deg: float
    absolute_error_mw: float
    measurement_count: int
    observations: tuple[PowerObservation, ...]


class TargetPowerController:
    """Bounded target-power feedback on a known monotonic waveplate branch.

    Parameters
    ----------
    measure_power_at_angle
        Callback which must move the waveplate, perform a real incident-power
        measurement, and return the achieved arithmetic-mean power in mW.

    waveplate_min_deg, waveplate_max_deg
        Physically reviewed endpoints of one monotonic branch.  The controller
        never commands an angle outside this interval.

    monotonic_direction
        ``"increasing"`` when power rises with angle on the selected branch,
        otherwise ``"decreasing"``.
    """

    def __init__(
        self,
        *,
        measure_power_at_angle: Callable[[float], float],
        waveplate_min_deg: float,
        waveplate_max_deg: float,
        monotonic_direction: str,
        tolerance_mw: float,
        maximum_iterations: int,
        minimum_angle_step_deg: float = 0.01,
    ) -> None:
        self._measure_callback = measure_power_at_angle
        self.waveplate_min_deg = self._finite(waveplate_min_deg, "waveplate_min_deg")
        self.waveplate_max_deg = self._finite(waveplate_max_deg, "waveplate_max_deg")
        if self.waveplate_max_deg <= self.waveplate_min_deg:
            raise ValueError("waveplate_max_deg must exceed waveplate_min_deg.")

        direction = str(monotonic_direction).strip().lower()
        if direction not in {"increasing", "decreasing"}:
            raise ValueError(
                "monotonic_direction must be 'increasing' or 'decreasing'."
            )
        self.monotonic_direction = direction

        self.tolerance_mw = self._finite(tolerance_mw, "tolerance_mw")
        if self.tolerance_mw <= 0:
            raise ValueError("tolerance_mw must be positive.")

        self.maximum_iterations = int(maximum_iterations)
        if self.maximum_iterations < 1:
            raise ValueError("maximum_iterations must be at least one.")

        self.minimum_angle_step_deg = self._finite(
            minimum_angle_step_deg,
            "minimum_angle_step_deg",
        )
        if self.minimum_angle_step_deg <= 0:
            raise ValueError("minimum_angle_step_deg must be positive.")

        self._observations: dict[float, float] = {}
        self._last_measured_angle: float | None = None
        self._measurement_count = 0

    @staticmethod
    def _finite(value: float, name: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
        return value

    @property
    def observations(self) -> tuple[PowerObservation, ...]:
        return tuple(
            PowerObservation(angle, self._observations[angle])
            for angle in sorted(self._observations)
        )

    def set_target(self, target_power_mw: float) -> TargetPowerResult:
        """Measure and reach one requested power within the configured tolerance."""

        target = self._finite(target_power_mw, "target_power_mw")
        if target <= 0:
            raise ValueError("target_power_mw must be positive.")

        # Power can drift between requested target blocks.  Start every target
        # with a fresh bracket rather than trusting observations from an older
        # probe insertion.  All observations below therefore belong to the
        # current persistent measurement session.
        self._observations = {}
        self._last_measured_angle = None
        measurement_count_before = self._measurement_count

        low_angle = self.waveplate_min_deg
        high_angle = self.waveplate_max_deg
        low_power = self._measure(low_angle)
        high_power = self._measure(high_angle)
        self._validate_monotonic_endpoints(low_power, high_power)

        minimum_power = min(low_power, high_power)
        maximum_power = max(low_power, high_power)
        if target < minimum_power - self.tolerance_mw or target > maximum_power + self.tolerance_mw:
            raise TargetPowerBracketError(
                f"Target {target:.6g} mW is not bracketed by the configured "
                f"waveplate branch: {low_angle:.6g} deg -> {low_power:.6g} mW, "
                f"{high_angle:.6g} deg -> {high_power:.6g} mW."
            )

        endpoint = self._endpoint_within_tolerance(
            target,
            low_angle,
            low_power,
            high_angle,
            high_power,
        )
        if endpoint is not None:
            angle, _ = endpoint
            achieved = self._verify_final(angle)
            if abs(achieved - target) <= self.tolerance_mw:
                return self._result(target, angle, achieved, measurement_count_before)
            low_angle, low_power, high_angle, high_power = self._bracket_from_observations(
                target
            )

        for _ in range(self.maximum_iterations):
            candidate = self._interpolated_candidate(
                target,
                low_angle,
                low_power,
                high_angle,
                high_power,
            )
            achieved = self._measure(candidate)
            error = achieved - target
            if abs(error) <= self.tolerance_mw:
                return self._result(
                    target,
                    candidate,
                    achieved,
                    measurement_count_before,
                )

            if self.monotonic_direction == "increasing":
                if achieved < target:
                    low_angle, low_power = candidate, achieved
                else:
                    high_angle, high_power = candidate, achieved
            else:
                if achieved > target:
                    low_angle, low_power = candidate, achieved
                else:
                    high_angle, high_power = candidate, achieved

            if high_angle - low_angle <= self.minimum_angle_step_deg:
                break

        best_angle, best_power = min(
            self._observations.items(),
            key=lambda item: abs(item[1] - target),
        )
        if self._last_measured_angle != best_angle:
            best_power = self._measure(best_angle)
        raise TargetPowerConvergenceError(
            f"Could not reach {target:.6g} +/- {self.tolerance_mw:.6g} mW "
            f"within {self.maximum_iterations} feedback iterations. Best "
            f"verified point was {best_power:.6g} mW at {best_angle:.6g} deg."
        )

    def _power_at(self, angle: float) -> float:
        angle = float(angle)
        if angle in self._observations:
            return self._observations[angle]
        return self._measure(angle)

    def _measure(self, angle: float) -> float:
        angle = self._finite(angle, "waveplate angle")
        if angle < self.waveplate_min_deg or angle > self.waveplate_max_deg:
            raise TargetPowerError(
                f"Refusing waveplate angle {angle:.6g} deg outside configured "
                f"branch [{self.waveplate_min_deg:.6g}, "
                f"{self.waveplate_max_deg:.6g}] deg."
            )
        power = self._finite(self._measure_callback(angle), "measured power")
        if power <= 0:
            raise TargetPowerError(
                f"Measured power at {angle:.6g} deg was not positive: "
                f"{power:.6g} mW."
            )
        self._observations[angle] = power
        self._last_measured_angle = angle
        self._measurement_count += 1
        return power

    def _verify_final(self, angle: float) -> float:
        if self._last_measured_angle == angle:
            return self._observations[angle]
        return self._measure(angle)

    def _validate_monotonic_endpoints(self, low_power: float, high_power: float) -> None:
        if self.monotonic_direction == "increasing" and high_power <= low_power:
            raise TargetPowerBracketError(
                "Configured branch was declared increasing, but measured endpoint "
                f"power did not increase ({low_power:.6g} -> {high_power:.6g} mW)."
            )
        if self.monotonic_direction == "decreasing" and high_power >= low_power:
            raise TargetPowerBracketError(
                "Configured branch was declared decreasing, but measured endpoint "
                f"power did not decrease ({low_power:.6g} -> {high_power:.6g} mW)."
            )

    def _endpoint_within_tolerance(
        self,
        target: float,
        low_angle: float,
        low_power: float,
        high_angle: float,
        high_power: float,
    ) -> tuple[float, float] | None:
        candidates = ((low_angle, low_power), (high_angle, high_power))
        angle, power = min(candidates, key=lambda item: abs(item[1] - target))
        if abs(power - target) <= self.tolerance_mw:
            return angle, power
        return None

    def _bracket_from_observations(
        self,
        target: float,
    ) -> tuple[float, float, float, float]:
        points = sorted(self._observations.items())
        for (angle_a, power_a), (angle_b, power_b) in zip(points, points[1:]):
            if min(power_a, power_b) <= target <= max(power_a, power_b):
                return angle_a, power_a, angle_b, power_b
        raise TargetPowerBracketError(
            f"Fresh endpoint verification no longer brackets {target:.6g} mW."
        )

    def _interpolated_candidate(
        self,
        target: float,
        low_angle: float,
        low_power: float,
        high_angle: float,
        high_power: float,
    ) -> float:
        width = high_angle - low_angle
        midpoint = (low_angle + high_angle) / 2.0
        if width <= 2.0 * self.minimum_angle_step_deg:
            return midpoint

        delta_power = high_power - low_power
        if not math.isfinite(delta_power) or abs(delta_power) < 1e-15:
            candidate = midpoint
        else:
            candidate = low_angle + (target - low_power) * width / delta_power

        margin = min(self.minimum_angle_step_deg, width / 4.0)
        candidate = max(low_angle + margin, min(high_angle - margin, candidate))

        if any(
            math.isclose(candidate, angle, rel_tol=0.0, abs_tol=1e-12)
            for angle in self._observations
        ):
            candidate = midpoint
        return float(candidate)

    def _result(
        self,
        target: float,
        angle: float,
        achieved: float,
        measurement_count_before: int,
    ) -> TargetPowerResult:
        return TargetPowerResult(
            target_power_mw=target,
            achieved_power_mw=achieved,
            waveplate_angle_deg=angle,
            absolute_error_mw=abs(achieved - target),
            measurement_count=max(0, self._measurement_count - measurement_count_before),
            observations=self.observations,
        )
