from __future__ import annotations

import math
import tempfile
from pathlib import Path

from experiments.waveplate_calibration import (
    MalusLawCalibration,
    fit_malus_calibration,
)


def test_fit_inverse_offset_and_round_trip() -> None:
    angles = list(range(70, 111, 2))
    powers = [
        11.0 - 9.0 * math.cos(math.radians(4.0 * (angle - 75.0)))
        for angle in angles
    ]
    calibration = fit_malus_calibration(
        angles,
        powers,
        waveplate_min_deg=75.0,
        waveplate_max_deg=110.0,
        monotonic_direction="increasing",
        source="synthetic.csv",
    )
    assert calibration.rms_residual_mw < 1e-10
    target_angle = 92.0
    target_power = calibration.predict_power_mw(target_angle)
    assert abs(calibration.angle_for_power_mw(target_power) - target_angle) < 0.01

    shifted = calibration.with_reference(
        angle_deg=110.0,
        measured_power_mw=calibration.predict_power_mw(110.0) + 2.5,
    )
    assert abs(shifted.power_offset_mw - 2.5) < 1e-10

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "calibration.json"
        shifted.save(path)
        assert MalusLawCalibration.load(path) == shifted


if __name__ == "__main__":
    test_fit_inverse_offset_and_round_trip()
    print("WAVEPLATE CALIBRATION TEST PASSED")
