"""Set incident power or map a monotonic waveplate control branch.

This operator tool connects only the waveplate stage, shutter, PI insertion
stage, and Ophir meter. It never homes a stage and never searches for a
mechanical end stop. The scan bounds are operator-supplied reviewed angles.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from experiments.power_targeting import TargetPowerController
from experiments.waveplate_calibration import (
    MalusLawCalibration,
    fit_malus_calibration,
)


@dataclass(frozen=True, slots=True)
class WaveplatePowerPoint:
    angle_deg: float
    power_mw: float


@dataclass(frozen=True, slots=True)
class MonotonicBranch:
    start_deg: float
    stop_deg: float
    direction: str
    start_power_mw: float
    stop_power_mw: float
    point_count: int

    @property
    def power_span_mw(self) -> float:
        return abs(self.stop_power_mw - self.start_power_mw)


def identify_monotonic_branch(
    points: Sequence[WaveplatePowerPoint],
    *,
    noise_tolerance_mw: float,
) -> MonotonicBranch:
    """Return the contiguous monotonic run with the largest measured span."""

    tolerance = float(noise_tolerance_mw)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("noise_tolerance_mw must be finite and non-negative.")
    if len(points) < 2:
        raise ValueError("At least two waveplate-power points are required.")

    ordered = tuple(points)
    if any(
        not math.isfinite(point.angle_deg) or not math.isfinite(point.power_mw)
        for point in ordered
    ):
        raise ValueError("Waveplate angles and powers must be finite.")
    if any(right.angle_deg <= left.angle_deg for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Waveplate-power points must have strictly increasing angles.")

    candidates: list[MonotonicBranch] = []
    for direction, sign in (("increasing", 1.0), ("decreasing", -1.0)):
        run_start = 0
        for index, (left, right) in enumerate(zip(ordered, ordered[1:]), start=1):
            signed_change = sign * (right.power_mw - left.power_mw)
            if signed_change < -tolerance:
                if index - run_start >= 2:
                    candidates.append(
                        _branch(ordered, run_start, index - 1, direction)
                    )
                run_start = index
        if len(ordered) - run_start >= 2:
            candidates.append(
                _branch(ordered, run_start, len(ordered) - 1, direction)
            )

    useful = [branch for branch in candidates if branch.power_span_mw > tolerance]
    if not useful:
        raise ValueError(
            "No monotonic branch exceeds the configured power-noise tolerance."
        )
    return max(
        useful,
        key=lambda branch: (branch.power_span_mw, branch.point_count),
    )


def _branch(
    points: Sequence[WaveplatePowerPoint],
    start: int,
    stop: int,
    direction: str,
) -> MonotonicBranch:
    return MonotonicBranch(
        start_deg=points[start].angle_deg,
        stop_deg=points[stop].angle_deg,
        direction=direction,
        start_power_mw=points[start].power_mw,
        stop_power_mw=points[stop].power_mw,
        point_count=stop - start + 1,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Skip typed RUN confirmation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser(
        "set-range", help="Move the waveplate until power lies in a requested range."
    )
    set_parser.add_argument("--minimum-power-mw", type=float, required=True)
    set_parser.add_argument("--maximum-power-mw", type=float, required=True)
    set_parser.add_argument("--waveplate-min-deg", type=float, required=True)
    set_parser.add_argument("--waveplate-max-deg", type=float, required=True)
    set_parser.add_argument(
        "--direction", choices=("increasing", "decreasing"), required=True
    )
    set_parser.add_argument("--maximum-iterations", type=int, default=8)
    set_parser.add_argument("--minimum-angle-step-deg", type=float, default=0.02)
    set_parser.add_argument(
        "--calibration",
        type=Path,
        default=None,
        help="Optional saved Malus-law calibration used for the initial guess.",
    )
    _add_acquisition_options(set_parser)

    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan reviewed angles, record power, and recommend a monotonic branch.",
    )
    scan_parser.add_argument("--scan-start-deg", type=float, required=True)
    scan_parser.add_argument("--scan-stop-deg", type=float, required=True)
    scan_parser.add_argument("--step-deg", type=float, required=True)
    scan_parser.add_argument("--noise-tolerance-mw", type=float, default=0.1)
    _add_acquisition_options(scan_parser)
    return parser


def _add_acquisition_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wavelength-option", default=">800")
    parser.add_argument("--range-option", default="AUTO")
    parser.add_argument("--duration-s", type=float, default=3.0)
    parser.add_argument("--settle-s", type=float, default=3.0)
    parser.add_argument("--initial-settle-s", type=float, default=5.0)
    parser.add_argument("--poll-interval-s", type=float, default=0.1)
    parser.add_argument(
        "--raw-power-ceiling-mw",
        type=float,
        default=50.0,
        help="Abort if any positive raw sample exceeds this ceiling (default: 50).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("results") / "waveplate_power_control",
    )


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    arguments = build_parser().parse_args(argv)
    _validate_arguments(arguments)
    return arguments


def _validate_arguments(arguments: argparse.Namespace) -> None:
    positive = ("duration_s", "poll_interval_s", "raw_power_ceiling_mw")
    non_negative = ("settle_s", "initial_settle_s")
    for name in positive:
        value = float(getattr(arguments, name))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive.")
    for name in non_negative:
        value = float(getattr(arguments, name))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"--{name.replace('_', '-')} must be non-negative.")

    if arguments.command == "set-range":
        if not 0 < arguments.minimum_power_mw < arguments.maximum_power_mw:
            raise ValueError("Power range must satisfy 0 < minimum < maximum.")
        if arguments.waveplate_max_deg <= arguments.waveplate_min_deg:
            raise ValueError("Waveplate maximum must exceed its minimum.")
        if arguments.maximum_iterations < 1:
            raise ValueError("--maximum-iterations must be at least one.")
        if arguments.minimum_angle_step_deg <= 0:
            raise ValueError("--minimum-angle-step-deg must be positive.")
    else:
        if arguments.scan_stop_deg <= arguments.scan_start_deg:
            raise ValueError("Scan stop must exceed scan start.")
        if not math.isfinite(arguments.step_deg) or arguments.step_deg <= 0:
            raise ValueError("--step-deg must be positive.")
        if (
            not math.isfinite(arguments.noise_tolerance_mw)
            or arguments.noise_tolerance_mw < 0
        ):
            raise ValueError("--noise-tolerance-mw must be non-negative.")


def scan_angles(start: float, stop: float, step: float) -> tuple[float, ...]:
    count = int(math.floor((stop - start) / step))
    values = [start + index * step for index in range(count + 1)]
    if not math.isclose(values[-1], stop, abs_tol=1e-9):
        values.append(stop)
    return tuple(float(value) for value in values)


class HardwareMeasurement:
    def __init__(self, arguments: argparse.Namespace, run_directory: Path) -> None:
        self.arguments = arguments
        self.run_directory = run_directory
        self.trace_index = 0
        self.hardware = None
        self.session = None

    def measure(self, angle_deg: float) -> float:
        assert self.hardware is not None and self.session is not None
        self.session.prepare_for_motion()
        self.hardware.waveplate.move_to(float(angle_deg))
        self.trace_index += 1
        trace = self.session.acquire_trace(
            duration_s=self.arguments.duration_s,
            settle_time_s=(
                self.arguments.initial_settle_s
                if self.trace_index == 1
                else self.arguments.settle_s
            ),
            poll_interval_s=self.arguments.poll_interval_s,
        )
        maximum = max(
            (
                sample.power_mw
                for sample in trace.samples
                if sample.power_mw is not None
                and math.isfinite(sample.power_mw)
                and sample.power_mw > 0
            ),
            default=None,
        )
        if maximum is not None and maximum > self.arguments.raw_power_ceiling_mw:
            raise RuntimeError(
                f"Raw power {maximum:.6g} mW exceeds the configured "
                f"{self.arguments.raw_power_ceiling_mw:.6g} mW ceiling."
            )
        statistics = trace.statistics
        power = statistics.arithmetic_mean_power_mw
        if power is None:
            raise RuntimeError(f"No valid positive power at {angle_deg:.6g} deg.")
        from tools.test_power_probe_hardware import save_trace

        save_trace(
            run_directory=self.run_directory,
            trace=trace,
            trace_index=self.trace_index,
            stage_position_mm=self.hardware.power_meter_stage.position_mm,
        )
        print(f"{angle_deg:.6g} deg -> {power:.6g} mW")
        return float(power)


@contextmanager
def _hardware_context(arguments: argparse.Namespace):
    """Connect only the four devices used by this tool."""

    from hardware.config import POWER_METER_STAGE, WAVEPLATE
    from hardware.devices.rotation import RotationStage
    from hardware.power_probe import RetractablePowerProbe
    from tools.test_power_probe_hardware import (
        connect_stage,
        disconnect_devices,
        make_devices,
    )

    shutter, insertion_stage, meter = make_devices(arguments, include_meter=True)
    waveplate = RotationStage(serial=WAVEPLATE.serial, name=WAVEPLATE.name)
    probe = None
    try:
        connect_stage(shutter, insertion_stage, prepare_motion=True)
        assert meter is not None
        meter.connect()
        waveplate.connect()
        probe = RetractablePowerProbe(
            shutter=shutter,
            insertion_stage=insertion_stage,
            power_meter=meter,
            in_position_mm=POWER_METER_STAGE.in_position_mm,
            out_position_mm=POWER_METER_STAGE.out_position_mm,
            position_tolerance_mm=POWER_METER_STAGE.position_tolerance_mm,
        )
        probe.require_configured_positions()
        yield SimpleNamespace(
            shutter=shutter,
            power_meter_stage=insertion_stage,
            power_meter=meter,
            power_probe=probe,
            waveplate=waveplate,
        )
    finally:
        if shutter.connected:
            try:
                shutter.close()
            except Exception as error:
                print(f"ERROR: final shutter closure failed: {error}")
        if probe is not None and insertion_stage.connected and shutter.connected:
            try:
                probe.safe_retract()
            except Exception as error:
                print(f"ERROR: final probe retraction failed: {error}")
        if waveplate.connected:
            waveplate.disconnect()
        disconnect_devices(shutter=shutter, stage=insertion_stage, meter=meter)


def run(arguments: argparse.Namespace) -> Path:
    run_directory = _make_run_directory(arguments.output_directory, arguments.command)
    failure: BaseException | None = None
    payload: dict[str, Any] = {"command": arguments.command}
    starting_angle: float | None = None
    try:
        with _hardware_context(arguments) as hardware:
            measurement = HardwareMeasurement(arguments, run_directory)
            measurement.hardware = hardware
            starting_angle = float(hardware.waveplate.position)
            with hardware.power_probe.measurement_session() as session:
                measurement.session = session
                if arguments.command == "set-range":
                    midpoint = (
                        arguments.minimum_power_mw + arguments.maximum_power_mw
                    ) / 2.0
                    tolerance = (
                        arguments.maximum_power_mw - arguments.minimum_power_mw
                    ) / 2.0
                    controller = TargetPowerController(
                        measure_power_at_angle=measurement.measure,
                        waveplate_min_deg=arguments.waveplate_min_deg,
                        waveplate_max_deg=arguments.waveplate_max_deg,
                        monotonic_direction=arguments.direction,
                        tolerance_mw=tolerance,
                        maximum_iterations=arguments.maximum_iterations,
                        minimum_angle_step_deg=arguments.minimum_angle_step_deg,
                        calibration=(
                            None
                            if arguments.calibration is None
                            else MalusLawCalibration.load(arguments.calibration)
                        ),
                    )
                    result = controller.set_target(midpoint)
                    payload["result"] = asdict(result)
                    print(
                        f"POWER IN RANGE: {result.achieved_power_mw:.6g} mW at "
                        f"{result.waveplate_angle_deg:.6g} deg"
                    )
                else:
                    points: list[WaveplatePowerPoint] = []
                    for angle in scan_angles(
                        arguments.scan_start_deg,
                        arguments.scan_stop_deg,
                        arguments.step_deg,
                    ):
                        points.append(
                            WaveplatePowerPoint(angle, measurement.measure(angle))
                        )
                        payload["points"] = [asdict(point) for point in points]
                        _save_scan_csv(
                            run_directory / "waveplate_power.csv",
                            points,
                        )
                    branch = identify_monotonic_branch(
                        points,
                        noise_tolerance_mw=arguments.noise_tolerance_mw,
                    )
                    payload["recommended_branch"] = asdict(branch)
                    calibration = fit_malus_calibration(
                        [point.angle_deg for point in points],
                        [point.power_mw for point in points],
                        waveplate_min_deg=branch.start_deg,
                        waveplate_max_deg=branch.stop_deg,
                        monotonic_direction=branch.direction,
                        source=str(run_directory / "waveplate_power.csv"),
                    )
                    calibration_path = run_directory / "malus_calibration.json"
                    calibration.save(calibration_path)
                    payload["malus_calibration"] = asdict(calibration)
                    plot_path = run_directory / "waveplate_power_map.png"
                    plot_waveplate_power_map(
                        points,
                        branch=branch,
                        output_path=plot_path,
                    )
                    payload["plot_file"] = plot_path.name
                    print()
                    print("RECOMMENDED CONFIG VALUES")
                    print(f"waveplate_min_deg = {branch.start_deg:.9g}")
                    print(f"waveplate_max_deg = {branch.stop_deg:.9g}")
                    print(f'monotonic_direction = "{branch.direction}"')
                    print(
                        f"Malus fit RMS residual: "
                        f"{calibration.rms_residual_mw:.6g} mW"
                    )
                    print(f"Calibration file: {calibration_path}")
                    print(f"Highlighted plot: {plot_path}")
            if arguments.command == "scan" and starting_angle is not None:
                hardware.shutter.close()
                hardware.waveplate.move_to(starting_angle)
                payload["returned_waveplate_angle_deg"] = float(
                    hardware.waveplate.position
                )
    except BaseException as error:
        failure = error
        payload["failure"] = repr(error)
        raise
    finally:
        payload["created"] = datetime.now().isoformat()
        payload["starting_waveplate_angle_deg"] = starting_angle
        payload["final_waveplate_angle_deg"] = (
            None if failure is not None else payload.get("result", {}).get("waveplate_angle_deg")
        )
        with (run_directory / "run_summary.json").open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, default=str)
    print(f"Saved: {run_directory}")
    return run_directory


def _save_scan_csv(path: Path, points: Sequence[WaveplatePowerPoint]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=("angle_deg", "power_mw"))
        writer.writeheader()
        writer.writerows(asdict(point) for point in points)


def plot_waveplate_power_map(
    points: Sequence[WaveplatePowerPoint],
    *,
    branch: MonotonicBranch,
    output_path: Path,
) -> None:
    """Save the complete map with the recommended branch and endpoints marked."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    angles = [point.angle_deg for point in points]
    powers = [point.power_mw for point in points]
    branch_points = [
        point
        for point in points
        if branch.start_deg <= point.angle_deg <= branch.stop_deg
    ]

    figure, axis = plt.subplots(figsize=(9, 5.5))
    axis.plot(
        angles,
        powers,
        marker="o",
        linewidth=1.4,
        markersize=4,
        color="0.45",
        label="Measured power",
    )
    axis.axvspan(
        branch.start_deg,
        branch.stop_deg,
        color="tab:green",
        alpha=0.14,
        label=f"Recommended {branch.direction} branch",
    )
    axis.plot(
        [point.angle_deg for point in branch_points],
        [point.power_mw for point in branch_points],
        marker="o",
        linewidth=2.2,
        markersize=5,
        color="tab:green",
    )
    axis.scatter(
        [branch.start_deg, branch.stop_deg],
        [branch.start_power_mw, branch.stop_power_mw],
        s=85,
        color=("tab:blue", "tab:red"),
        edgecolors="black",
        linewidths=0.7,
        zorder=4,
    )
    axis.annotate(
        f"min angle = {branch.start_deg:.6g}°\n"
        f"{branch.start_power_mw:.6g} mW",
        (branch.start_deg, branch.start_power_mw),
        xytext=(8, 12),
        textcoords="offset points",
    )
    axis.annotate(
        f"max angle = {branch.stop_deg:.6g}°\n"
        f"{branch.stop_power_mw:.6g} mW",
        (branch.stop_deg, branch.stop_power_mw),
        xytext=(8, -34),
        textcoords="offset points",
    )
    axis.set(
        xlabel="Waveplate angle (deg)",
        ylabel="Measured power (mW)",
        title="Waveplate power map and recommended monotonic branch",
    )
    axis.grid(True, alpha=0.25)
    axis.legend(loc="best")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _make_run_directory(parent: Path, command: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(parent) / f"{command.replace('-', '_')}_{timestamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def print_summary(arguments: argparse.Namespace) -> None:
    from hardware.config import POWER_METER, POWER_METER_STAGE, SHUTTER, WAVEPLATE

    print("WAVEPLATE POWER CONTROL")
    print(f"Command             : {arguments.command}")
    print(f"Waveplate serial    : {WAVEPLATE.serial}")
    print(f"Shutter serial      : {SHUTTER.serial}")
    print(f"PI controller       : {POWER_METER_STAGE.serial}")
    print(f"Ophir controller    : {POWER_METER.controller_serial}")
    print(f"Initial settle      : {arguments.initial_settle_s} s")
    print(f"Per-point settle    : {arguments.settle_s} s")
    if arguments.command == "scan":
        print(
            f"Reviewed scan       : {arguments.scan_start_deg} to "
            f"{arguments.scan_stop_deg} deg in {arguments.step_deg} deg steps"
        )
        print("Limit search        : monotonic optical branch only; no end-stop search")
    else:
        print(
            f"Requested power     : {arguments.minimum_power_mw} to "
            f"{arguments.maximum_power_mw} mW"
        )
        print(
            f"Reviewed branch     : {arguments.waveplate_min_deg} to "
            f"{arguments.waveplate_max_deg} deg ({arguments.direction})"
        )
    print("Motion interlock    : shutter closed and verified before every move")
    print("Final safe state    : shutter closed, probe retracted")


def main() -> None:
    arguments = parse_arguments()
    print_summary(arguments)
    if not arguments.yes and input("Type RUN to connect and move hardware: ").strip() != "RUN":
        raise SystemExit("Cancelled before hardware connection.")
    run(arguments)


if __name__ == "__main__":
    main()
