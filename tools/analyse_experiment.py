"""Load a saved experiment and run explicit offline harmonic analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from analysis.analysis_reporting import (
    BACKGROUND_EXPLICITLY_NOT_USED,
    BACKGROUND_NOT_SPECIFIED,
    BACKGROUND_USED,
    TRANSMISSION_CURVE,
    TRANSMISSION_EXPLICITLY_NOT_USED,
    TRANSMISSION_NOT_SPECIFIED,
    TRANSMISSION_SCALAR,
    build_analysis_warnings,
    build_quality_summary,
    correction_annotation,
    render_analysis_summary,
    render_console_summary,
)
from analysis.data_products import (
    EXCITATION_FIELDS,
    SIGNAL_FIELDS,
    AnalysedRun,
    FigureData,
    coordinate_values,
    excitation_scan_data,
    rotation_scan_data,
    save_figure_data_csv,
)
from analysis.harmonic_analysis import (
    HarmonicResult,
    HarmonicWindow,
    TransmissionCurve,
    analyse_dataset,
    save_results_csv,
)
from data.background_spectrum import BackgroundSpectrum
from data.data_loader import load_experiment
from plotting.harmonic_plots import plot_figure_data


def parse_harmonic(value: str) -> HarmonicWindow:
    """Parse NAME:MIN_NM:MAX_NM from the command line."""

    parts = value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "Harmonics must use NAME:MIN_NM:MAX_NM, for example H5:390:410."
        )

    name, minimum, maximum = parts
    try:
        return HarmonicWindow(
            name=name,
            wavelength_min_nm=float(minimum),
            wavelength_max_nm=float(maximum),
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Integrate one or more harmonic wavelength windows from a saved "
            "experiment. Acquisition data are never modified."
        )
    )
    parser.add_argument("experiment_directory", type=Path)
    parser.add_argument(
        "--harmonic",
        action="append",
        type=parse_harmonic,
        required=True,
        help="Repeatable NAME:MIN_NM:MAX_NM harmonic definition.",
    )
    background_options = parser.add_mutually_exclusive_group()
    background_options.add_argument(
        "--use-background",
        nargs="?",
        const="pre_scan_dark",
        default=None,
        metavar="NAME",
        help="Subtract a named saved background (default name: pre_scan_dark).",
    )
    background_options.add_argument(
        "--no-background",
        action="store_true",
        help="Explicitly analyse without subtracting a saved background.",
    )

    transmission = parser.add_mutually_exclusive_group()
    transmission.add_argument(
        "--transmission-fraction",
        type=float,
        default=None,
        help="Explicit constant filter transmission fraction, in (0, 1].",
    )
    transmission.add_argument(
        "--transmission-curve",
        type=Path,
        default=None,
        help=(
            "CSV containing wavelength_nm and transmission_fraction columns."
        ),
    )
    transmission.add_argument(
        "--no-transmission-correction",
        action="store_true",
        help="Explicitly analyse without a filter-transmission correction.",
    )
    parser.add_argument(
        "--minimum-transmission-fraction",
        type=float,
        default=1e-6,
        help="Reject corrections below this transmission fraction.",
    )

    parser.add_argument(
        "--sample-angle",
        action="append",
        type=float,
        default=[],
        help="Create a harmonic-vs-input plot at this sample angle.",
    )
    parser.add_argument(
        "--input-coordinate",
        choices=EXCITATION_FIELDS,
        default="waveplate_angle_deg",
        help=(
            "Excitation coordinate for input scans and fixed-value rotation "
            "selection. Missing calibrated values are never inferred."
        ),
    )
    parser.add_argument(
        "--input-value",
        action="append",
        type=float,
        default=[],
        help=(
            "Create a rotation plot at this value of --input-coordinate; "
            "repeat for multiple values."
        ),
    )
    parser.add_argument(
        "--input-tolerance",
        type=float,
        default=1e-6,
        help=(
            "Absolute tolerance used when matching a fixed input value for "
            "a rotation plot."
        ),
    )
    parser.add_argument(
        "--waveplate-angle",
        action="append",
        type=float,
        default=[],
        help=(
            "Create a rotation plot at this waveplate angle. This is a "
            "backward-compatible alias for --input-value when the input "
            "coordinate is waveplate_angle_deg."
        ),
    )
    parser.add_argument(
        "--signal",
        choices=SIGNAL_FIELDS,
        default="integrated_signal",
        help="Derived signal field to plot and export for each figure.",
    )
    parser.add_argument(
        "--polar",
        action="store_true",
        help="Also create polar versions of requested rotation plots.",
    )
    parser.add_argument(
        "--plot-all",
        action="store_true",
        help=(
            "Create input plots for every sample angle and rotation plots "
            "for every available value of --input-coordinate. For achieved "
            "power data, complete target-power setpoints define the automatic "
            "rotation centres."
        ),
    )
    parser.add_argument(
        "--normalise",
        action="store_true",
        help="Normalise each plotted harmonic by its maximum absolute signal.",
    )
    parser.add_argument(
        "--annotate-corrections",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Add the background, transmission, and signal choices to "
            "quick-look figures (enabled by default)."
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=None,
        help="Analysis output directory; defaults inside the experiment.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if (
        not math.isfinite(arguments.input_tolerance)
        or arguments.input_tolerance < 0
    ):
        raise ValueError("--input-tolerance must be finite and non-negative.")
    dataset = load_experiment(arguments.experiment_directory)

    available_backgrounds = [
        saved_background.name for saved_background in dataset.backgrounds
    ]
    background = None
    if arguments.use_background is not None:
        background = dataset.get_background(arguments.use_background)
        background_mode = BACKGROUND_USED
    elif arguments.no_background:
        background_mode = BACKGROUND_EXPLICITLY_NOT_USED
    else:
        background_mode = BACKGROUND_NOT_SPECIFIED

    transmission_curve = None
    curve_hash = None
    if arguments.transmission_curve is not None:
        transmission_curve = TransmissionCurve.from_csv(
            arguments.transmission_curve
        )
        curve_hash = _sha256(arguments.transmission_curve)
        transmission_mode = TRANSMISSION_CURVE
    elif arguments.transmission_fraction is not None:
        transmission_mode = TRANSMISSION_SCALAR
    elif arguments.no_transmission_correction:
        transmission_mode = TRANSMISSION_EXPLICITLY_NOT_USED
    else:
        transmission_mode = TRANSMISSION_NOT_SPECIFIED

    results = analyse_dataset(
        dataset,
        arguments.harmonic,
        background=background,
        transmission_fraction=arguments.transmission_fraction,
        transmission_curve=transmission_curve,
        minimum_transmission_fraction=(
            arguments.minimum_transmission_fraction
        ),
    )

    if (
        arguments.waveplate_angle
        and arguments.input_coordinate != "waveplate_angle_deg"
    ):
        raise ValueError(
            "--waveplate-angle can only be combined with "
            "--input-coordinate waveplate_angle_deg. Use --input-value for "
            f"{arguments.input_coordinate}."
        )

    output_directory = arguments.output_directory
    if output_directory is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_directory = (
            dataset.root / "analysis" / f"harmonic_analysis_{timestamp}"
        )
    output_directory = output_directory.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=False)

    signals_path = save_results_csv(
        results,
        output_directory / "harmonic_signals.csv",
    )

    copied_curve = None
    if arguments.transmission_curve is not None:
        calibration_directory = output_directory / "calibration"
        calibration_directory.mkdir()
        copied_curve = calibration_directory / arguments.transmission_curve.name
        shutil.copy2(arguments.transmission_curve, copied_curve)

    experimental_metadata = dataset.metadata.get("experimental_metadata", {})
    if not isinstance(experimental_metadata, dict):
        experimental_metadata = {}
    saved_run_label = str(experimental_metadata.get("run_label", "")).strip()
    analysed_run = AnalysedRun(
        run_id=dataset.root.name,
        run_label=saved_run_label or dataset.experiment_name,
        source_experiment=dataset.root,
        results=tuple(results),
        analysis_directory=output_directory,
    )

    background_record = _background_recipe(
        mode=background_mode,
        available_backgrounds=available_backgrounds,
        background=background,
    )
    transmission_record = _transmission_recipe(
        mode=transmission_mode,
        fraction=arguments.transmission_fraction,
        copied_curve=copied_curve,
        curve_hash=curve_hash,
        minimum_fraction=arguments.minimum_transmission_fraction,
    )
    quality_summary = build_quality_summary(results)
    warnings = build_analysis_warnings(
        results=results,
        background_mode=background_mode,
        available_backgrounds=available_backgrounds,
        transmission_mode=transmission_mode,
        experimental_metadata=experimental_metadata,
    )

    recipe = {
        "analysis_format_version": 2,
        "analysis_id": output_directory.name,
        "created": datetime.now().isoformat(),
        "source_experiment": str(dataset.root),
        "source_run_id": dataset.root.name,
        "source_format_version": dataset.metadata.get("format_version"),
        "experimental_metadata": experimental_metadata,
        "harmonics": [asdict(window) for window in arguments.harmonic],
        "background": background_record,
        "transmission_correction": transmission_record,
        "integration": "numpy.trapezoid",
        "correction_order": [
            "raw detector data",
            "optional saved-background subtraction",
            "optional filter-transmission correction",
            "harmonic-window trapezoidal integration",
        ],
        "correction_pipeline": _correction_pipeline(
            background_record,
            transmission_record,
        ),
        "normalise_plots": arguments.normalise,
        "annotate_corrections": arguments.annotate_corrections,
        "plot_signal": arguments.signal,
        "input_coordinate": arguments.input_coordinate,
        "input_tolerance": arguments.input_tolerance,
        "quality_summary": quality_summary,
        "warnings": warnings,
        "software": {
            "application": "Rotation Intensity Scan",
            "entry_point": "tools.analyse_experiment",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "checksums": {
            "algorithm": "sha256",
            "harmonic_signals.csv": _sha256(signals_path),
        },
        "figures": [],
    }

    figures_directory = output_directory / "figures"
    sample_angles = set(arguments.sample_angle)
    explicit_input_values = set(arguments.input_value)
    explicit_input_values.update(arguments.waveplate_angle)
    input_values = set(explicit_input_values)
    automatic_values: list[float] = []
    automatic_input_source = None
    if arguments.plot_all:
        sample_angles.update(dataset.sample_angles)
        automatic_values, automatic_input_source = _automatic_input_values(
            results,
            arguments.input_coordinate,
        )
        input_values.update(automatic_values)

    recipe["rotation_centres"] = {
        "values": sorted(input_values),
        "explicit_values": sorted(explicit_input_values),
        "automatic_values": automatic_values,
        "automatic_source": automatic_input_source,
        "selection_field": arguments.input_coordinate,
        "absolute_tolerance": arguments.input_tolerance,
    }
    recipe_path = output_directory / "analysis_recipe.json"
    _write_json(recipe_path, recipe)
    figure_annotation = (
        correction_annotation(recipe)
        if arguments.annotate_corrections
        else None
    )

    figure_manifest: list[dict] = []
    coordinate_slug = _coordinate_slug(arguments.input_coordinate)

    for sample_angle in sorted(sample_angles):
        figures_directory.mkdir(exist_ok=True)
        figure_data = excitation_scan_data(
            analysed_run,
            sample_angle_deg=sample_angle,
            x_field=arguments.input_coordinate,
            signal=arguments.signal,
            normalise=arguments.normalise,
        )
        figure, _ = plot_figure_data(
            figure_data,
            annotation=figure_annotation,
        )
        figure_manifest.append(_save_figure(
            figure,
            figures_directory / f"{coordinate_slug}_sample_{sample_angle:g}",
            figure_data,
            plot_type="excitation_cartesian",
            analysis_directory=output_directory,
            annotation=figure_annotation,
        ))

    for input_value in sorted(input_values):
        figures_directory.mkdir(exist_ok=True)
        figure_data = rotation_scan_data(
            analysed_run,
            fixed_field=arguments.input_coordinate,
            fixed_value=input_value,
            value_tolerance=arguments.input_tolerance,
            signal=arguments.signal,
            normalise=arguments.normalise,
        )
        figure, _ = plot_figure_data(
            figure_data,
            annotation=figure_annotation,
        )
        figure_manifest.append(_save_figure(
            figure,
            figures_directory / f"rotation_{coordinate_slug}_{input_value:g}",
            figure_data,
            plot_type="rotation_cartesian",
            analysis_directory=output_directory,
            annotation=figure_annotation,
        ))

        if arguments.polar:
            figure, _ = plot_figure_data(
                figure_data,
                polar=True,
                annotation=figure_annotation,
            )
            figure_manifest.append(_save_figure(
                figure,
                figures_directory
                / f"rotation_polar_{coordinate_slug}_{input_value:g}",
                figure_data,
                plot_type="rotation_polar",
                analysis_directory=output_directory,
                annotation=figure_annotation,
            ))

    recipe["figures"] = figure_manifest
    _write_json(recipe_path, recipe)
    recipe_hash = _sha256(recipe_path)
    _write_text(
        output_directory / "analysis_recipe.sha256",
        f"{recipe_hash}  analysis_recipe.json\n",
    )
    _write_text(
        output_directory / "analysis_summary.md",
        render_analysis_summary(recipe, recipe_sha256=recipe_hash),
    )

    print(render_console_summary(recipe))
    print(f"Loaded experiment: {dataset.root}")
    print(f"Measurements:      {len(dataset)}")
    print(f"Backgrounds:       {len(dataset.backgrounds)}")
    print(f"Harmonic rows:     {len(results)}")
    print(f"Figure bundles:    {len(figure_manifest)} (PNG/PDF/CSV)")
    print(f"Summary:           {output_directory / 'analysis_summary.md'}")
    print(f"Recipe:            {recipe_path}")
    print(f"Analysis saved:    {output_directory}")


def _save_figure(
    figure,
    base_path: Path,
    data: FigureData,
    *,
    plot_type: str,
    analysis_directory: Path,
    annotation: str | None,
) -> dict:
    png_path = _append_extension(base_path, ".png")
    pdf_path = _append_extension(base_path, ".pdf")
    csv_path = _append_extension(base_path, ".csv")
    if annotation:
        figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    else:
        figure.tight_layout()
    figure.savefig(png_path, dpi=300)
    figure.savefig(pdf_path)
    save_figure_data_csv(data, csv_path)
    plt.close(figure)
    return {
        "plot_type": plot_type,
        "png_file": png_path.relative_to(analysis_directory).as_posix(),
        "pdf_file": pdf_path.relative_to(analysis_directory).as_posix(),
        "data_file": csv_path.relative_to(analysis_directory).as_posix(),
        "x_field": data.x_field,
        "x_label": data.x_label,
        "x_unit": data.x_unit,
        "signal": data.signal,
        "normalisation": data.normalisation,
        "fixed_field": data.fixed_field,
        "fixed_value": data.fixed_value,
        "fixed_tolerance": data.fixed_tolerance,
        "fixed_unit": data.records[0].fixed_unit,
        "matched_fixed_min": _matched_fixed_bound(data, minimum=True),
        "matched_fixed_max": _matched_fixed_bound(data, minimum=False),
        "correction_annotation": annotation,
        "data_sha256": _sha256(csv_path),
        "series_ids": list(data.series_ids),
        "row_count": len(data.records),
    }


def _append_extension(path: Path, extension: str) -> Path:
    """Append an extension without losing a decimal coordinate suffix."""

    return path.parent / f"{path.name}{extension}"


def _coordinate_slug(field: str) -> str:
    return {
        "waveplate_angle_deg": "waveplate",
        "power_mw": "power_mw",
        "fluence_mj_cm2": "fluence_mj_cm2",
        "intensity_w_cm2": "intensity_w_cm2",
    }[field]


def _automatic_input_values(
    results: list[HarmonicResult],
    field: str,
) -> tuple[list[float], str]:
    if field == "power_mw":
        target_values = [
            result.target_power_mw
            for result in results
            if result.target_power_mw is not None
        ]
        if target_values and len(target_values) == len(results):
            return sorted(set(target_values)), "target_power_mw"
    return coordinate_values(results, field), field


def _background_recipe(
    *,
    mode: str,
    available_backgrounds: list[str],
    background: BackgroundSpectrum | None,
) -> dict:
    record = {
        "mode": mode,
        "applied": mode == BACKGROUND_USED,
        "available_backgrounds": list(available_backgrounds),
        "name": None,
        "spectrum_timestamp": None,
        "metadata": {},
        "source_file": None,
        "source_sha256": None,
    }
    if background is not None:
        record.update(
            {
                "name": background.name,
                "spectrum_timestamp": background.spectrum.timestamp,
                "metadata": background.metadata,
                "source_file": (
                    str(background.source_path)
                    if background.source_path is not None
                    else None
                ),
                "source_sha256": (
                    _sha256(background.source_path)
                    if background.source_path is not None
                    else None
                ),
            }
        )
    return record


def _transmission_recipe(
    *,
    mode: str,
    fraction: float | None,
    copied_curve: Path | None,
    curve_hash: str | None,
    minimum_fraction: float,
) -> dict:
    return {
        "mode": mode,
        "applied": mode in {TRANSMISSION_SCALAR, TRANSMISSION_CURVE},
        "fraction": fraction,
        "source_file": (
            (Path("calibration") / copied_curve.name).as_posix()
            if copied_curve is not None
            else None
        ),
        "source_sha256": curve_hash,
        "minimum_fraction": minimum_fraction,
    }


def _correction_pipeline(
    background: dict,
    transmission: dict,
) -> list[dict]:
    return [
        {
            "order": 1,
            "name": "raw_detector_data",
            "mode": "source",
            "applied": True,
        },
        {
            "order": 2,
            "name": "saved_background_subtraction",
            "mode": background["mode"],
            "applied": background["applied"],
        },
        {
            "order": 3,
            "name": "filter_transmission_correction",
            "mode": transmission["mode"],
            "applied": transmission["applied"],
        },
        {
            "order": 4,
            "name": "harmonic_window_integration",
            "mode": "numpy.trapezoid",
            "applied": True,
        },
    ]


def _matched_fixed_bound(
    data: FigureData,
    *,
    minimum: bool,
) -> float | None:
    values = [
        getattr(record.result, data.fixed_field)
        for record in data.records
    ]
    finite_values = [
        float(value)
        for value in values
        if value is not None and math.isfinite(value)
    ]
    if not finite_values:
        return None
    return min(finite_values) if minimum else max(finite_values)


def _write_json(path: Path, value: dict) -> None:
    temporary_path = path.parent / f".{path.name}.tmp"
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=4, ensure_ascii=False)
        file.flush()
    temporary_path.replace(path)


def _write_text(path: Path, value: str) -> None:
    temporary_path = path.parent / f".{path.name}.tmp"
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(value)
        file.flush()
    temporary_path.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
