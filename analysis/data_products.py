"""Reusable, hardware-independent data products for harmonic plots.

The extraction layer in :mod:`analysis.harmonic_analysis` produces one
``HarmonicResult`` per measurement and harmonic window.  This module keeps
those quantitative rows separate from presentation while preparing the exact
subsets and transformations used by figures.  The same ``FigureData`` object
is therefore consumed by Matplotlib and by CSV export.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from analysis.harmonic_analysis import HarmonicResult, load_results_csv


EXCITATION_FIELDS = (
    "waveplate_angle_deg",
    "power_mw",
    "fluence_mj_cm2",
    "intensity_w_cm2",
)

SIGNAL_FIELDS = (
    "integrated_signal",
    "raw_integrated_signal",
    "background_corrected_integral",
    "peak_signal",
    "raw_peak_signal",
)

_COORDINATE_SPECS = {
    "waveplate_angle_deg": ("Waveplate angle", "deg"),
    "power_mw": ("Achieved input power", "mW"),
    "fluence_mj_cm2": ("Fluence", "mJ/cm^2"),
    "intensity_w_cm2": ("Input intensity", "W/cm^2"),
    "sample_angle_deg": ("Sample angle", "deg"),
}

_SIGNAL_SPECS = {
    "integrated_signal": ("Integrated spectral counts", "counts*nm"),
    "raw_integrated_signal": (
        "Raw integrated spectral counts",
        "counts*nm",
    ),
    "background_corrected_integral": (
        "Background-corrected integrated spectral counts",
        "counts*nm",
    ),
    "peak_signal": ("Peak spectral counts", "counts"),
    "raw_peak_signal": ("Raw peak spectral counts", "counts"),
}


@dataclass(frozen=True, slots=True)
class AnalysedRun:
    """One analysed experiment with a unique identity and provenance."""

    run_id: str
    run_label: str
    source_experiment: Path | None
    results: tuple[HarmonicResult, ...]
    recipe: dict = field(default_factory=dict)
    analysis_directory: Path | None = None

    def __post_init__(self) -> None:
        run_id = str(self.run_id).strip()
        if not run_id:
            raise ValueError("Analysed-run ID must not be empty.")

        results = tuple(self.results)
        if not results:
            raise ValueError(f"Analysed run {run_id!r} contains no results.")
        if not isinstance(self.recipe, dict):
            raise TypeError("Analysed-run recipe must be a dictionary.")

        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "run_label", str(self.run_label).strip() or run_id)
        source_experiment = self.source_experiment
        if source_experiment is None or not str(source_experiment).strip():
            normalised_source = None
        else:
            normalised_source = Path(source_experiment).expanduser().resolve()
        object.__setattr__(self, "source_experiment", normalised_source)
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "recipe", dict(self.recipe))
        if self.analysis_directory is not None:
            object.__setattr__(
                self,
                "analysis_directory",
                Path(self.analysis_directory).expanduser().resolve(),
            )


@dataclass(frozen=True, slots=True)
class FigureRecord:
    """One exact plotted point plus its original quantitative result."""

    figure_kind: str
    fixed_field: str
    fixed_value: float
    run_id: str
    run_label: str
    source_experiment: str
    source_analysis: str
    series_id: str
    series_label: str
    plot_x_field: str
    plot_x_value: float
    plot_x_unit: str
    plot_y_field: str
    signal_value: float
    plot_y_value: float
    plot_y_unit: str
    normalisation: str
    normalisation_factor: float
    result: HarmonicResult
    fixed_tolerance: float = 0.0
    plot_x_label: str = ""
    fixed_unit: str = ""

    def as_dict(self) -> dict:
        """Return a flat, tidy row suitable for CSV or a dataframe."""

        row = {
            "figure_kind": self.figure_kind,
            "fixed_field": self.fixed_field,
            "fixed_value": self.fixed_value,
            "fixed_tolerance": self.fixed_tolerance,
            "fixed_unit": self.fixed_unit,
            "run_id": self.run_id,
            "run_label": self.run_label,
            "source_experiment": self.source_experiment,
            "source_analysis": self.source_analysis,
            "series_id": self.series_id,
            "series_label": self.series_label,
            "plot_x_field": self.plot_x_field,
            "plot_x_label": self.plot_x_label,
            "plot_x_value": self.plot_x_value,
            "plot_x_unit": self.plot_x_unit,
            "plot_angle_rad": (
                float(np.deg2rad(self.plot_x_value))
                if self.plot_x_field == "sample_angle_deg"
                else None
            ),
            "plot_y_field": self.plot_y_field,
            "signal_value": self.signal_value,
            "plot_y_value": self.plot_y_value,
            "plot_y_unit": self.plot_y_unit,
            "normalisation": self.normalisation,
            "normalisation_factor": self.normalisation_factor,
        }
        row.update(self.result.as_dict())
        return row


@dataclass(frozen=True, slots=True)
class FigureData:
    """Exact long-form dataset used to render one scientific figure."""

    kind: str
    x_field: str
    x_label: str
    x_unit: str
    signal: str
    y_label: str
    y_unit: str
    normalisation: str
    fixed_field: str
    fixed_value: float
    records: tuple[FigureRecord, ...]
    fixed_tolerance: float = 0.0

    def __post_init__(self) -> None:
        records = tuple(self.records)
        if not records:
            raise ValueError("Figure data must contain at least one point.")
        fixed_tolerance = float(self.fixed_tolerance)
        if not np.isfinite(fixed_tolerance) or fixed_tolerance < 0:
            raise ValueError(
                "Figure fixed-value tolerance must be finite and non-negative."
            )
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "fixed_tolerance", fixed_tolerance)

    @property
    def series_ids(self) -> tuple[str, ...]:
        """Series IDs in deterministic plotting order."""

        return tuple(dict.fromkeys(record.series_id for record in self.records))

    def records_for_series(self, series_id: str) -> tuple[FigureRecord, ...]:
        """Return all plotted points belonging to one series."""

        return tuple(
            record for record in self.records if record.series_id == series_id
        )


def load_analysed_run(
    path: str | Path,
    *,
    label: str | None = None,
    run_id: str | None = None,
) -> AnalysedRun:
    """Load a quick-analysis directory as a reusable publication data run."""

    path = Path(path).expanduser().resolve()
    analysis_directory = path if path.is_dir() else path.parent
    results = tuple(load_results_csv(path))

    recipe_path = analysis_directory / "analysis_recipe.json"
    recipe: dict = {}
    if recipe_path.exists():
        with recipe_path.open("r", encoding="utf-8") as file:
            loaded_recipe = json.load(file)
        if not isinstance(loaded_recipe, dict):
            raise ValueError(f"Analysis recipe must contain an object: {recipe_path}")
        recipe = loaded_recipe

    source_experiment = str(recipe.get("source_experiment", ""))
    source_name = (
        Path(source_experiment).name if source_experiment else "experiment"
    )
    default_run_id = str(
        recipe.get(
            "source_run_id",
            source_name if source_experiment else analysis_directory.name,
        )
    )

    experimental_metadata = recipe.get("experimental_metadata", {})
    saved_label = ""
    if isinstance(experimental_metadata, dict):
        saved_label = str(experimental_metadata.get("run_label", "")).strip()
    run_label = label or saved_label or source_name

    return AnalysedRun(
        run_id=run_id or default_run_id,
        run_label=run_label,
        source_experiment=source_experiment,
        results=results,
        recipe=recipe,
        analysis_directory=analysis_directory,
    )


def excitation_scan_data(
    runs: AnalysedRun | Iterable[AnalysedRun],
    *,
    sample_angle_deg: float,
    x_field: str = "waveplate_angle_deg",
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    normalise: bool = False,
    angle_tolerance_deg: float = 1e-6,
    series_labels: Mapping[tuple[str, str], str] | None = None,
    allow_mismatched_windows: bool = False,
) -> FigureData:
    """Prepare harmonic signal versus an excitation coordinate.

    Replicates are deliberately preserved as separate records.  Requesting a
    calibrated coordinate whose values are missing raises an actionable error;
    this function never falls back to waveplate angle implicitly.
    """

    sample_angle_deg = float(sample_angle_deg)
    angle_tolerance_deg = _validated_tolerance(
        angle_tolerance_deg,
        "angle_tolerance_deg",
    )
    if not np.isfinite(sample_angle_deg):
        raise ValueError("Sample angle must be finite.")
    analysed_runs = _normalised_runs(runs)
    _validate_coordinate(x_field, excitation_only=True)
    _validate_signal(signal)
    requested_harmonics = _normalised_harmonics(harmonics)

    selected: list[tuple[AnalysedRun, HarmonicResult]] = []
    for run in analysed_runs:
        candidates = _harmonic_candidates(run, requested_harmonics)
        if not candidates:
            continue
        matches = [
            result
            for result in candidates
            if np.isclose(
                result.sample_angle_deg,
                sample_angle_deg,
                atol=angle_tolerance_deg,
                rtol=0.0,
            )
        ]
        if not matches:
            available = sorted({result.sample_angle_deg for result in candidates})
            raise ValueError(
                f"Run {run.run_label!r} has no sample angle matching "
                f"{sample_angle_deg}; available: {available}."
            )
        selected.extend((run, result) for result in matches)

    _validate_selection(selected, requested_harmonics)
    _validated_coordinate_values(selected, x_field)
    if not allow_mismatched_windows:
        _validate_harmonic_windows(selected)

    return _build_figure_data(
        selected,
        kind="excitation_scan",
        x_field=x_field,
        signal=signal,
        normalise=normalise,
        fixed_field="sample_angle_deg",
        fixed_value=float(sample_angle_deg),
        fixed_tolerance=angle_tolerance_deg,
        series_labels=series_labels,
    )


def rotation_scan_data(
    runs: AnalysedRun | Iterable[AnalysedRun],
    *,
    fixed_field: str = "waveplate_angle_deg",
    fixed_value: float,
    harmonics: Iterable[str] | None = None,
    signal: str = "integrated_signal",
    normalise: bool = False,
    value_tolerance: float = 1e-6,
    series_labels: Mapping[tuple[str, str], str] | None = None,
    allow_mismatched_windows: bool = False,
) -> FigureData:
    """Prepare sample-rotation data at a fixed excitation coordinate."""

    fixed_value = float(fixed_value)
    value_tolerance = _validated_tolerance(
        value_tolerance,
        "value_tolerance",
    )
    if not np.isfinite(fixed_value):
        raise ValueError("Fixed excitation value must be finite.")
    analysed_runs = _normalised_runs(runs)
    _validate_coordinate(fixed_field, excitation_only=True)
    _validate_signal(signal)
    requested_harmonics = _normalised_harmonics(harmonics)

    selected: list[tuple[AnalysedRun, HarmonicResult]] = []
    for run in analysed_runs:
        candidates = _harmonic_candidates(run, requested_harmonics)
        if not candidates:
            continue
        values = _validated_coordinate_values(
            [(run, result) for result in candidates],
            fixed_field,
        )
        matches = [
            result
            for result, value in zip(candidates, values, strict=True)
            if np.isclose(
                value,
                fixed_value,
                atol=value_tolerance,
                rtol=0.0,
            )
        ]
        if not matches:
            available = sorted(set(values))
            raise ValueError(
                f"Run {run.run_label!r} has no {fixed_field} matching "
                f"{fixed_value}; available: {available}."
            )
        selected.extend((run, result) for result in matches)

    _validate_selection(selected, requested_harmonics)
    if not allow_mismatched_windows:
        _validate_harmonic_windows(selected)

    return _build_figure_data(
        selected,
        kind="rotation_scan",
        x_field="sample_angle_deg",
        signal=signal,
        normalise=normalise,
        fixed_field=fixed_field,
        fixed_value=float(fixed_value),
        fixed_tolerance=value_tolerance,
        series_labels=series_labels,
    )


def save_figure_data_csv(data: FigureData, path: str | Path) -> Path:
    """Save the exact values represented by a ``FigureData`` object."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.as_dict() for record in data.records]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    return path


def coordinate_values(
    results: Iterable[HarmonicResult],
    field: str,
) -> list[float]:
    """Return sorted unique finite coordinate values or explain omissions."""

    _validate_coordinate(field, excitation_only=False)
    synthetic_run = AnalysedRun(
        run_id="coordinate-values",
        run_label="coordinate values",
        source_experiment="",
        results=tuple(results),
    )
    values = _validated_coordinate_values(
        [(synthetic_run, result) for result in synthetic_run.results],
        field,
    )
    return sorted(set(values))


def _normalised_runs(
    runs: AnalysedRun | Iterable[AnalysedRun],
) -> tuple[AnalysedRun, ...]:
    if isinstance(runs, AnalysedRun):
        normalised = (runs,)
    else:
        normalised = tuple(runs)
    if not normalised:
        raise ValueError("At least one analysed run is required.")
    if not all(isinstance(run, AnalysedRun) for run in normalised):
        raise TypeError("All runs must be AnalysedRun instances.")

    run_ids = [run.run_id for run in normalised]
    duplicates = sorted({run_id for run_id in run_ids if run_ids.count(run_id) > 1})
    if duplicates:
        raise ValueError(
            f"Analysed-run IDs must be unique before combining runs: {duplicates}."
        )
    return normalised


def _normalised_harmonics(
    harmonics: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if harmonics is None:
        return None
    names = tuple(str(name).strip() for name in harmonics)
    if not names or any(not name for name in names):
        raise ValueError("Requested harmonic names must not be empty.")
    if len(set(names)) != len(names):
        raise ValueError("Requested harmonic names must be unique.")
    return names


def _harmonic_candidates(
    run: AnalysedRun,
    harmonics: tuple[str, ...] | None,
) -> list[HarmonicResult]:
    if harmonics is None:
        return list(run.results)
    requested = set(harmonics)
    return [result for result in run.results if result.harmonic in requested]


def _validate_selection(
    selected: list[tuple[AnalysedRun, HarmonicResult]],
    requested_harmonics: tuple[str, ...] | None,
) -> None:
    if not selected:
        raise ValueError("No harmonic results match the requested figure selection.")
    if requested_harmonics is not None:
        available = {result.harmonic for _, result in selected}
        missing = sorted(set(requested_harmonics) - available)
        if missing:
            raise ValueError(
                f"Requested harmonics are absent from the selection: {missing}."
            )


def _validate_coordinate(field: str, *, excitation_only: bool) -> None:
    allowed = EXCITATION_FIELDS if excitation_only else tuple(_COORDINATE_SPECS)
    if field not in allowed:
        raise ValueError(f"Coordinate must be one of {sorted(allowed)}.")


def _validate_signal(signal: str) -> None:
    if signal not in SIGNAL_FIELDS:
        raise ValueError(f"Signal must be one of {sorted(SIGNAL_FIELDS)}.")


def _validated_tolerance(value: float, name: str) -> float:
    value = float(value)
    if not np.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return value


def _validated_coordinate_values(
    selected: list[tuple[AnalysedRun, HarmonicResult]],
    field: str,
) -> list[float]:
    missing: list[str] = []
    values: list[float] = []
    for run, result in selected:
        value = getattr(result, field)
        if value is None or not np.isfinite(value):
            missing.append(f"{run.run_id}/measurement-{result.measurement_number}")
        else:
            values.append(float(value))

    if missing:
        preview = ", ".join(missing[:5])
        suffix = " ..." if len(missing) > 5 else ""
        raise ValueError(
            f"Coordinate {field!r} is missing for {len(missing)} selected "
            f"result(s): {preview}{suffix}. Populate that calibrated field "
            "before requesting this axis; waveplate angle will not be used "
            "as an implicit substitute."
        )
    return values


def _validate_harmonic_windows(
    selected: list[tuple[AnalysedRun, HarmonicResult]],
) -> None:
    windows: dict[str, tuple[float, float]] = {}
    for run, result in selected:
        bounds = (result.wavelength_min_nm, result.wavelength_max_nm)
        existing = windows.setdefault(result.harmonic, bounds)
        if not np.allclose(existing, bounds, rtol=0.0, atol=1e-12):
            raise ValueError(
                f"Harmonic {result.harmonic!r} uses different wavelength "
                f"windows across selected runs ({existing} and {bounds} in "
                f"{run.run_label!r}). Use matching analysis windows or set "
                "allow_mismatched_windows=True explicitly."
            )


def _build_figure_data(
    selected: list[tuple[AnalysedRun, HarmonicResult]],
    *,
    kind: str,
    x_field: str,
    signal: str,
    normalise: bool,
    fixed_field: str,
    fixed_value: float,
    fixed_tolerance: float,
    series_labels: Mapping[tuple[str, str], str] | None,
) -> FigureData:
    x_label, x_unit = _COORDINATE_SPECS[x_field]
    _, fixed_unit = _COORDINATE_SPECS[fixed_field]
    y_label, y_unit = _SIGNAL_SPECS[signal]
    if normalise:
        plot_y_label = "Normalised harmonic signal"
        plot_y_unit = "relative"
        normalisation = "per_series_max_abs"
    else:
        plot_y_label = y_label
        plot_y_unit = y_unit
        normalisation = "none"

    groups: dict[tuple[str, str], list[tuple[AnalysedRun, HarmonicResult]]] = {}
    for run, result in selected:
        groups.setdefault((run.run_id, result.harmonic), []).append((run, result))

    multiple_runs = len({run.run_id for run, _ in selected}) > 1
    records: list[FigureRecord] = []
    for (run_id, harmonic), rows in groups.items():
        rows.sort(
            key=lambda item: (
                float(getattr(item[1], x_field)),
                item[1].measurement_number,
                item[1].measurement_timestamp,
            )
        )
        signal_values = np.asarray(
            [float(getattr(result, signal)) for _, result in rows],
            dtype=float,
        )
        if not np.all(np.isfinite(signal_values)):
            raise ValueError(
                f"Signal {signal!r} contains non-finite values in "
                f"{run_id!r}/{harmonic!r}."
            )
        factor = float(np.max(np.abs(signal_values))) if normalise else 1.0
        if normalise and factor == 0:
            raise ValueError(
                f"Cannot normalise zero signal for {run_id!r}/{harmonic!r}."
            )

        run = rows[0][0]
        key = (run_id, harmonic)
        if series_labels is not None and key in series_labels:
            series_label = str(series_labels[key])
        elif multiple_runs:
            series_label = f"{run.run_label} / {harmonic}"
        else:
            series_label = harmonic
        series_id = f"{run_id}::{harmonic}"
        source_analysis = (
            str(run.analysis_directory)
            if run.analysis_directory is not None
            else ""
        )

        for (row_run, result), signal_value in zip(
            rows,
            signal_values,
            strict=True,
        ):
            records.append(
                FigureRecord(
                    figure_kind=kind,
                    fixed_field=fixed_field,
                    fixed_value=fixed_value,
                    fixed_tolerance=fixed_tolerance,
                    fixed_unit=fixed_unit,
                    run_id=row_run.run_id,
                    run_label=row_run.run_label,
                    source_experiment=(
                        str(row_run.source_experiment)
                        if row_run.source_experiment is not None
                        else ""
                    ),
                    source_analysis=source_analysis,
                    series_id=series_id,
                    series_label=series_label,
                    plot_x_field=x_field,
                    plot_x_label=x_label,
                    plot_x_value=float(getattr(result, x_field)),
                    plot_x_unit=x_unit,
                    plot_y_field=signal,
                    signal_value=float(signal_value),
                    plot_y_value=float(signal_value / factor),
                    plot_y_unit=plot_y_unit,
                    normalisation=normalisation,
                    normalisation_factor=factor,
                    result=result,
                )
            )

    return FigureData(
        kind=kind,
        x_field=x_field,
        x_label=x_label,
        x_unit=x_unit,
        signal=signal,
        y_label=plot_y_label,
        y_unit=plot_y_unit,
        normalisation=normalisation,
        fixed_field=fixed_field,
        fixed_value=fixed_value,
        fixed_tolerance=fixed_tolerance,
        records=tuple(records),
    )
