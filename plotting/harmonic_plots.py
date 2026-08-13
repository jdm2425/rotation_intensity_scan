"""Offline rendering for reusable harmonic-analysis data products."""

from __future__ import annotations

from collections.abc import Iterable

import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np

from analysis.data_products import (
    AnalysedRun,
    FigureData,
    excitation_scan_data,
    rotation_scan_data,
)
from analysis.harmonic_analysis import HarmonicResult


def plot_figure_data(
    data: FigureData,
    *,
    polar: bool = False,
    connect_points: bool = True,
    annotation: str | None = None,
    axes=None,
    power_decimal_places: int = 1,
):
    """Render exactly the points stored in ``data``.

    Replicates at the same plotted coordinate are shown as their arithmetic
    mean with a standard-error-of-the-mean error bar. A single acquisition has
    a zero error bar. The raw replicate rows remain in ``FigureData`` and its
    CSV export. For a polar rotation plot it converts
    the saved sample angles from degrees to radians only at render time.
    """

    if polar and data.kind != "rotation_scan":
        raise ValueError("Polar rendering is only valid for rotation-scan data.")

    if axes is None:
        if polar:
            _, axes = plt.subplots(subplot_kw={"projection": "polar"})
        else:
            _, axes = plt.subplots()
    elif polar and getattr(axes, "name", "") != "polar":
        raise ValueError("Polar rendering requires polar Matplotlib axes.")

    for series_id in data.series_ids:
        records = data.records_for_series(series_id)
        grouped: dict[float, list[float]] = {}
        for record in records:
            grouped.setdefault(float(record.plot_x_value), []).append(
                float(record.plot_y_value)
            )
        x = np.asarray(sorted(grouped), dtype=float)
        groups = [np.asarray(grouped[value], dtype=float) for value in x]
        y = np.asarray([float(np.mean(values)) for values in groups])
        y_error = np.asarray([
            float(np.std(values, ddof=1) / np.sqrt(values.size))
            if values.size > 1 else 0.0
            for values in groups
        ])
        if polar:
            x = np.deg2rad(x)
        axes.errorbar(
            x,
            y,
            yerr=y_error,
            marker="o",
            linestyle="-" if connect_points else "None",
            label=records[0].series_label,
        )

    if not 0 <= int(power_decimal_places) <= 9:
        raise ValueError("power_decimal_places must be between 0 and 9.")
    power_format = f".{int(power_decimal_places)}f"
    fixed_label, fixed_unit = _coordinate_label(data.fixed_field)
    title_value = f"{data.fixed_value:g}"
    if data.fixed_field == "power_mw":
        power_value, power_std = _recorded_power_summary(data)
        title_value = format(power_value, power_format)
        if power_std is not None:
            title_value = f"{title_value} ± {format(power_std, power_format)}"
    if fixed_unit:
        title_value = f"{title_value} {fixed_unit}"
    if data.fixed_tolerance >= 1e-3:
        tolerance = (
            format(data.fixed_tolerance, power_format)
            if data.fixed_field == "power_mw"
            else f"{data.fixed_tolerance:g}"
        )
        if fixed_unit:
            tolerance = f"{tolerance} {fixed_unit}"
        title_value = f"{title_value} (tolerance ± {tolerance})"
    axes.set_title(f"{fixed_label} {title_value}")

    if not polar:
        axes.set_xlabel(_label_with_unit(data.x_label, data.x_unit))
        axes.set_ylabel(_label_with_unit(data.y_label, data.y_unit))
        axes.grid(True, alpha=0.3)
        if data.x_field == "power_mw":
            axes.xaxis.set_major_formatter(
                FormatStrFormatter(f"%.{int(power_decimal_places)}f")
            )
    if annotation:
        axes.figure.text(
            0.5,
            0.01,
            annotation,
            ha="center",
            va="bottom",
            fontsize="small",
        )
    axes.legend()
    return axes.figure, axes


def plot_harmonics_vs_excitation(
    runs: AnalysedRun | Iterable[AnalysedRun],
    *,
    sample_angle_deg: float,
    x_field: str = "waveplate_angle_deg",
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    angle_tolerance_deg: float = 1e-6,
    normalise: bool = False,
    connect_points: bool = True,
    axes=None,
):
    """Prepare and plot harmonics against waveplate, power, or intensity."""

    data = excitation_scan_data(
        runs,
        sample_angle_deg=sample_angle_deg,
        x_field=x_field,
        harmonics=harmonics,
        signal=signal,
        angle_tolerance_deg=angle_tolerance_deg,
        normalise=normalise,
    )
    return plot_figure_data(
        data,
        connect_points=connect_points,
        axes=axes,
    )


def plot_rotation_scan(
    runs: AnalysedRun | Iterable[AnalysedRun],
    *,
    fixed_field: str = "waveplate_angle_deg",
    fixed_value: float,
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    value_tolerance: float = 1e-6,
    normalise: bool = False,
    polar: bool = False,
    connect_points: bool = True,
    axes=None,
):
    """Prepare and plot sample rotation at fixed excitation."""

    data = rotation_scan_data(
        runs,
        fixed_field=fixed_field,
        fixed_value=fixed_value,
        harmonics=harmonics,
        signal=signal,
        value_tolerance=value_tolerance,
        normalise=normalise,
    )
    return plot_figure_data(
        data,
        polar=polar,
        connect_points=connect_points,
        axes=axes,
    )


def plot_harmonics_vs_waveplate(
    results: Iterable[HarmonicResult],
    *,
    sample_angle_deg: float,
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    angle_tolerance_deg: float = 1e-6,
    normalise: bool = False,
    axes=None,
):
    """Backward-compatible one-run waveplate plotting wrapper."""

    run = _standalone_run(results)
    return plot_harmonics_vs_excitation(
        run,
        sample_angle_deg=sample_angle_deg,
        x_field="waveplate_angle_deg",
        harmonics=harmonics,
        signal=signal,
        angle_tolerance_deg=angle_tolerance_deg,
        normalise=normalise,
        axes=axes,
    )


def plot_rotation_dependence(
    results: Iterable[HarmonicResult],
    *,
    waveplate_angle_deg: float,
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    angle_tolerance_deg: float = 1e-6,
    normalise: bool = False,
    polar: bool = False,
    axes=None,
):
    """Backward-compatible one-run waveplate-selected rotation wrapper."""

    run = _standalone_run(results)
    return plot_rotation_scan(
        run,
        fixed_field="waveplate_angle_deg",
        fixed_value=waveplate_angle_deg,
        harmonics=harmonics,
        signal=signal,
        value_tolerance=angle_tolerance_deg,
        normalise=normalise,
        polar=polar,
        axes=axes,
    )


def _standalone_run(results: Iterable[HarmonicResult]) -> AnalysedRun:
    materialised = tuple(results)
    return AnalysedRun(
        run_id="single-run",
        run_label="Single run",
        source_experiment=None,
        results=materialised,
    )


def _label_with_unit(label: str, unit: str) -> str:
    return f"{label} ({unit})" if unit else label


def _coordinate_label(field: str) -> tuple[str, str]:
    labels = {
        "sample_angle_deg": ("Sample angle", "deg"),
        "waveplate_angle_deg": ("Waveplate angle", "deg"),
        "power_mw": ("Achieved input power", "mW"),
        "fluence_mj_cm2": ("Fluence", "mJ/cm^2"),
        "intensity_w_cm2": ("Input intensity", "W/cm^2"),
    }
    return labels.get(field, (field, ""))


def _recorded_power_summary(data: FigureData) -> tuple[float, float | None]:
    """Summarise unique recorded traces without duplicating harmonics/angles."""

    traces: dict[object, tuple[float, float | None]] = {}
    for record in data.records:
        result = record.result
        if result.power_mw is None or not np.isfinite(result.power_mw):
            continue
        key = (
            result.power_measurement_id
            if result.power_measurement_id is not None
            else result.measurement_number
        )
        standard_deviation = (
            float(result.power_std_mw)
            if result.power_std_mw is not None
            and np.isfinite(result.power_std_mw)
            else None
        )
        traces[key] = (float(result.power_mw), standard_deviation)
    if not traces:
        return float(data.fixed_value), None
    powers = [value[0] for value in traces.values()]
    deviations = [
        value[1] for value in traces.values() if value[1] is not None
    ]
    return (
        float(np.mean(powers)),
        float(np.mean(deviations)) if deviations else None,
    )
