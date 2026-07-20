"""Experiment-context record for one incident-power acquisition attempt."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class PowerMeasurementAttempt:
    """One attempt shared by an intensity block or one spectrum.

    Failed attempts deliberately have no trace ID and no achieved power. Their
    stable attempt ID still lets reporting count the failure once rather than
    once per associated sample angle.
    """

    attempt_id: str
    attempted_at_unix_s: float
    waveplate_angle_deg: float
    cadence: str
    status: str
    fundamental_wavelength_nm: float
    trace_id: str | None = None
    error: str | None = None
    maximum_allowed_power_mw: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.attempt_id).strip():
            raise ValueError("Power measurement attempt ID cannot be empty.")
        object.__setattr__(self, "attempt_id", str(self.attempt_id).strip())
        for name in (
            "attempted_at_unix_s",
            "waveplate_angle_deg",
            "fundamental_wavelength_nm",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")
            object.__setattr__(self, name, value)
        if self.fundamental_wavelength_nm <= 0:
            raise ValueError("Fundamental wavelength must be positive.")
        if not str(self.cadence).strip() or not str(self.status).strip():
            raise ValueError("Power attempt cadence and status cannot be empty.")
        if self.trace_id is not None:
            trace_id = str(self.trace_id).strip()
            if not trace_id:
                raise ValueError("Power trace ID cannot be blank.")
            object.__setattr__(self, "trace_id", trace_id)
        if self.maximum_allowed_power_mw is not None:
            limit = float(self.maximum_allowed_power_mw)
            if not math.isfinite(limit) or limit <= 0:
                raise ValueError(
                    "Maximum allowed power must be finite and positive."
                )
            object.__setattr__(self, "maximum_allowed_power_mw", limit)
        object.__setattr__(self, "metadata", dict(self.metadata))
