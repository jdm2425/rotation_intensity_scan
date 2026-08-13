from __future__ import annotations

from pathlib import Path
import tempfile

from tools.waveplate_power_control import (
    WaveplatePowerPoint,
    identify_monotonic_branch,
    parse_arguments,
    plot_waveplate_power_map,
    scan_angles,
)


def test_scan_angles_includes_stop() -> None:
    assert scan_angles(0.0, 1.0, 0.4) == (0.0, 0.4, 0.8, 1.0)


def test_identifies_largest_monotonic_branch() -> None:
    points = (
        WaveplatePowerPoint(0.0, 5.0),
        WaveplatePowerPoint(1.0, 4.0),
        WaveplatePowerPoint(2.0, 3.0),
        WaveplatePowerPoint(3.0, 3.02),
        WaveplatePowerPoint(4.0, 2.0),
        WaveplatePowerPoint(5.0, 2.5),
    )
    branch = identify_monotonic_branch(points, noise_tolerance_mw=0.05)
    assert branch.start_deg == 0.0
    assert branch.stop_deg == 4.0
    assert branch.direction == "decreasing"
    assert branch.point_count == 5


def test_set_range_maps_range_to_midpoint_tolerance_inputs() -> None:
    arguments = parse_arguments(
        [
            "set-range",
            "--minimum-power-mw",
            "4",
            "--maximum-power-mw",
            "5",
            "--waveplate-min-deg",
            "60",
            "--waveplate-max-deg",
            "80",
            "--direction",
            "increasing",
        ]
    )
    assert arguments.minimum_power_mw == 4.0
    assert arguments.maximum_power_mw == 5.0
    assert arguments.initial_settle_s == 5.0
    assert arguments.range_option == "AUTO"


def test_multiple_extrema_selects_and_plots_largest_branch() -> None:
    points = (
        WaveplatePowerPoint(0.0, 1.0),
        WaveplatePowerPoint(1.0, 3.0),
        WaveplatePowerPoint(2.0, 2.0),
        WaveplatePowerPoint(3.0, 7.0),
        WaveplatePowerPoint(4.0, 6.0),
        WaveplatePowerPoint(5.0, 5.0),
    )
    branch = identify_monotonic_branch(points, noise_tolerance_mw=0.0)
    assert branch.start_deg == 2.0
    assert branch.stop_deg == 3.0
    assert branch.direction == "increasing"

    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "map.png"
        plot_waveplate_power_map(
            points,
            branch=branch,
            output_path=output_path,
        )
        assert output_path.is_file()
        assert output_path.stat().st_size > 0


if __name__ == "__main__":
    test_scan_angles_includes_stop()
    test_identifies_largest_monotonic_branch()
    test_set_range_maps_range_to_midpoint_tolerance_inputs()
    test_multiple_extrema_selects_and_plots_largest_branch()
    print("Waveplate power-control tests passed.")
