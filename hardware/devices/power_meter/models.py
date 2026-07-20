"""Immutable, vendor-independent power-sampling data models.

Raw meter outputs are retained on every :class:`PowerSample`.  Parsed values
are additional fields; invalid values are never replaced, interpolated, or
predicted.  Statistics use only samples explicitly marked as valid.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Iterable
from uuid import uuid4


def _to_milliwatts(value_w: float | None) -> float | None:
    if value_w is None:
        return None
    return value_w * 1000.0


@dataclass(frozen=True, slots=True)
class PowerSample:
    """One unmodified meter result plus its conservative interpretation.

    ``raw_value``, ``raw_timestamp``, and ``raw_status`` are the three values
    returned by the hardware API.  ``power_w`` and ``timestamp_s`` are parsed
    numeric views which may be ``None``.  Invalid raw readings remain in the
    trace and are excluded from descriptive statistics.
    """

    batch_index: int
    index_in_batch: int
    raw_value: object
    raw_timestamp: object
    raw_status: object
    power_w: float | None
    timestamp_s: float | None
    valid_for_statistics: bool
    invalid_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.batch_index < 0:
            raise ValueError("batch_index must be non-negative.")
        if self.index_in_batch < 0:
            raise ValueError("index_in_batch must be non-negative.")

        object.__setattr__(self, "invalid_reasons", tuple(self.invalid_reasons))

        if self.valid_for_statistics:
            if self.invalid_reasons:
                raise ValueError(
                    "A valid power sample cannot have invalid_reasons."
                )
            if (
                self.power_w is None
                or not math.isfinite(self.power_w)
                or self.power_w <= 0.0
            ):
                raise ValueError(
                    "A valid power sample requires finite positive power_w."
                )
            if self.timestamp_s is None or not math.isfinite(self.timestamp_s):
                raise ValueError(
                    "A valid power sample requires a finite timestamp_s."
                )
        elif not self.invalid_reasons:
            raise ValueError(
                "An invalid power sample must explain why it is invalid."
            )

    @property
    def power_mw(self) -> float | None:
        """Parsed power in milliwatts, including non-positive raw readings."""

        return _to_milliwatts(self.power_w)


@dataclass(frozen=True, slots=True)
class PowerStatistics:
    """Descriptive statistics for valid samples in one trace.

    The three central quantities have deliberately explicit names:

    * ``arithmetic_mean_power_w`` is the ordinary arithmetic mean.
    * ``population_standard_deviation_w`` measures spread about that mean
      with a population denominator of ``N``.
    * ``absolute_root_mean_square_power_w`` is ``sqrt(mean(power ** 2))``.

    They are not aliases for one another.  If there are no valid samples, all
    numerical results are ``None`` rather than guessed values.
    """

    measurement_duration_s: float
    total_sample_count: int
    valid_sample_count: int
    invalid_sample_count: int
    arithmetic_mean_power_w: float | None
    population_standard_deviation_w: float | None
    absolute_root_mean_square_power_w: float | None
    minimum_power_w: float | None
    maximum_power_w: float | None
    invalid_reason_counts: tuple[tuple[str, int], ...]

    @classmethod
    def from_samples(
        cls,
        samples: Iterable[PowerSample],
        *,
        measurement_duration_s: float,
    ) -> PowerStatistics:
        """Calculate statistics without discarding invalid sample records."""

        sample_tuple = tuple(samples)
        duration = float(measurement_duration_s)
        if not math.isfinite(duration) or duration < 0.0:
            raise ValueError(
                "measurement_duration_s must be finite and non-negative."
            )

        valid_values = tuple(
            sample.power_w
            for sample in sample_tuple
            if sample.valid_for_statistics and sample.power_w is not None
        )
        reasons = Counter(
            reason
            for sample in sample_tuple
            if not sample.valid_for_statistics
            for reason in sample.invalid_reasons
        )

        if valid_values:
            count = len(valid_values)
            mean = math.fsum(valid_values) / count
            variance = (
                math.fsum((value - mean) ** 2 for value in valid_values)
                / count
            )
            square_mean = math.fsum(
                value * value for value in valid_values
            ) / count
            population_std = math.sqrt(variance)
            absolute_rms = math.sqrt(square_mean)
            minimum = min(valid_values)
            maximum = max(valid_values)
        else:
            mean = None
            population_std = None
            absolute_rms = None
            minimum = None
            maximum = None

        valid_count = len(valid_values)
        return cls(
            measurement_duration_s=duration,
            total_sample_count=len(sample_tuple),
            valid_sample_count=valid_count,
            invalid_sample_count=len(sample_tuple) - valid_count,
            arithmetic_mean_power_w=mean,
            population_standard_deviation_w=population_std,
            absolute_root_mean_square_power_w=absolute_rms,
            minimum_power_w=minimum,
            maximum_power_w=maximum,
            invalid_reason_counts=tuple(sorted(reasons.items())),
        )

    @property
    def arithmetic_mean_power_mw(self) -> float | None:
        return _to_milliwatts(self.arithmetic_mean_power_w)

    @property
    def population_standard_deviation_mw(self) -> float | None:
        return _to_milliwatts(self.population_standard_deviation_w)

    @property
    def absolute_root_mean_square_power_mw(self) -> float | None:
        return _to_milliwatts(self.absolute_root_mean_square_power_w)

    @property
    def minimum_power_mw(self) -> float | None:
        return _to_milliwatts(self.minimum_power_w)

    @property
    def maximum_power_mw(self) -> float | None:
        return _to_milliwatts(self.maximum_power_w)


@dataclass(frozen=True, slots=True)
class PowerTrace:
    """A complete, immutable streamed power measurement."""

    samples: tuple[PowerSample, ...]
    batch_sizes: tuple[int, ...]
    requested_duration_s: float
    elapsed_duration_s: float
    started_at_unix_s: float
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    source_unit: str = "W"
    device_serial: str | None = None
    sensor_serial: str | None = None
    measurement_mode: str | None = None
    wavelength_option: str | None = None
    range_option: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))
        object.__setattr__(self, "batch_sizes", tuple(self.batch_sizes))

        if not str(self.trace_id).strip():
            raise ValueError("trace_id cannot be empty.")
        object.__setattr__(self, "trace_id", str(self.trace_id).strip())

        for field_name in ("requested_duration_s", "elapsed_duration_s"):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"{field_name} must be finite and non-negative."
                )
            object.__setattr__(self, field_name, value)

        if any(size < 0 for size in self.batch_sizes):
            raise ValueError("batch_sizes cannot contain negative values.")
        if sum(self.batch_sizes) != len(self.samples):
            raise ValueError(
                "batch_sizes must account for every sample in the trace."
            )
        if self.source_unit != "W":
            raise ValueError(
                "PowerTrace source_unit must be 'W'; unit conversion belongs "
                "in explicit convenience properties."
            )

    @property
    def valid_samples(self) -> tuple[PowerSample, ...]:
        return tuple(
            sample for sample in self.samples if sample.valid_for_statistics
        )

    @property
    def invalid_samples(self) -> tuple[PowerSample, ...]:
        return tuple(
            sample for sample in self.samples if not sample.valid_for_statistics
        )

    @property
    def raw_values(self) -> tuple[object, ...]:
        return tuple(sample.raw_value for sample in self.samples)

    @property
    def raw_timestamps(self) -> tuple[object, ...]:
        return tuple(sample.raw_timestamp for sample in self.samples)

    @property
    def raw_statuses(self) -> tuple[object, ...]:
        return tuple(sample.raw_status for sample in self.samples)

    @property
    def statistics(self) -> PowerStatistics:
        return PowerStatistics.from_samples(
            self.samples,
            measurement_duration_s=self.elapsed_duration_s,
        )
