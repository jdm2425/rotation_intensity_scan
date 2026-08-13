"""Operator-controlled PI-stage and Ophir power-probe hardware checks.

This tool intentionally avoids the rotation stages, sample stage, and
spectrometer.  Hardware-facing imports and connections occur only after the
operator has reviewed the printed action summary and typed ``RUN`` (or passed
``--yes``).

Examples
--------
Read identities and current PI position without motion::

    python -m tools.test_power_probe_hardware inspect

Move the PI stage to a reviewed position and return to the starting point::

    python -m tools.test_power_probe_hardware move --position-mm 0.5

Insert at the configured measurement position, collect three traces while
remaining inserted, save them, then retract once::

    python -m tools.test_power_probe_hardware measure --traces 3
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path
import time
from typing import Any


DEFAULT_WAVELENGTH_OPTION = ">800"
DEFAULT_RANGE_OPTION = "AUTO"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or move the configured PI power-meter stage and record "
            "standalone Ophir power traces."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the final typed RUN confirmation.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Connect read-only, print identities and PI state, then disconnect.",
    )
    _add_meter_options(inspect_parser)

    move_parser = subparsers.add_parser(
        "move",
        help="Move the PI stage to one reviewed absolute position.",
    )
    move_parser.add_argument(
        "--position-mm",
        type=float,
        required=True,
        help="Absolute PI-stage target in millimetres.",
    )
    move_parser.add_argument(
        "--leave-at-target",
        action="store_true",
        help=(
            "Leave the stage at the target. By default it returns to the "
            "starting position before disconnecting."
        ),
    )

    measure_parser = subparsers.add_parser(
        "measure",
        help=(
            "Insert once, record one or more shutter-gated power traces, "
            "then retract once."
        ),
    )
    _add_meter_options(measure_parser)
    measure_parser.add_argument(
        "--in-position-mm",
        type=float,
        default=None,
        help="Measurement position override; default uses hardware.config.",
    )
    measure_parser.add_argument(
        "--out-position-mm",
        type=float,
        default=None,
        help="Retracted position override; default uses hardware.config.",
    )
    measure_parser.add_argument(
        "--duration-s",
        type=float,
        default=3.0,
        help="Duration of each trace in seconds (default: 3).",
    )
    measure_parser.add_argument(
        "--settle-s",
        type=float,
        default=3.0,
        help="Wait after opening the shutter before each trace (default: 3).",
    )
    measure_parser.add_argument(
        "--initial-settle-s",
        type=float,
        default=5.0,
        help=(
            "Longer wait before the first trace after meter connection "
            "(default: 5). Later traces use --settle-s."
        ),
    )
    measure_parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=0.1,
        help="Ophir data polling interval in seconds (default: 0.1).",
    )
    measure_parser.add_argument(
        "--traces",
        type=int,
        default=1,
        help="Number of traces acquired during one insertion (default: 1).",
    )
    measure_parser.add_argument(
        "--between-trace-delay-s",
        type=float,
        default=0.0,
        help="Shutter-closed delay between traces (default: 0).",
    )
    measure_parser.add_argument(
        "--maximum-power-mw",
        type=float,
        default=None,
        help=(
            "Optional diagnostic warning threshold in mW. Measurements are "
            "still saved and subsequent traces continue unless "
            "--abort-above-maximum is also supplied."
        ),
    )
    measure_parser.add_argument(
        "--abort-above-maximum",
        action="store_true",
        help=(
            "Abort after saving a trace above --maximum-power-mw. This is "
            "off by default because this command is a diagnostic tool."
        ),
    )
    measure_parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("results") / "power_probe_hardware_tests",
        help="Parent output directory for trace files.",
    )

    return parser


def _add_meter_options(parser: argparse.ArgumentParser) -> None:
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


def parse_arguments() -> argparse.Namespace:
    arguments = build_parser().parse_args()
    _validate_arguments(arguments)
    return arguments


def _validate_arguments(arguments: argparse.Namespace) -> None:
    if arguments.command == "move":
        if not math.isfinite(arguments.position_mm):
            raise ValueError("--position-mm must be finite.")
        return

    if arguments.command == "measure":
        for name in (
            "duration_s",
            "poll_interval_s",
        ):
            value = float(getattr(arguments, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"--{name.replace('_', '-')} must be positive.")
        for name in ("settle_s", "initial_settle_s", "between_trace_delay_s"):
            value = float(getattr(arguments, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"--{name.replace('_', '-')} must be non-negative."
                )
        if arguments.traces < 1:
            raise ValueError("--traces must be at least one.")
        if arguments.maximum_power_mw is not None:
            value = float(arguments.maximum_power_mw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("--maximum-power-mw must be positive.")
        if arguments.abort_above_maximum and arguments.maximum_power_mw is None:
            raise ValueError(
                "--abort-above-maximum requires --maximum-power-mw."
            )
        for name in ("in_position_mm", "out_position_mm"):
            value = getattr(arguments, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"--{name.replace('_', '-')} must be finite.")


def print_action_summary(arguments: argparse.Namespace) -> None:
    # Pure configuration import; no vendor API or hardware connection occurs.
    from hardware.config import POWER_METER, POWER_METER_STAGE, SHUTTER

    print()
    print("=" * 72)
    print("POWER-PROBE HARDWARE TEST")
    print("=" * 72)
    print(f"Command             : {arguments.command}")
    print(f"Shutter serial      : {SHUTTER.serial}")
    print(f"PI controller       : {POWER_METER_STAGE.serial}")
    print(f"PI stage model      : {POWER_METER_STAGE.stage_model}")
    print(f"Ophir controller    : {POWER_METER.controller_serial}")
    print(f"Ophir sensor        : {POWER_METER.sensor_serial}")

    if arguments.command == "inspect":
        print("Motion              : none")
        print("Shutter action      : close and verify")
        print("Meter action        : connect, identify, disconnect")

    elif arguments.command == "move":
        print(f"Move target         : {arguments.position_mm:.6g} mm")
        print(
            "Final stage position : "
            + (
                "target (explicit --leave-at-target)"
                if arguments.leave_at_target
                else "original starting position"
            )
        )
        print("Shutter action      : close before every PI movement")
        print("Meter action        : not connected")

    elif arguments.command == "measure":
        in_position = (
            POWER_METER_STAGE.in_position_mm
            if arguments.in_position_mm is None
            else arguments.in_position_mm
        )
        out_position = (
            POWER_METER_STAGE.out_position_mm
            if arguments.out_position_mm is None
            else arguments.out_position_mm
        )
        print(f"Probe in position   : {in_position!r} mm")
        print(f"Probe out position  : {out_position!r} mm")
        print(f"Trace count         : {arguments.traces}")
        print(f"Trace duration      : {arguments.duration_s} s")
        print(f"Settle time         : {arguments.settle_s} s")
        print(f"Initial settle time : {arguments.initial_settle_s} s")
        print(
            "Diagnostic threshold: "
            + (
                "disabled"
                if arguments.maximum_power_mw is None
                else f"{arguments.maximum_power_mw} mW ("
                + ("abort" if arguments.abort_above_maximum else "warn only")
                + ")"
            )
        )
        print(f"Wavelength option   : {arguments.wavelength_option!r}")
        print(f"Range option        : {arguments.range_option!r}")
        print(
            "Probe motion        : one insertion, all traces, one retraction"
        )
        print("Final state         : shutter closed, probe at out position")

    print("=" * 72)


def require_confirmation(arguments: argparse.Namespace) -> None:
    if arguments.yes:
        return
    confirmation = input(
        "Type RUN to connect the listed physical hardware: "
    ).strip()
    if confirmation != "RUN":
        raise SystemExit("Hardware test cancelled before connection.")


def make_devices(arguments: argparse.Namespace, *, include_meter: bool):
    from hardware.config import POWER_METER, POWER_METER_STAGE, SHUTTER
    from hardware.devices.linear import PILinearStage
    from hardware.devices.shutter import BeamShutter

    shutter = BeamShutter(serial=SHUTTER.serial, name=SHUTTER.name)
    stage = PILinearStage.from_project_config(POWER_METER_STAGE)
    meter = None
    if include_meter:
        from hardware.devices.power_meter import OphirJunoPowerMeter

        meter = OphirJunoPowerMeter(
            controller_serial=POWER_METER.controller_serial,
            sensor_serial=POWER_METER.sensor_serial,
            wavelength_name=arguments.wavelength_option,
            fixed_range_name=arguments.range_option,
            name=POWER_METER.name,
        )
    return shutter, stage, meter


def connect_stage(shutter, stage, *, prepare_motion: bool) -> None:
    shutter.connect()
    shutter.close()
    if not shutter.is_closed:
        raise RuntimeError("Shutter did not verify closed before PI connection.")
    stage.connect()
    if prepare_motion:
        # stage.apply_configured_velocity()
        stage.prepare_for_closed_loop()
        stage.refresh_snapshot()


def run_inspect(arguments: argparse.Namespace) -> None:
    shutter, stage, meter = make_devices(arguments, include_meter=True)
    try:
        connect_stage(shutter, stage, prepare_motion=False)
        assert meter is not None
        meter.connect()
        snapshot = stage.refresh_snapshot()
        print_json(
            {
                "pi_stage": asdict(snapshot),
                "pi_limits": asdict(stage.motion_limits()),
                "ophir": meter.info(),
                "shutter_closed": bool(shutter.is_closed),
            }
        )
    finally:
        disconnect_devices(shutter=shutter, stage=stage, meter=meter)


def run_move(arguments: argparse.Namespace) -> None:
    shutter, stage, _ = make_devices(arguments, include_meter=False)
    start_position: float | None = None
    move_completed = False
    try:
        connect_stage(shutter, stage, prepare_motion=True)
        start_position = stage.position_mm
        print(f"Starting position: {start_position:.9g} mm")
        result = stage.move_absolute_mm(arguments.position_mm)
        move_completed = True
        print_json({"outbound_move": asdict(result)})
    finally:
        if (
            start_position is not None
            and move_completed
            and not arguments.leave_at_target
            and stage.connected
        ):
            try:
                if shutter.connected:
                    shutter.close()
                return_result = stage.move_absolute_mm(start_position)
                print_json({"return_move": asdict(return_result)})
            except Exception as error:
                print(f"ERROR: failed to return to starting position: {error}")
        disconnect_devices(shutter=shutter, stage=stage, meter=None)


def run_measure(arguments: argparse.Namespace) -> None:
    from hardware.config import POWER_METER_STAGE
    from hardware.power_probe import RetractablePowerProbe

    in_position = (
        POWER_METER_STAGE.in_position_mm
        if arguments.in_position_mm is None
        else float(arguments.in_position_mm)
    )
    out_position = (
        POWER_METER_STAGE.out_position_mm
        if arguments.out_position_mm is None
        else float(arguments.out_position_mm)
    )

    shutter, stage, meter = make_devices(arguments, include_meter=True)
    probe = None
    run_directory = make_run_directory(arguments.output_directory)
    summaries: list[dict[str, Any]] = []

    try:
        connect_stage(shutter, stage, prepare_motion=True)
        assert meter is not None
        meter.connect()
        probe = RetractablePowerProbe(
            shutter=shutter,
            insertion_stage=stage,
            power_meter=meter,
            in_position_mm=in_position,
            out_position_mm=out_position,
            position_tolerance_mm=POWER_METER_STAGE.position_tolerance_mm,
        )
        probe.require_configured_positions()

        with probe.measurement_session() as session:
            for trace_index in range(1, arguments.traces + 1):
                print(f"Acquiring trace {trace_index}/{arguments.traces}...")
                trace = session.acquire_trace(
                    duration_s=arguments.duration_s,
                    settle_time_s=(
                        arguments.initial_settle_s
                        if trace_index == 1
                        else arguments.settle_s
                    ),
                    poll_interval_s=arguments.poll_interval_s,
                )
                summary = save_trace(
                    run_directory=run_directory,
                    trace=trace,
                    trace_index=trace_index,
                    stage_position_mm=stage.position_mm,
                )
                summaries.append(summary)
                print_trace_summary(summary)
                maximum = summary["maximum_positive_raw_power_mw"]
                if (
                    maximum is not None
                    and arguments.maximum_power_mw is not None
                    and maximum > arguments.maximum_power_mw
                ):
                    message = (
                        f"Raw measured power {maximum:.6g} mW exceeded the "
                        f"diagnostic threshold "
                        f"{arguments.maximum_power_mw:.6g} mW."
                    )
                    if arguments.abort_above_maximum:
                        raise RuntimeError(message)
                    print(f"WARNING: {message} Continuing diagnostic traces.")
                if trace_index < arguments.traces and arguments.between_trace_delay_s:
                    time.sleep(arguments.between_trace_delay_s)

        write_json(
            run_directory / "run_summary.json",
            {
                "created": datetime.now().isoformat(),
                "command": "measure",
                "in_position_mm": in_position,
                "out_position_mm": out_position,
                "trace_count": len(summaries),
                "diagnostic_warning_threshold_mw": arguments.maximum_power_mw,
                "abort_above_diagnostic_threshold": bool(
                    arguments.abort_above_maximum
                ),
                "traces": summaries,
                "ophir": meter.info(),
                "pi_stage": stage.info(),
                "probe": probe.info(),
                "shutter_closed": bool(shutter.is_closed),
            },
        )
        print(f"Saved hardware test: {run_directory}")
    finally:
        if probe is not None and stage.connected and shutter.connected:
            try:
                probe.safe_retract()
            except Exception as error:
                print(f"ERROR: final verified probe retraction failed: {error}")
        disconnect_devices(shutter=shutter, stage=stage, meter=meter)


def disconnect_devices(*, shutter, stage, meter) -> None:
    if shutter.connected:
        try:
            shutter.close()
        except Exception as error:
            print(f"ERROR: shutter close during cleanup failed: {error}")

    for device in (meter, stage, shutter):
        if device is None:
            continue
        try:
            device.disconnect()
        except Exception as error:
            print(f"ERROR: disconnecting {device.name} failed: {error}")


def make_run_directory(parent: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(parent) / f"power_probe_test_{timestamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def save_trace(
    *,
    run_directory: Path,
    trace,
    trace_index: int,
    stage_position_mm: float,
) -> dict[str, Any]:
    csv_path = run_directory / f"trace_{trace_index:03d}.csv"
    fields = [
        "batch_index",
        "index_in_batch",
        "raw_value",
        "raw_timestamp",
        "raw_status",
        "power_w",
        "power_mw",
        "timestamp_s",
        "valid_for_statistics",
        "invalid_reasons",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for sample in trace.samples:
            writer.writerow(
                {
                    "batch_index": sample.batch_index,
                    "index_in_batch": sample.index_in_batch,
                    "raw_value": sample.raw_value,
                    "raw_timestamp": sample.raw_timestamp,
                    "raw_status": sample.raw_status,
                    "power_w": sample.power_w,
                    "power_mw": sample.power_mw,
                    "timestamp_s": sample.timestamp_s,
                    "valid_for_statistics": sample.valid_for_statistics,
                    "invalid_reasons": ";".join(sample.invalid_reasons),
                }
            )

    statistics = trace.statistics
    positive_raw_mw = [
        sample.power_mw
        for sample in trace.samples
        if sample.power_mw is not None
        and math.isfinite(sample.power_mw)
        and sample.power_mw > 0
    ]
    summary = {
        "trace_index": trace_index,
        "trace_id": trace.trace_id,
        "csv_file": csv_path.name,
        "stage_position_mm": stage_position_mm,
        "requested_duration_s": trace.requested_duration_s,
        "elapsed_duration_s": trace.elapsed_duration_s,
        "controller_serial": trace.device_serial,
        "sensor_serial": trace.sensor_serial,
        "measurement_mode": trace.measurement_mode,
        "wavelength_option": trace.wavelength_option,
        "range_option": trace.range_option,
        "total_sample_count": statistics.total_sample_count,
        "valid_sample_count": statistics.valid_sample_count,
        "invalid_sample_count": statistics.invalid_sample_count,
        "mean_power_mw": statistics.arithmetic_mean_power_mw,
        "standard_deviation_mw": statistics.population_standard_deviation_mw,
        "rms_power_mw": statistics.absolute_root_mean_square_power_mw,
        "minimum_power_mw": statistics.minimum_power_mw,
        "maximum_power_mw": statistics.maximum_power_mw,
        "maximum_positive_raw_power_mw": (
            max(positive_raw_mw) if positive_raw_mw else None
        ),
        "invalid_reason_counts": list(statistics.invalid_reason_counts),
    }
    write_json(run_directory / f"trace_{trace_index:03d}_summary.json", summary)
    return summary


def print_trace_summary(summary: dict[str, Any]) -> None:
    print(
        "Trace {trace_index}: mean={mean_power_mw!r} mW, "
        "std={standard_deviation_mw!r} mW, valid={valid_sample_count}/"
        "{total_sample_count}".format(**summary)
    )


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, default=str)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def main() -> None:
    arguments = parse_arguments()
    print_action_summary(arguments)
    require_confirmation(arguments)

    if arguments.command == "inspect":
        run_inspect(arguments)
    elif arguments.command == "move":
        run_move(arguments)
    elif arguments.command == "measure":
        run_measure(arguments)
    else:  # argparse enforces this; keep a defensive guard.
        raise RuntimeError(f"Unsupported command: {arguments.command}")


if __name__ == "__main__":
    main()
