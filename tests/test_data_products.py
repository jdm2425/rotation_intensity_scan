"""Hardware-free regression tests for reusable analysis data products."""

from __future__ import annotations

import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from analysis.data_products import (
    AnalysedRun,
    excitation_scan_data,
    load_analysed_run,
    rotation_scan_data,
    save_figure_data_csv,
)
from analysis.harmonic_analysis import HarmonicResult, save_results_csv
from plotting.harmonic_plots import plot_figure_data


def make_result(
    measurement_number: int,
    *,
    sample_angle_deg: float,
    waveplate_angle_deg: float,
    power_mw: float | None,
    integrated_signal: float,
    target_power_mw: float | None = None,
    power_rms_mw: float | None = None,
    power_measurement_duration_s: float | None = None,
    harmonic: str = "H5",
    wavelength_min_nm: float = 390.0,
    wavelength_max_nm: float = 410.0,
) -> HarmonicResult:
    """Construct one deterministic derived result without any hardware."""

    return HarmonicResult(
        measurement_number=measurement_number,
        harmonic=harmonic,
        wavelength_min_nm=wavelength_min_nm,
        wavelength_max_nm=wavelength_max_nm,
        sample_angle_deg=sample_angle_deg,
        waveplate_angle_deg=waveplate_angle_deg,
        power_mw=power_mw,
        target_power_mw=target_power_mw,
        power_rms_mw=power_rms_mw,
        power_measurement_duration_s=power_measurement_duration_s,
        integrated_signal=integrated_signal,
        raw_integrated_signal=integrated_signal + 10.0,
        background_corrected_integral=integrated_signal + 2.0,
        raw_peak_signal=integrated_signal + 20.0,
        peak_signal=integrated_signal + 5.0,
        peak_wavelength_nm=400.0,
        background_subtracted=True,
        background_name="pre_scan_dark",
        transmission_corrected=True,
        transmission_source="synthetic-filter.csv",
        saturated=False,
        window_saturated=False,
    )


def make_runs() -> tuple[AnalysedRun, AnalysedRun]:
    """Create two runs with identical coordinates and distinct signals."""

    run_a = AnalysedRun(
        run_id="run-a",
        run_label="Run A",
        source_experiment=Path("synthetic/run-a"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=0.0,
                power_mw=1.0,
                integrated_signal=2.0,
            ),
            make_result(
                2,
                sample_angle_deg=0.0,
                waveplate_angle_deg=10.0,
                power_mw=2.0,
                integrated_signal=4.0,
            ),
            make_result(
                3,
                sample_angle_deg=90.0,
                waveplate_angle_deg=10.0,
                power_mw=2.0,
                integrated_signal=6.0,
            ),
        ),
        recipe={"analysis": "synthetic-a"},
    )
    run_b = AnalysedRun(
        run_id="run-b",
        run_label="Run B",
        source_experiment=Path("synthetic/run-b"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=0.0,
                power_mw=1.0,
                integrated_signal=10.0,
            ),
            make_result(
                2,
                sample_angle_deg=0.0,
                waveplate_angle_deg=10.0,
                power_mw=2.0,
                integrated_signal=20.0,
            ),
            make_result(
                3,
                sample_angle_deg=90.0,
                waveplate_angle_deg=10.0,
                power_mw=2.0,
                integrated_signal=30.0,
            ),
        ),
        recipe={"analysis": "synthetic-b"},
    )
    return run_a, run_b


def records_by_series(data) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for record in data.records:
        grouped[record.series_id].append(record)
    return dict(grouped)


def series_containing(data, label_fragment: str) -> list:
    matches = [
        records
        for records in records_by_series(data).values()
        if label_fragment in records[0].series_label
    ]
    assert len(matches) == 1
    return matches[0]


def expect_value_error(function, *message_fragments: str) -> ValueError:
    try:
        function()
    except ValueError as error:
        message = str(error)
        for fragment in message_fragments:
            assert fragment.lower() in message.lower(), message
        return error
    raise AssertionError("Expected ValueError was not raised.")


def test_two_run_power_scan_and_normalisation() -> None:
    run_a, run_b = make_runs()

    data = excitation_scan_data(
        (run_a, run_b),
        sample_angle_deg=0.0,
        x_field="power_mw",
        harmonics=["H5"],
    )

    assert len(data.series_ids) == 2
    assert len(set(data.series_ids)) == 2
    assert set(records_by_series(data)) == set(data.series_ids)
    assert len(data.records) == 4

    records_a = series_containing(data, "Run A")
    records_b = series_containing(data, "Run B")

    assert [record.plot_x_value for record in records_a] == [1.0, 2.0]
    assert [record.signal_value for record in records_a] == [2.0, 4.0]
    assert [record.plot_y_value for record in records_a] == [2.0, 4.0]
    assert [record.plot_x_value for record in records_b] == [1.0, 2.0]
    assert [record.signal_value for record in records_b] == [10.0, 20.0]
    assert [record.plot_y_value for record in records_b] == [10.0, 20.0]

    assert all(record.result.power_mw == record.plot_x_value for record in data.records)
    assert all(
        record.plot_x_label == "Achieved input power"
        for record in data.records
    )
    assert all("H5" in record.series_label for record in data.records)

    figure, axes = plot_figure_data(data)
    assert len(axes.lines) == len(data.series_ids)
    for line, series_id in zip(axes.lines, data.series_ids, strict=True):
        records = data.records_for_series(series_id)
        assert np.allclose(
            line.get_xdata(),
            [record.plot_x_value for record in records],
        )
        assert np.allclose(
            line.get_ydata(),
            [record.plot_y_value for record in records],
        )
    plt.close(figure)

    normalised = excitation_scan_data(
        (run_a, run_b),
        sample_angle_deg=0.0,
        x_field="power_mw",
        harmonics=["H5"],
        normalise=True,
    )
    normalised_a = series_containing(normalised, "Run A")
    normalised_b = series_containing(normalised, "Run B")

    assert [record.signal_value for record in normalised_a] == [2.0, 4.0]
    assert [record.plot_y_value for record in normalised_a] == [0.5, 1.0]
    assert {record.normalisation_factor for record in normalised_a} == {4.0}
    assert [record.signal_value for record in normalised_b] == [10.0, 20.0]
    assert [record.plot_y_value for record in normalised_b] == [0.5, 1.0]
    assert {record.normalisation_factor for record in normalised_b} == {20.0}


def test_rotation_angles_remain_degrees() -> None:
    run_a, run_b = make_runs()

    data = rotation_scan_data(
        (run_a, run_b),
        fixed_field="power_mw",
        fixed_value=2.0,
        harmonics=["H5"],
    )

    assert len(data.series_ids) == 2
    assert len(data.records) == 4
    for records in records_by_series(data).values():
        assert [record.plot_x_value for record in records] == [0.0, 90.0]
        assert [
            record.result.sample_angle_deg for record in records
        ] == [0.0, 90.0]

    # Figure data retain measured angles in degrees. A polar renderer can
    # explicitly convert these values without changing the saved data.
    assert np.allclose(
        np.deg2rad(
            [
                record.plot_x_value
                for record in series_containing(data, "Run A")
            ]
        ),
        [0.0, np.pi / 2.0],
    )

    figure, axes = plot_figure_data(data, polar=True)
    for line, series_id in zip(axes.lines, data.series_ids, strict=True):
        records = data.records_for_series(series_id)
        assert np.allclose(
            line.get_xdata(),
            np.deg2rad([record.plot_x_value for record in records]),
        )
    plt.close(figure)


def test_achieved_power_tolerance_is_recorded() -> None:
    run = AnalysedRun(
        run_id="power-tolerance",
        run_label="Power tolerance",
        source_experiment=Path("synthetic/power-tolerance"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=5.0,
                target_power_mw=10.0,
                power_mw=9.6,
                power_rms_mw=0.15,
                power_measurement_duration_s=1.0,
                integrated_signal=2.0,
            ),
            make_result(
                2,
                sample_angle_deg=45.0,
                waveplate_angle_deg=5.0,
                target_power_mw=10.0,
                power_mw=10.4,
                power_rms_mw=0.20,
                power_measurement_duration_s=1.0,
                integrated_signal=3.0,
            ),
        ),
    )

    data = rotation_scan_data(
        run,
        fixed_field="power_mw",
        fixed_value=10.0,
        value_tolerance=0.5,
    )

    assert data.fixed_tolerance == 0.5
    assert [record.result.target_power_mw for record in data.records] == [
        10.0,
        10.0,
    ]
    assert [record.result.power_mw for record in data.records] == [9.6, 10.4]
    assert all(record.fixed_tolerance == 0.5 for record in data.records)
    assert all(record.fixed_unit == "mW" for record in data.records)

    figure, axes = plot_figure_data(data)
    assert "± 0.5 mW" in axes.get_title()
    plt.close(figure)

    expect_value_error(
        lambda: rotation_scan_data(
            run,
            fixed_field="power_mw",
            fixed_value=10.0,
            value_tolerance=0.1,
        ),
        "power_mw",
    )


def test_missing_power_is_actionable() -> None:
    missing_power = AnalysedRun(
        run_id="missing-power",
        run_label="Missing power",
        source_experiment=Path("synthetic/missing-power"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=5.0,
                power_mw=None,
                integrated_signal=1.0,
            ),
        ),
    )

    expect_value_error(
        lambda: excitation_scan_data(
            (missing_power,),
            sample_angle_deg=0.0,
            x_field="power_mw",
        ),
        "power_mw",
        "missing-power",
    )


def test_replicates_are_preserved() -> None:
    replicate_run = AnalysedRun(
        run_id="replicates",
        run_label="Replicates",
        source_experiment=Path("synthetic/replicates"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=0.0,
                power_mw=1.0,
                integrated_signal=2.0,
            ),
            make_result(
                2,
                sample_angle_deg=0.0,
                waveplate_angle_deg=0.0,
                power_mw=1.0,
                integrated_signal=3.0,
            ),
            make_result(
                3,
                sample_angle_deg=0.0,
                waveplate_angle_deg=10.0,
                power_mw=2.0,
                integrated_signal=4.0,
            ),
        ),
    )

    data = excitation_scan_data(
        (replicate_run,),
        sample_angle_deg=0.0,
        x_field="power_mw",
    )

    assert len(data.series_ids) == 1
    assert len(data.records) == 3
    assert [record.plot_x_value for record in data.records] == [1.0, 1.0, 2.0]
    assert [record.signal_value for record in data.records] == [2.0, 3.0, 4.0]
    assert [record.result.measurement_number for record in data.records] == [1, 2, 3]


def test_incompatible_same_name_windows_are_rejected() -> None:
    run_a, _ = make_runs()
    incompatible = AnalysedRun(
        run_id="different-window",
        run_label="Different window",
        source_experiment=Path("synthetic/different-window"),
        results=(
            make_result(
                1,
                sample_angle_deg=0.0,
                waveplate_angle_deg=0.0,
                power_mw=1.0,
                integrated_signal=8.0,
                harmonic="H5",
                wavelength_min_nm=391.0,
                wavelength_max_nm=409.0,
            ),
        ),
    )

    expect_value_error(
        lambda: excitation_scan_data(
            (run_a, incompatible),
            sample_angle_deg=0.0,
            harmonics=["H5"],
        ),
        "H5",
    )


def test_figure_csv_contains_exact_plot_rows() -> None:
    run_a, run_b = make_runs()
    data = excitation_scan_data(
        (run_a, run_b),
        sample_angle_deg=0.0,
        x_field="power_mw",
        harmonics=["H5"],
        normalise=True,
    )

    with tempfile.TemporaryDirectory(prefix="figure_data_") as temporary:
        path = Path(temporary) / "power_scan.csv"
        saved_path = save_figure_data_csv(data, path)
        assert Path(saved_path).exists()

        with path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            fieldnames = set(reader.fieldnames or [])

        required = set(data.records[0].result.as_dict()) | {
            "run_id",
            "run_label",
            "source_experiment",
            "series_id",
            "series_label",
            "plot_x_field",
            "plot_x_label",
            "plot_x_value",
            "plot_x_unit",
            "fixed_tolerance",
            "fixed_unit",
            "plot_y_field",
            "plot_y_value",
            "plot_y_unit",
            "normalisation",
            "normalisation_factor",
        }
        assert required.issubset(fieldnames)
        assert len(rows) == len(data.records)

        for row, record in zip(rows, data.records):
            assert row["series_id"] == record.series_id
            assert row["series_label"] == record.series_label
            assert row["plot_x_field"] == "power_mw"
            assert row["plot_y_field"] == "integrated_signal"
            assert float(row["fixed_tolerance"]) == record.fixed_tolerance
            assert float(row["plot_x_value"]) == record.plot_x_value
            assert float(row[row["plot_y_field"]]) == record.signal_value
            assert float(row["plot_y_value"]) == record.plot_y_value
            assert (
                float(row["normalisation_factor"])
                == record.normalisation_factor
            )
            assert int(row["measurement_number"]) == (
                record.result.measurement_number
            )
            assert row["harmonic"] == record.result.harmonic


def test_saved_analysis_run_loader() -> None:
    run_a, _ = make_runs()

    with tempfile.TemporaryDirectory(prefix="analysed_run_") as temporary:
        temporary_root = Path(temporary)
        analysis_directory = temporary_root / "harmonic_analysis"
        source_experiment = temporary_root / "source-run-a"
        analysis_directory.mkdir()
        source_experiment.mkdir()

        save_results_csv(
            run_a.results,
            analysis_directory / "harmonic_signals.csv",
        )
        recipe = {
            "source_experiment": str(source_experiment),
            "experimental_metadata": {
                "run_label": "Label from recipe",
            },
            "harmonics": [
                {
                    "name": "H5",
                    "wavelength_min_nm": 390.0,
                    "wavelength_max_nm": 410.0,
                }
            ],
        }
        with (analysis_directory / "analysis_recipe.json").open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(recipe, file, indent=4)

        loaded = load_analysed_run(
            analysis_directory,
            label="Publication Run A",
        )
        assert loaded.run_id == source_experiment.name
        assert loaded.run_label == "Publication Run A"
        assert loaded.source_experiment == source_experiment
        assert loaded.recipe == recipe
        assert len(loaded.results) == len(run_a.results)
        for original, restored in zip(run_a.results, loaded.results):
            assert restored.as_dict() == original.as_dict()

        default_label = load_analysed_run(analysis_directory)
        assert default_label.run_label == "Label from recipe"


def main() -> None:
    test_two_run_power_scan_and_normalisation()
    test_rotation_angles_remain_degrees()
    test_achieved_power_tolerance_is_recorded()
    test_missing_power_is_actionable()
    test_replicates_are_preserved()
    test_incompatible_same_name_windows_are_rejected()
    test_figure_csv_contains_exact_plot_rows()
    test_saved_analysis_run_loader()
    print("DATA PRODUCTS TEST PASSED")


if __name__ == "__main__":
    main()
