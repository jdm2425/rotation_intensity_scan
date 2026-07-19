"""Hardware-free end-to-end regression test for the analysis CLI."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")

import numpy as np

from analysis.measurement import Measurement
from data.data_writer import DataWriter
from hardware.devices.spectrometer.spectrum import Spectrum
from tools import analyse_experiment


SPECTROMETER_SERIAL = "SYNTHETIC-CLI-SPECTROMETER"
INTEGRATION_TIME_MS = 10.0
BACKGROUND_NAME = "pre_scan_dark"
RUN_LABEL = "Synthetic CLI Run"


def create_saved_experiment(output_root: Path) -> Path:
    """Create a complete format-v3 experiment using deterministic arrays."""

    wavelengths = np.arange(399.0, 406.0, dtype=float)
    background_counts = np.full(wavelengths.shape, 10.0)
    harmonic_shape = np.array([0.0, 1.0, 2.0, 1.0, 3.0, 1.0, 0.0])

    with DataWriter(
        output_directory=output_root,
        experiment_name="AnalysisCliSynthetic",
    ) as writer:
        writer.save_metadata(
            config={
                "synthetic": True,
                "sample_angles_deg": [0.0, 45.0],
                "waveplate_angles_deg": [0.0, 7.5],
            },
            hardware_info={
                "spectrometer": {
                    "serial": SPECTROMETER_SERIAL,
                }
            },
            extra_metadata={
                "experimental_metadata": {
                    "run_label": RUN_LABEL,
                    "notes": "Synthetic CLI regression data",
                    "filters": [
                        {
                            "name": "FBH400-40",
                            "manufacturer": "Thorlabs",
                            "part_number": "FBH400-40",
                            "intended_harmonics": ["H5"],
                        }
                    ],
                }
            },
        )

        writer.save_background(
            Spectrum(
                wavelengths=wavelengths.copy(),
                intensities=background_counts.copy(),
                integration_time_ms=INTEGRATION_TIME_MS,
                serial=SPECTROMETER_SERIAL,
                averages=5,
                dark_corrected=False,
                nonlinearity_corrected=False,
                timestamp=900.0,
            ),
            name=BACKGROUND_NAME,
            metadata={
                "kind": "shutter_closed_dark",
                "purpose": "analysis CLI regression",
            },
        )

        measurement_number = 0
        for sample_angle in (0.0, 45.0):
            for waveplate_angle in (0.0, 7.5):
                measurement_number += 1
                amplitude = (
                    1.0
                    + sample_angle / 45.0
                    + waveplate_angle / 7.5
                )
                spectrum = Spectrum(
                    wavelengths=wavelengths.copy(),
                    intensities=(
                        background_counts + amplitude * harmonic_shape
                    ),
                    integration_time_ms=INTEGRATION_TIME_MS,
                    serial=SPECTROMETER_SERIAL,
                    averages=3,
                    dark_corrected=False,
                    nonlinearity_corrected=False,
                    timestamp=1000.0 + measurement_number,
                )
                measurement = Measurement(
                    timestamp=2000.0 + measurement_number,
                    waveplate_angle_deg=waveplate_angle,
                    sample_angle_deg=sample_angle,
                    power_mw=1.0 + waveplate_angle / 7.5,
                    fluence_mj_cm2=0.1 + waveplate_angle / 75.0,
                    intensity_w_cm2=(1.0 + waveplate_angle / 7.5) * 1e8,
                    target_power_mw=1.05 + waveplate_angle / 7.5,
                    power_rms_mw=0.02 + measurement_number * 0.001,
                    power_measurement_duration_s=0.25,
                    spectrum=spectrum,
                    metadata={
                        "synthetic_measurement_number": measurement_number,
                    },
                )
                measurement.compute_statistics()
                writer.save_result(measurement)

        return writer.experiment_directory


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def assert_manifest_outputs(
    output_directory: Path,
    experiment_directory: Path,
    manifest: list[dict],
) -> None:
    """Verify every manifest record describes exact, reusable figure data."""

    required_csv_fields = {
        "run_id",
        "run_label",
        "source_experiment",
        "source_analysis",
        "series_id",
        "series_label",
        "plot_x_field",
        "plot_x_value",
        "plot_x_unit",
        "plot_y_field",
        "signal_value",
        "plot_y_value",
        "plot_y_unit",
        "normalisation",
        "normalisation_factor",
        "fixed_tolerance",
        "measurement_number",
        "measurement_timestamp",
        "harmonic",
        "sample_angle_deg",
        "waveplate_angle_deg",
        "power_mw",
        "target_power_mw",
        "power_rms_mw",
        "power_measurement_duration_s",
        "fluence_mj_cm2",
        "intensity_w_cm2",
        "integrated_signal",
        "raw_integrated_signal",
        "background_corrected_integral",
        "background_subtracted",
        "background_name",
        "transmission_corrected",
        "transmission_source",
        "transmission_fraction",
        "integration_time_ms",
        "averages",
        "spectrometer_serial",
        "saturated",
        "window_saturated",
    }

    assert len(manifest) == 6
    assert {
        entry["plot_type"] for entry in manifest
    } == {
        "excitation_cartesian",
        "rotation_cartesian",
        "rotation_polar",
    }

    for entry in manifest:
        assert entry["row_count"] == 4
        assert len(entry["series_ids"]) == 2
        assert entry["fixed_tolerance"] == 1e-6
        assert entry["correction_annotation"]
        assert "Background: pre_scan_dark" in entry["correction_annotation"]
        assert "Transmission: fraction 0.5" in entry["correction_annotation"]

        resolved_files: dict[str, Path] = {}
        for key, suffix in (
            ("png_file", ".png"),
            ("pdf_file", ".pdf"),
            ("data_file", ".csv"),
        ):
            relative_path = Path(entry[key])
            assert not relative_path.is_absolute()
            assert relative_path.suffix == suffix
            resolved = (output_directory / relative_path).resolve()
            resolved.relative_to(output_directory.resolve())
            assert resolved.exists()
            assert resolved.stat().st_size > 0
            resolved_files[key] = resolved

        fieldnames, rows = read_csv(resolved_files["data_file"])
        assert required_csv_fields.issubset(fieldnames)
        assert len(rows) == entry["row_count"]
        assert entry["data_sha256"] == hashlib.sha256(
            resolved_files["data_file"].read_bytes()
        ).hexdigest()

        for row in rows:
            assert row["run_id"] == experiment_directory.name
            assert row["run_label"] == RUN_LABEL
            assert Path(row["source_experiment"]) == (
                experiment_directory.resolve()
            )
            assert Path(row["source_analysis"]) == (
                output_directory.resolve()
            )
            assert row["series_id"] in entry["series_ids"]
            assert row["plot_x_field"] == entry["x_field"]
            assert row["plot_y_field"] == entry["signal"]
            assert row["normalisation"] == entry["normalisation"]
            assert float(row["normalisation_factor"]) == 1.0
            assert float(row["fixed_tolerance"]) == entry["fixed_tolerance"]

            # These equalities are the core publication-data invariant: the
            # saved plot coordinates and values are exactly reproducible from
            # the quantitative result columns in the same tidy row.
            assert float(row["plot_x_value"]) == float(
                row[row["plot_x_field"]]
            )
            assert float(row["signal_value"]) == float(
                row[row["plot_y_field"]]
            )
            assert float(row["plot_y_value"]) == float(row["signal_value"])

            assert row["background_subtracted"] == "True"
            assert row["background_name"] == BACKGROUND_NAME
            assert row["transmission_corrected"] == "True"
            assert row["transmission_source"] == "scalar"
            assert float(row["transmission_fraction"]) == 0.5
            assert row["spectrometer_serial"] == SPECTROMETER_SERIAL
            assert float(row["integration_time_ms"]) == INTEGRATION_TIME_MS
            assert int(row["averages"]) == 3
            assert row["target_power_mw"]
            assert row["power_rms_mw"]
            assert float(row["power_measurement_duration_s"]) == 0.25

            if entry["plot_type"].startswith("rotation"):
                assert row["plot_x_field"] == "sample_angle_deg"
                assert np.isclose(
                    float(row["plot_angle_rad"]),
                    np.deg2rad(float(row["sample_angle_deg"])),
                )


def run_compact_analysis(
    experiment_directory: Path,
    output_directory: Path,
    *extra_arguments: str,
) -> tuple[dict, list[dict[str, str]], str, str]:
    """Run a no-figure CLI case and return its durable reports."""

    arguments = [
        "analyse_experiment",
        str(experiment_directory),
        "--harmonic",
        "H5:400:402",
        *extra_arguments,
        "--output-directory",
        str(output_directory),
    ]
    console = io.StringIO()
    with patch.object(sys, "argv", arguments), redirect_stdout(console):
        analyse_experiment.main()

    with (output_directory / "analysis_recipe.json").open(
        "r",
        encoding="utf-8",
    ) as file:
        recipe = json.load(file)
    _, rows = read_csv(output_directory / "harmonic_signals.csv")
    summary = (output_directory / "analysis_summary.md").read_text(
        encoding="utf-8"
    )
    return recipe, rows, summary, console.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="analysis_cli_") as temporary:
        temporary_root = Path(temporary)
        experiment_directory = create_saved_experiment(
            temporary_root / "results"
        )
        output_directory = temporary_root / "analysis-output"

        arguments = [
            "analyse_experiment",
            str(experiment_directory),
            "--harmonic",
            "H5:400:402",
            "--harmonic",
            "H7:402:404",
            "--use-background",
            "--transmission-fraction",
            "0.5",
            "--plot-all",
            "--polar",
            "--annotate-corrections",
            "--output-directory",
            str(output_directory),
        ]
        console = io.StringIO()
        with patch.object(sys, "argv", arguments), redirect_stdout(console):
            analyse_experiment.main()

        signals_path = output_directory / "harmonic_signals.csv"
        recipe_path = output_directory / "analysis_recipe.json"
        assert signals_path.exists()
        assert recipe_path.exists()

        signal_fields, signal_rows = read_csv(signals_path)
        assert len(signal_rows) == 8
        assert {
            "background_subtracted",
            "background_name",
            "transmission_corrected",
            "transmission_source",
            "transmission_fraction",
            "measurement_timestamp",
            "power_mw",
            "target_power_mw",
            "power_rms_mw",
            "power_measurement_duration_s",
            "fluence_mj_cm2",
            "intensity_w_cm2",
        }.issubset(signal_fields)
        assert all(row["background_subtracted"] == "True" for row in signal_rows)
        assert all(row["transmission_corrected"] == "True" for row in signal_rows)

        with recipe_path.open("r", encoding="utf-8") as file:
            recipe = json.load(file)

        assert recipe["analysis_format_version"] == 2
        assert Path(recipe["source_experiment"]) == experiment_directory.resolve()
        assert recipe["background"]["mode"] == "used"
        assert recipe["background"]["applied"] is True
        assert recipe["background"]["name"] == BACKGROUND_NAME
        assert recipe["background"]["source_sha256"]
        assert recipe["transmission_correction"]["mode"] == "scalar_fraction"
        assert recipe["transmission_correction"]["applied"] is True
        assert recipe["transmission_correction"]["fraction"] == 0.5
        assert len(recipe["harmonics"]) == 2
        assert recipe["warnings"] == []
        assert recipe["annotate_corrections"] is True
        assert recipe["input_tolerance"] == 1e-6
        assert all(recipe["software"].get(name) for name in (
            "python",
            "numpy",
            "matplotlib",
        ))
        assert recipe["correction_pipeline"] == [
            {
                "order": 1,
                "name": "raw_detector_data",
                "mode": "source",
                "applied": True,
            },
            {
                "order": 2,
                "name": "saved_background_subtraction",
                "mode": "used",
                "applied": True,
            },
            {
                "order": 3,
                "name": "filter_transmission_correction",
                "mode": "scalar_fraction",
                "applied": True,
            },
            {
                "order": 4,
                "name": "harmonic_window_integration",
                "mode": "numpy.trapezoid",
                "applied": True,
            },
        ]
        assert recipe["quality_summary"]["measurement_count"] == 4
        assert recipe["quality_summary"]["harmonic_row_count"] == 8
        assert recipe["quality_summary"]["target_power_row_count"] == 8
        assert recipe["quality_summary"]["power_rms_row_count"] == 8
        assert recipe["quality_summary"]["power_duration_row_count"] == 8

        signals_hash = hashlib.sha256(signals_path.read_bytes()).hexdigest()
        assert recipe["checksums"] == {
            "algorithm": "sha256",
            "harmonic_signals.csv": signals_hash,
        }

        checksum_path = output_directory / "analysis_recipe.sha256"
        summary_path = output_directory / "analysis_summary.md"
        assert checksum_path.exists()
        assert summary_path.exists()
        recipe_hash, checksum_filename = checksum_path.read_text(
            encoding="utf-8"
        ).split()
        assert checksum_filename == "analysis_recipe.json"
        assert recipe_hash == hashlib.sha256(recipe_path.read_bytes()).hexdigest()

        summary = summary_path.read_text(encoding="utf-8")
        assert "# Harmonic analysis summary" in summary
        assert f"Analysis recipe SHA-256: `{recipe_hash}`" in summary
        assert "Background subtraction: USED - pre_scan_dark" in summary
        assert "Transmission correction: USED - scalar fraction 0.5" in summary
        assert "FBH400-40" in summary
        assert "Correction pipeline" in summary
        assert "Fixed-value absolute tolerance:" in summary
        assert "1e-06" in summary
        assert "Quick-look correction annotation: `True`" in summary
        assert "Python:" in summary and "NumPy:" in summary

        console_output = console.getvalue()
        assert "Background subtraction : USED - pre_scan_dark" in console_output
        assert "Transmission correction: USED - scalar fraction 0.5" in console_output
        assert "Fixed-value tolerance" in console_output
        assert "1e-06 deg" in console_output
        assert "Warnings: none" in console_output
        assert "Figure bundles:    6 (PNG/PDF/CSV)" in console_output

        manifest = recipe["figures"]
        assert_manifest_outputs(
            output_directory,
            experiment_directory,
            manifest,
        )

        decimal_entries = [
            entry
            for entry in manifest
            if entry["fixed_field"] == "waveplate_angle_deg"
            and np.isclose(entry["fixed_value"], 7.5)
        ]
        assert len(decimal_entries) == 2
        for entry in decimal_entries:
            assert "_7.5." in entry["png_file"]
            assert "_7.5." in entry["pdf_file"]
            assert "_7.5." in entry["data_file"]

        explicit_directory = temporary_root / "analysis-explicit-none"
        explicit, explicit_rows, explicit_summary, explicit_console = (
            run_compact_analysis(
                experiment_directory,
                explicit_directory,
                "--no-background",
                "--no-transmission-correction",
            )
        )
        assert explicit["background"]["mode"] == "explicitly_not_used"
        assert explicit["background"]["applied"] is False
        assert explicit["transmission_correction"]["mode"] == (
            "explicitly_not_used"
        )
        assert explicit["transmission_correction"]["applied"] is False
        assert explicit["warnings"] == []
        assert all(row["background_subtracted"] == "False" for row in explicit_rows)
        assert all(row["transmission_corrected"] == "False" for row in explicit_rows)
        assert "NOT USED (explicit choice)" in explicit_summary
        assert "NOT USED (explicit choice)" in explicit_console

        unspecified_directory = temporary_root / "analysis-unspecified"
        unspecified, unspecified_rows, unspecified_summary, unspecified_console = (
            run_compact_analysis(
                experiment_directory,
                unspecified_directory,
            )
        )
        assert unspecified["background"]["mode"] == "not_specified"
        assert unspecified["transmission_correction"]["mode"] == "not_specified"
        warning_codes = {warning["code"] for warning in unspecified["warnings"]}
        assert warning_codes == {
            "background_choice_unspecified",
            "installed_filter_without_transmission_choice",
        }
        assert all(
            row["background_subtracted"] == "False"
            for row in unspecified_rows
        )
        assert all(
            row["transmission_corrected"] == "False"
            for row in unspecified_rows
        )
        assert "background_choice_unspecified" in unspecified_summary
        assert (
            "installed_filter_without_transmission_choice"
            in unspecified_summary
        )
        assert "WARNING:" in unspecified_console

    print("ANALYSIS CLI TEST PASSED")


if __name__ == "__main__":
    main()
