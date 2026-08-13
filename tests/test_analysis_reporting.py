"""Hardware-free regressions for analysis reporting and plot annotations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from analysis.analysis_reporting import (
    BACKGROUND_EXPLICITLY_NOT_USED,
    BACKGROUND_NOT_SPECIFIED,
    BACKGROUND_USED,
    TRANSMISSION_EXPLICITLY_NOT_USED,
    TRANSMISSION_NOT_SPECIFIED,
    TRANSMISSION_SCALAR,
    build_analysis_warnings,
    build_quality_summary,
    correction_annotation,
    installed_filter_names,
    render_analysis_summary,
    render_console_summary,
)
from analysis.data_products import AnalysedRun, rotation_scan_data
from analysis.harmonic_analysis import HarmonicResult
from plotting.harmonic_plots import plot_figure_data
from tools.analyse_experiment import _automatic_input_values


def make_result(
    measurement_number: int,
    *,
    sample_angle_deg: float,
    power_mw: float = 2.04,
    integrated_signal: float = 4.0,
    target_power_mw: float | None = None,
) -> HarmonicResult:
    return HarmonicResult(
        measurement_number=measurement_number,
        harmonic="H5",
        wavelength_min_nm=390.0,
        wavelength_max_nm=410.0,
        sample_angle_deg=sample_angle_deg,
        waveplate_angle_deg=7.5,
        power_mw=power_mw,
        power_std_mw=0.03,
        target_power_mw=target_power_mw,
        integrated_signal=integrated_signal,
        raw_integrated_signal=integrated_signal + 10.0,
        background_corrected_integral=integrated_signal + 2.0,
        raw_peak_signal=integrated_signal + 20.0,
        peak_signal=integrated_signal + 5.0,
        peak_wavelength_nm=400.0,
        background_subtracted=True,
        background_name="pre_scan_dark",
        transmission_corrected=True,
        transmission_source="scalar",
        saturated=False,
        window_saturated=False,
        measurement_timestamp=1000.0 + measurement_number,
        integration_time_ms=10.0,
        averages=3,
        spectrometer_serial="SYNTHETIC",
        transmission_fraction=0.5,
    )


def reporting_recipe() -> dict:
    results = (
        make_result(1, sample_angle_deg=0.0, integrated_signal=4.0),
        make_result(2, sample_angle_deg=90.0, integrated_signal=8.0),
    )
    return {
        "analysis_format_version": 2,
        "analysis_id": "reporting-test",
        "created": "2026-07-19T10:00:00",
        "source_experiment": "synthetic/source-run",
        "source_run_id": "source-run",
        "experimental_metadata": {
            "run_label": "Reporting run",
            "sample_name": "Synthetic sample",
            "notes": "No hardware involved",
            "filters": [
                {
                    "name": "FBH400-40",
                    "part_number": "FBH400-40",
                }
            ],
        },
        "harmonics": [
            {
                "name": "H5",
                "wavelength_min_nm": 390.0,
                "wavelength_max_nm": 410.0,
            }
        ],
        "background": {
            "mode": BACKGROUND_USED,
            "applied": True,
            "name": "pre_scan_dark",
        },
        "transmission_correction": {
            "mode": TRANSMISSION_SCALAR,
            "applied": True,
            "fraction": 0.5,
            "source_file": None,
        },
        "plot_signal": "integrated_signal",
        "integration": "numpy.trapezoid",
        "input_coordinate": "power_mw",
        "input_tolerance": 0.05,
        "normalise_plots": False,
        "annotate_corrections": True,
        "correction_pipeline": [
            {
                "order": 1,
                "name": "raw_detector_data",
                "mode": "source",
                "applied": True,
            },
            {
                "order": 2,
                "name": "saved_background_subtraction",
                "mode": BACKGROUND_USED,
                "applied": True,
            },
            {
                "order": 3,
                "name": "filter_transmission_correction",
                "mode": TRANSMISSION_SCALAR,
                "applied": True,
            },
            {
                "order": 4,
                "name": "harmonic_window_integration",
                "mode": "numpy.trapezoid",
                "applied": True,
            },
        ],
        "quality_summary": build_quality_summary(results),
        "warnings": [],
        "figures": [
            {
                "plot_type": "rotation_cartesian",
                "fixed_field": "power_mw",
                "fixed_value": 2.0,
                "fixed_tolerance": 0.05,
                "row_count": 2,
                "data_file": "figures/rotation_power_mw_2.csv",
            }
        ],
        "software": {
            "python": "3.test",
            "numpy": "test",
            "matplotlib": "test",
        },
    }


def test_warning_modes_and_reporting_text() -> None:
    results = (make_result(1, sample_angle_deg=0.0),)
    metadata = {
        "filters": [
            {
                "name": "Thorlabs bandpass",
                "part_number": "FBH400-40",
            }
        ]
    }
    assert installed_filter_names(metadata) == [
        "Thorlabs bandpass (FBH400-40)"
    ]

    warnings = build_analysis_warnings(
        results=results,
        background_mode=BACKGROUND_NOT_SPECIFIED,
        available_backgrounds=["pre_scan_dark"],
        transmission_mode=TRANSMISSION_NOT_SPECIFIED,
        experimental_metadata=metadata,
    )
    assert {warning["code"] for warning in warnings} == {
        "background_choice_unspecified",
        "installed_filter_without_transmission_choice",
    }

    explicit_warnings = build_analysis_warnings(
        results=results,
        background_mode=BACKGROUND_EXPLICITLY_NOT_USED,
        available_backgrounds=["pre_scan_dark"],
        transmission_mode=TRANSMISSION_EXPLICITLY_NOT_USED,
        experimental_metadata=metadata,
    )
    assert explicit_warnings == []

    recipe = reporting_recipe()
    summary = render_analysis_summary(
        recipe,
        recipe_sha256="a" * 64,
    )
    assert "# Harmonic analysis summary" in summary
    assert "Background subtraction: USED - pre_scan_dark" in summary
    assert "Transmission correction: USED - scalar fraction 0.5" in summary
    assert "FBH400-40" in summary
    assert "Fixed-value absolute tolerance:" in summary
    assert "0.05" in summary
    assert "rotation_power_mw_2.csv" in summary
    assert f"Analysis recipe SHA-256: `{'a' * 64}`" in summary

    explicit_recipe = deepcopy(recipe)
    explicit_recipe["background"] = {
        "mode": BACKGROUND_EXPLICITLY_NOT_USED,
        "applied": False,
    }
    explicit_recipe["transmission_correction"] = {
        "mode": TRANSMISSION_EXPLICITLY_NOT_USED,
        "applied": False,
    }
    explicit_recipe["warnings"] = []
    console = render_console_summary(explicit_recipe)
    assert console.count("NOT USED (explicit choice)") == 2
    assert "Fixed-value tolerance" in console
    assert "0.05 mW" in console
    assert "Warnings: none" in console


def test_raw_annotation_and_fixed_tolerance_plot() -> None:
    recipe = reporting_recipe()
    raw_recipe = deepcopy(recipe)
    raw_recipe["plot_signal"] = "raw_integrated_signal"
    raw_annotation = correction_annotation(raw_recipe)
    assert "raw; corrections not applied" in raw_annotation
    assert "Background: pre_scan_dark" in raw_annotation
    assert "Transmission: fraction 0.5" in raw_annotation
    assert "selected corrections applied" not in raw_annotation

    final_annotation = correction_annotation(recipe)
    assert "selected corrections applied" in final_annotation

    run = AnalysedRun(
        run_id="reporting-run",
        run_label="Reporting run",
        source_experiment=Path("synthetic/reporting-run"),
        results=(
            make_result(1, sample_angle_deg=0.0, integrated_signal=4.0),
            make_result(2, sample_angle_deg=90.0, integrated_signal=8.0),
        ),
        recipe=recipe,
    )
    data = rotation_scan_data(
        run,
        fixed_field="power_mw",
        fixed_value=2.0,
        value_tolerance=0.05,
        signal="raw_integrated_signal",
    )
    assert data.fixed_tolerance == 0.05
    assert all(record.fixed_tolerance == 0.05 for record in data.records)
    assert all(record.fixed_unit == "mW" for record in data.records)
    assert all(record.as_dict()["fixed_tolerance"] == 0.05 for record in data.records)
    assert all(record.result.power_mw == 2.04 for record in data.records)

    figure, axes = plot_figure_data(data, annotation=raw_annotation)
    assert "2.0 ± 0.0 mW" in axes.get_title()
    assert "tolerance" in axes.get_title()
    assert "0.1 mW" in axes.get_title()
    assert len(figure.texts) == 1
    assert figure.texts[0].get_text() == raw_annotation
    plt.close(figure)

    figure, _ = plot_figure_data(data)
    assert figure.texts == []
    plt.close(figure)

    try:
        rotation_scan_data(
            run,
            fixed_field="power_mw",
            fixed_value=2.0,
            value_tolerance=0.01,
        )
    except ValueError as error:
        assert "power_mw" in str(error)
        assert "2.04" in str(error)
    else:
        raise AssertionError("An out-of-tolerance power point was selected.")


def test_automatic_power_centres_use_recorded_achieved_values() -> None:
    complete = (
        make_result(
            1,
            sample_angle_deg=0.0,
            power_mw=9.7,
            target_power_mw=10.0,
        ),
        make_result(
            2,
            sample_angle_deg=90.0,
            power_mw=10.3,
            target_power_mw=10.0,
        ),
    )
    values, source = _automatic_input_values(complete, "power_mw")
    assert values == [9.7, 10.3]
    assert source == "power_mw"

    partial = (
        complete[0],
        make_result(
            2,
            sample_angle_deg=90.0,
            power_mw=10.3,
            target_power_mw=None,
        ),
    )
    values, source = _automatic_input_values(partial, "power_mw")
    assert values == [9.7, 10.3]
    assert source == "power_mw"


def test_power_attempt_warnings_are_grouped_by_attempt() -> None:
    partial_h5 = replace(
        make_result(1, sample_angle_deg=0.0),
        power_measurement_id="attempt-partial",
        power_measurement_status="measured_with_invalid_samples",
    )
    partial_h7 = replace(partial_h5, harmonic="H7")
    failed_first_angle = replace(
        make_result(2, sample_angle_deg=0.0, power_mw=None),
        power_measurement_id="attempt-failed",
        power_measurement_status="failed",
        power_measurement_error="meter unavailable",
    )
    failed_second_angle = replace(
        failed_first_angle,
        measurement_number=3,
        sample_angle_deg=90.0,
    )
    rows = (
        partial_h5,
        partial_h7,
        failed_first_angle,
        failed_second_angle,
    )
    quality = build_quality_summary(rows)
    assert quality["partial_power_measurement_count"] == 1
    assert quality["failed_power_measurement_count"] == 1

    warnings = build_analysis_warnings(
        results=rows,
        background_mode=BACKGROUND_EXPLICITLY_NOT_USED,
        available_backgrounds=[],
        transmission_mode=TRANSMISSION_EXPLICITLY_NOT_USED,
        experimental_metadata={},
    )
    codes = {warning["code"] for warning in warnings}
    assert "partially_invalid_power_measurements" in codes
    assert "failed_power_measurements" in codes


def test_attempts_without_spectra_are_included_in_reporting() -> None:
    linked = replace(
        make_result(1, sample_angle_deg=0.0),
        power_measurement_id="attempt-linked",
        power_measurement_status="measured",
    )
    attempts = (
        {"attempt_id": "attempt-linked", "status": "measured"},
        {"attempt_id": "attempt-over-limit", "status": "over_limit"},
        {"attempt_id": "attempt-unsafe", "status": "unsafe_meter_status"},
        {"attempt_id": "attempt-failed", "status": "failed"},
    )

    quality = build_quality_summary((linked,), power_attempts=attempts)
    assert quality["power_attempt_count"] == 4
    assert quality["power_attempt_without_spectrum_count"] == 3
    assert quality["over_limit_power_measurement_count"] == 1
    assert quality["unsafe_status_power_measurement_count"] == 1
    assert quality["failed_power_measurement_count"] == 1

    warnings = build_analysis_warnings(
        results=(linked,),
        background_mode=BACKGROUND_EXPLICITLY_NOT_USED,
        available_backgrounds=[],
        transmission_mode=TRANSMISSION_EXPLICITLY_NOT_USED,
        experimental_metadata={},
        power_attempts=attempts,
    )
    codes = {warning["code"] for warning in warnings}
    assert "incident_power_over_limit" in codes
    assert "unsafe_power_meter_status" in codes
    assert "failed_power_measurements" in codes
    assert "power_attempts_without_spectra" in codes


def main() -> None:
    test_warning_modes_and_reporting_text()
    test_raw_annotation_and_fixed_tolerance_plot()
    test_automatic_power_centres_use_recorded_achieved_values()
    test_power_attempt_warnings_are_grouped_by_attempt()
    test_attempts_without_spectra_are_included_in_reporting()
    print("ANALYSIS REPORTING TEST PASSED")


if __name__ == "__main__":
    main()
