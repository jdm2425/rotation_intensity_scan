"""Persistent Malus-law calibration for bounded waveplate-power targeting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class MalusLawCalibration:
    """Linearised half-wave-plate Malus model in measured power units."""

    constant_mw: float
    cosine_mw: float
    sine_mw: float
    waveplate_min_deg: float
    waveplate_max_deg: float
    monotonic_direction: str
    rms_residual_mw: float
    point_count: int
    power_offset_mw: float = 0.0
    created: str = ""
    source: str = ""

    def predict_power_mw(self, angle_deg: float) -> float:
        phase = math.radians(4.0 * float(angle_deg))
        return (
            self.constant_mw
            + self.cosine_mw * math.cos(phase)
            + self.sine_mw * math.sin(phase)
            + self.power_offset_mw
        )

    def with_reference(self, *, angle_deg: float, measured_power_mw: float):
        unshifted = replace(self, power_offset_mw=0.0).predict_power_mw(angle_deg)
        return replace(
            self,
            power_offset_mw=float(measured_power_mw) - unshifted,
        )

    def angle_for_power_mw(self, target_power_mw: float) -> float:
        angles = np.linspace(
            self.waveplate_min_deg,
            self.waveplate_max_deg,
            20001,
            dtype=float,
        )
        phase = np.deg2rad(4.0 * angles)
        powers = (
            self.constant_mw
            + self.cosine_mw * np.cos(phase)
            + self.sine_mw * np.sin(phase)
            + self.power_offset_mw
        )
        index = int(np.argmin(np.abs(powers - float(target_power_mw))))
        return float(angles[index])

    def save(self, path: Path) -> None:
        with Path(path).open("w", encoding="utf-8") as file:
            json.dump(asdict(self), file, indent=2)

    @classmethod
    def load(cls, path: Path):
        with Path(path).open("r", encoding="utf-8") as file:
            return cls(**json.load(file))


def fit_malus_calibration(
    angles_deg: Sequence[float],
    powers_mw: Sequence[float],
    *,
    waveplate_min_deg: float,
    waveplate_max_deg: float,
    monotonic_direction: str,
    source: str = "",
) -> MalusLawCalibration:
    angles = np.asarray(angles_deg, dtype=float)
    powers = np.asarray(powers_mw, dtype=float)
    if angles.ndim != 1 or powers.ndim != 1 or angles.shape != powers.shape:
        raise ValueError("Calibration angles and powers must be matching 1D arrays.")
    mask = (
        np.isfinite(angles)
        & np.isfinite(powers)
        & (angles >= float(waveplate_min_deg))
        & (angles <= float(waveplate_max_deg))
    )
    angles = angles[mask]
    powers = powers[mask]
    if angles.size < 3:
        raise ValueError("At least three finite calibration points are required.")
    phase = np.deg2rad(4.0 * angles)
    design = np.column_stack((np.ones_like(angles), np.cos(phase), np.sin(phase)))
    coefficients, _, rank, _ = np.linalg.lstsq(design, powers, rcond=None)
    if rank < 3:
        raise ValueError("Calibration angles do not constrain a Malus-law fit.")
    fitted = design @ coefficients
    return MalusLawCalibration(
        constant_mw=float(coefficients[0]),
        cosine_mw=float(coefficients[1]),
        sine_mw=float(coefficients[2]),
        waveplate_min_deg=float(waveplate_min_deg),
        waveplate_max_deg=float(waveplate_max_deg),
        monotonic_direction=str(monotonic_direction),
        rms_residual_mw=float(np.sqrt(np.mean((powers - fitted) ** 2))),
        point_count=int(angles.size),
        created=datetime.now().isoformat(),
        source=source,
    )
