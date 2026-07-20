"""Laser-off commissioning test for target-power scan hardware order.

This utility exercises the real mechanical order used by a target-power scan
without attempting closed-loop power convergence.  Each simulated power block
uses one reviewed waveplate angle supplied by the operator:

    close shutter
    insert power probe once
    move waveplate with shutter closed
    optionally acquire one dark Ophir trace
    close shutter and retract probe once
    move sample through all requested angles
    optionally acquire dark spectra

The requested powers are labels only.  They are never treated as achieved
powers and are not used for feedback.  The operator must assert that the laser
is off before hardware connection.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import time
from typing import Any, Callable

import numpy as np


DEFAULT_WAVELENGTH_OPTION = ">800"
DEFAULT_RANGE_OPTION = "30.0mW"


@dataclass(frozen=True, slots=True)
class SimulatedPowerBlock:
    """One laser-off power-block label and its reviewed waveplate angle."""

    target_power_mw: float
    waveplate_angle_deg: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the real target-power scan motion order with the laser "
            "off. No closed-loop power convergence is attempted."
        )
    )
    parser.add_argument(
        "--laser-off",
        action="store_true",
        help="Required operator assertion that the laser source is off.",
    )
    parser.add_argument(
        "--sample-angles",
        type=float,
        nargs="+",
        required=True,
        help="Reviewed sample-stage angles in degrees.",
    )
    parser.add_argument(
        "--simulated-target-powers-mw",
        type=float,
        nargs="+",
        required=True,
        help=(
            "Labels for the power blocks. These values are logged only and "
            "are not used for feedback."
        ),
    )
    parser.add_argument(
        "--waveplate-angles",
        type=float,
        nargs="+",
        required=True,
        help=(
            "Reviewed waveplate angle for each simulated power block. The "
            "list length must match --simulated-target-powers-mw."
        ),
    )
    parser.add_argument(
        "--exercise-optical-paths",
        action="store_true",
        help=(
            "With the laser confirmed off, open the shutter to acquire one "
            "Ophir dark trace per power block and one dark spectrum per sample "
            "angle. Without this flag the shutter remains closed throughout."
        ),
    )
    parser.add_argument(
        "--power-duration-s",
        type=float,
        default=1.0,
        help="Duration of each dark Ophir trace in seconds (default: 1).",
    )
    parser.add_argument(
        "--power-settle-s",
        type=float,
        default=0.0,
        help="Delay after opening the shutter for a dark power trace (default: 0).",
    )
    parser.add_argument(
        "--integration-time-ms",
        type=float,
        default=10.0,
        help="Spectrometer integration time for dark acquisitions (default: 10).",
    )
    parser.add_argument(
        "--averages",
        type=int,
        default=1,
        help="Spectra averaged at each test point (default: 1).",
    )
    parser.add_argument(
        "--wavelength-option",
        default=DEFAULT_WAVELENGTH_OPTION,
        help=(
            "Exact Ophir wavelength option label "
            f"(default: {DEFAULT_WAVELENGTH_OPTION!r})."
        ),
    )
    parser.add_argument(
        "--range-option",
        default=DEFAULT_RANGE_OPTION,
        help=(
            "Exact Ophir fixed-range option label "
            f"(default: {DEFAULT_RANGE_OPTION!r})."
        ),
    )
    parser.add_argument(
        "--leave-rotation-stages",
        action="store_true",
        help=(
            "Leave sample and waveplate stages at their final test positions. "
            "By default both return to their starting positions."
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("results") / "target_power_hardware_order_tests",
        help="Parent output directory for the chronological test log.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the final typed RUN confirmation.",
    )
    return parser


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    arguments = build_parser().parse_args(argv)
    validate_arguments(arguments)
    return arguments


def validate_arguments(arguments: argparse.Namespace) -> None:
    if not arguments.laser_off:
        raise ValueError(
            "--laser-off is required. This tool cannot verify laser state; "
            "the flag is an explicit operator assertion."
        )

    if len(arguments.simulated_target_powers_mw) != len(arguments.waveplate_angles):
        raise ValueError(
            "--simulated-target-powers-mw and --waveplate-angles must contain "
            "the same number of values."
        )

    for name in (
        "sample_angles",
        "simulated_target_powers_mw",
        "waveplate_angles",
    ):
        values = [float(value) for value in getattr(arguments, name)]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError(f"--{name.replace('_', '-')} must contain finite values.")

    if any(float(value) <= 0 for value in arguments.simulated_target_powers_mw):
        raise ValueError("Simulated target-power labels must be positive.")

    for name in (
        "power_duration_s",
        "integration_time_ms",
    ):
        value = float(getattr(arguments, name))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive.")

    settle = float(arguments.power_settle_s)
    if not math.isfinite(settle) or settle < 0:
        raise ValueError("--power-settle-s must be non-negative.")

    if int(arguments.averages) < 1:
        raise ValueError("--averages must be at least one.")


def build_blocks(arguments: argparse.Namespace) -> list[SimulatedPowerBlock]:
    return [
        SimulatedPowerBlock(
            target_power_mw=float(target),
            waveplate_angle_deg=float(angle),
        )
        for target, angle in zip(
            arguments.simulated_target_powers_mw,
            arguments.waveplate_angles,
        )
    ]


def print_action_summary(arguments: argparse.Namespace) -> None:
    from hardware.config import (
        POWER_METER,
        POWER_METER_STAGE,
        SAMPLE_STAGE,
        SHUTTER,
        SPECTROMETER,
        WAVEPLATE,
    )

    print()
    print("=" * 76)
    print("LASER-OFF TARGET-POWER HARDWARE-ORDER TEST")
    print("=" * 76)
    print("Laser assertion       : OFF (operator supplied --laser-off)")
    print(f"Waveplate stage       : {WAVEPLATE.serial}")
    print(f"Sample stage          : {SAMPLE_STAGE.serial}")
    print(f"Shutter               : {SHUTTER.serial}")
    print(f"Spectrometer          : {SPECTROMETER.serial}")
    print(f"PI controller         : {POWER_METER_STAGE.serial}")
    print(f"Ophir controller      : {POWER_METER.controller_serial}")
    print(f"Sample angles         : {arguments.sample_angles}")
    print(f"Simulated powers      : {arguments.simulated_target_powers_mw} mW")
    print(f"Waveplate angles      : {arguments.waveplate_angles} deg")
    print(
        "Optical-path exercise : "
        + ("enabled; dark traces and spectra" if arguments.exercise_optical_paths else "disabled; shutter remains closed")
    )
    print(
        "Final rotation state  : "
        + ("leave at final positions" if arguments.leave_rotation_stages else "return to starting positions")
    )
    print("Guaranteed final goal : shutter closed, power probe retracted")
    print("=" * 76)
    print("Order for each simulated power block:")
    print("  1. Close shutter")
    print("  2. Insert and verify power probe once")
    print("  3. Move waveplate with shutter closed")
    if arguments.exercise_optical_paths:
        print("  4. Acquire one shutter-gated Ophir dark trace")
    else:
        print("  4. Keep shutter closed; skip Ophir acquisition")
    print("  5. Close shutter and retract probe once")
    print("  6. Move sample through the complete angle list")
    if arguments.exercise_optical_paths:
        print("  7. Acquire one dark spectrum at each sample angle")
    else:
        print("  7. Keep shutter closed; skip spectrum acquisition")
    print("=" * 76)


def require_confirmation(arguments: argparse.Namespace) -> None:
    if arguments.yes:
        return
    confirmation = input(
        "Confirm the laser source is OFF, then type RUN to connect hardware: "
    ).strip()
    if confirmation != "RUN":
        raise SystemExit("Hardware-order test cancelled before connection.")


class EventRecorder:
    """Chronological console and JSON event recorder."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, action: str, **details: Any) -> None:
        event = {
            "index": len(self.events) + 1,
            "time": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }
        self.events.append(event)
        detail_text = ", ".join(f"{key}={value!r}" for key, value in details.items())
        print(f"[{event['index']:03d}] {action}" + (f" | {detail_text}" if detail_text else ""))


def make_run_directory(parent: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(parent) / f"target_power_order_test_{timestamp}"
    path.mkdir(parents=True, exist_ok=False)
    (path / "spectra").mkdir()
    return path


def save_spectrum(
    *,
    run_directory: Path,
    spectrum,
    block_index: int,
    sample_index: int,
    block: SimulatedPowerBlock,
    sample_angle_deg: float,
) -> Path:
    path = run_directory / "spectra" / (
        f"block_{block_index:03d}_sample_{sample_index:03d}.npz"
    )
    np.savez_compressed(
        path,
        wavelengths=np.asarray(spectrum.wavelengths, dtype=float),
        intensities=np.asarray(spectrum.intensities, dtype=float),
        integration_time_ms=np.asarray(spectrum.integration_time_ms, dtype=float),
        averages=np.asarray(spectrum.averages, dtype=int),
        serial=np.asarray(spectrum.serial, dtype=str),
        simulated_target_power_mw=np.asarray(block.target_power_mw, dtype=float),
        waveplate_angle_deg=np.asarray(block.waveplate_angle_deg, dtype=float),
        sample_angle_deg=np.asarray(sample_angle_deg, dtype=float),
    )
    return path


def run_order_test(
    arguments: argparse.Namespace,
    *,
    hardware_factory: Callable[..., Any] | None = None,
    acquisition_factory: Callable[..., Any] | None = None,
) -> Path:
    """Execute the real or injected target-power hardware order."""

    if hardware_factory is None:
        from hardware.hardware_manager import HardwareManager

        hardware_factory = HardwareManager
    if acquisition_factory is None:
        from acquisition.acquisition import Acquisition

        acquisition_factory = Acquisition

    from tools.test_power_probe_hardware import save_trace

    run_directory = make_run_directory(arguments.output_directory)
    recorder = EventRecorder()
    blocks = build_blocks(arguments)
    failure: BaseException | None = None
    starting_waveplate: float | None = None
    starting_sample: float | None = None

    hardware_context = hardware_factory(
        enable_power_meter=True,
        power_meter_wavelength_option=arguments.wavelength_option,
        power_meter_range_option=arguments.range_option,
    )

    try:
        with hardware_context as hardware:
            try:
                recorder.record("hardware_connected")
                hardware.spectrometer.set_integration_time(
                    float(arguments.integration_time_ms)
                )
                acquisition = acquisition_factory(
                    spectrometer=hardware.spectrometer,
                    shutter=hardware.shutter,
                    shutter_open_delay=0.0,
                    shutter_close_delay=0.0,
                    before_open=hardware.require_sample_beam_path_clear,
                )

                starting_waveplate = float(hardware.waveplate.position)
                starting_sample = float(hardware.sample.position)
                recorder.record(
                    "starting_positions",
                    waveplate_angle_deg=starting_waveplate,
                    sample_angle_deg=starting_sample,
                )

                hardware.shutter.close()
                recorder.record("shutter_closed")

                for block_index, block in enumerate(blocks, start=1):
                    recorder.record(
                        "power_block_started",
                        block_index=block_index,
                        simulated_target_power_mw=block.target_power_mw,
                        planned_waveplate_angle_deg=block.waveplate_angle_deg,
                    )

                    with hardware.power_probe.measurement_session() as session:
                        recorder.record(
                            "power_probe_inserted",
                            block_index=block_index,
                            stage_position_mm=float(
                                hardware.power_meter_stage.position_mm
                            ),
                        )
                        session.prepare_for_motion()
                        recorder.record(
                            "waveplate_motion_guard_verified",
                            block_index=block_index,
                            shutter_closed=bool(hardware.shutter.is_closed),
                        )
                        hardware.waveplate.move_to(block.waveplate_angle_deg)
                        recorder.record(
                            "waveplate_moved",
                            block_index=block_index,
                            waveplate_angle_deg=float(hardware.waveplate.position),
                        )

                        if arguments.exercise_optical_paths:
                            trace = session.acquire_trace(
                                duration_s=float(arguments.power_duration_s),
                                settle_time_s=float(arguments.power_settle_s),
                            )
                            trace_summary = save_trace(
                                run_directory=run_directory,
                                trace=trace,
                                trace_index=block_index,
                                stage_position_mm=float(
                                    hardware.power_meter_stage.position_mm
                                ),
                            )
                            recorder.record(
                                "dark_power_trace_acquired",
                                block_index=block_index,
                                trace_id=trace.trace_id,
                                valid_samples=trace.statistics.valid_sample_count,
                                mean_power_mw=(
                                    trace.statistics.arithmetic_mean_power_mw
                                ),
                                summary_file=(
                                    f"trace_{block_index:03d}_summary.json"
                                ),
                                summary=trace_summary,
                            )
                        else:
                            recorder.record(
                                "dark_power_trace_skipped",
                                block_index=block_index,
                                shutter_closed=bool(hardware.shutter.is_closed),
                            )

                    hardware.require_sample_beam_path_clear()
                    recorder.record(
                        "power_probe_retracted",
                        block_index=block_index,
                        stage_position_mm=float(
                            hardware.power_meter_stage.position_mm
                        ),
                    )

                    for sample_index, sample_angle in enumerate(
                        arguments.sample_angles,
                        start=1,
                    ):
                        hardware.sample.move_to(float(sample_angle))
                        recorder.record(
                            "sample_moved",
                            block_index=block_index,
                            sample_index=sample_index,
                            sample_angle_deg=float(hardware.sample.position),
                        )

                        if arguments.exercise_optical_paths:
                            spectrum = acquisition.acquire(
                                averages=int(arguments.averages)
                            )
                            spectrum_path = save_spectrum(
                                run_directory=run_directory,
                                spectrum=spectrum,
                                block_index=block_index,
                                sample_index=sample_index,
                                block=block,
                                sample_angle_deg=float(sample_angle),
                            )
                            recorder.record(
                                "dark_spectrum_acquired",
                                block_index=block_index,
                                sample_index=sample_index,
                                spectrum_file=str(
                                    spectrum_path.relative_to(run_directory)
                                ),
                            )
                        else:
                            recorder.record(
                                "dark_spectrum_skipped",
                                block_index=block_index,
                                sample_index=sample_index,
                                shutter_closed=bool(hardware.shutter.is_closed),
                            )

                    recorder.record(
                        "power_block_finished",
                        block_index=block_index,
                        simulated_target_power_mw=block.target_power_mw,
                    )

            except BaseException as error:
                failure = error
                recorder.record("test_failed", error=repr(error))
                raise

            finally:
                cleanup_errors: list[BaseException] = []

                try:
                    hardware.shutter.close()
                    recorder.record("final_shutter_close_verified")
                except BaseException as error:
                    cleanup_errors.append(error)
                    recorder.record(
                        "final_shutter_close_failed",
                        error=repr(error),
                    )

                try:
                    if hardware.power_probe is not None:
                        hardware.power_probe.safe_retract()
                        recorder.record("final_probe_retraction_verified")
                except BaseException as error:
                    cleanup_errors.append(error)
                    recorder.record(
                        "final_probe_retraction_failed",
                        error=repr(error),
                    )

                if (
                    not arguments.leave_rotation_stages
                    and starting_waveplate is not None
                    and starting_sample is not None
                ):
                    try:
                        hardware.shutter.close()
                        hardware.require_sample_beam_path_clear()
                        hardware.waveplate.move_to(starting_waveplate)
                        recorder.record(
                            "waveplate_returned",
                            waveplate_angle_deg=float(
                                hardware.waveplate.position
                            ),
                        )
                        hardware.sample.move_to(starting_sample)
                        recorder.record(
                            "sample_returned",
                            sample_angle_deg=float(hardware.sample.position),
                        )
                    except BaseException as error:
                        cleanup_errors.append(error)
                        recorder.record(
                            "rotation_stage_return_failed",
                            error=repr(error),
                        )

                if failure is None and cleanup_errors:
                    raise RuntimeError(
                        "Laser-off hardware-order cleanup failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    ) from cleanup_errors[0]

    finally:
        summary = {
            "created": datetime.now().isoformat(),
            "laser_off_asserted": bool(arguments.laser_off),
            "exercise_optical_paths": bool(arguments.exercise_optical_paths),
            "sample_angles_deg": [
                float(value) for value in arguments.sample_angles
            ],
            "blocks": [
                {
                    "simulated_target_power_mw": block.target_power_mw,
                    "waveplate_angle_deg": block.waveplate_angle_deg,
                }
                for block in blocks
            ],
            "returned_rotation_stages": not arguments.leave_rotation_stages,
            "failure": None if failure is None else repr(failure),
            "events": recorder.events,
        }
        with (run_directory / "hardware_order_log.json").open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(summary, file, indent=2, default=str)

    print(f"Saved chronological hardware-order log: {run_directory}")
    return run_directory

def main() -> None:
    arguments = parse_arguments()
    print_action_summary(arguments)
    require_confirmation(arguments)
    run_order_test(arguments)


if __name__ == "__main__":
    main()
