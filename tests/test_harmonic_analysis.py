"""Hardware-free regression tests for offline harmonic analysis."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np

from analysis.harmonic_analysis import (
    HarmonicWindow,
    TransmissionCurve,
    analyse_dataset,
    load_results_csv,
    save_results_csv,
)
from analysis.measurement import Measurement
from data.background_spectrum import BackgroundSpectrum
from data.experiment_dataset import ExperimentDataset
from hardware.devices.spectrometer.spectrum import Spectrum
from plotting.harmonic_plots import (
    plot_harmonics_vs_waveplate,
    plot_rotation_dependence,
)


def create_dataset() -> tuple[ExperimentDataset, BackgroundSpectrum]:
    wavelengths = np.array([400.0, 401.0, 402.0, 403.0, 404.0])
    measurements: list[Measurement] = []

    for sample_angle in (0.0, 90.0):
        for waveplate_angle in (0.0, 10.0):
            amplitude = 2.0 + sample_angle / 90.0 + waveplate_angle / 10.0
            intensities = np.array(
                [10.0, 10.0 + amplitude, 10.0, 10.0 + 2 * amplitude, 10.0]
            )
            spectrum = Spectrum(
                wavelengths=wavelengths.copy(),
                intensities=intensities,
                integration_time_ms=10.0,
                serial="SYNTHETIC",
                averages=2,
            )
            measurement = Measurement(
                timestamp=float(len(measurements)),
                waveplate_angle_deg=waveplate_angle,
                sample_angle_deg=sample_angle,
                power_mw=1.0 + waveplate_angle / 10.0,
                target_power_mw=1.1 + waveplate_angle / 10.0,
                power_rms_mw=0.02 + waveplate_angle / 1000.0,
                power_measurement_duration_s=0.5,
                fluence_mj_cm2=0.1 + waveplate_angle / 100.0,
                intensity_w_cm2=1.0e8 + waveplate_angle * 1.0e6,
                spectrum=spectrum,
            )
            measurement.compute_statistics()
            measurements.append(measurement)

    background = BackgroundSpectrum(
        name="pre_scan_dark",
        spectrum=Spectrum(
            wavelengths=wavelengths.copy(),
            intensities=np.full(wavelengths.shape, 10.0),
            integration_time_ms=10.0,
            serial="SYNTHETIC",
            averages=5,
        ),
        metadata={"kind": "shutter_closed_dark"},
    )

    dataset = ExperimentDataset(
        root=Path("synthetic"),
        experiment_name="Synthetic",
        created="",
        measurements=measurements,
        backgrounds=[background],
    )
    return dataset, background


def main() -> None:
    dataset, background = create_dataset()
    original = dataset[0].spectrum.intensities.copy()

    windows = [
        HarmonicWindow("H5", 400.0, 402.0),
        HarmonicWindow.from_center(
            "H7",
            center_nm=403.0,
            half_width_nm=1.0,
        ),
    ]

    results = analyse_dataset(
        dataset,
        windows,
        background=background,
    )

    assert len(results) == len(dataset) * len(windows)
    assert results[0].harmonic == "H5"
    assert np.isclose(results[0].integrated_signal, 2.0)
    assert np.isclose(results[1].integrated_signal, 4.0)
    assert np.isclose(results[0].raw_integrated_signal, 22.0)
    assert results[0].background_subtracted is True
    assert results[0].measurement_timestamp == dataset[0].timestamp
    assert results[0].power_mw == dataset[0].power_mw
    assert results[0].achieved_power_mw == results[0].power_mw
    assert results[0].target_power_mw == dataset[0].target_power_mw
    assert results[0].power_rms_mw == dataset[0].power_rms_mw
    assert (
        results[0].power_measurement_duration_s
        == dataset[0].power_measurement_duration_s
    )
    assert results[0].fluence_mj_cm2 == dataset[0].fluence_mj_cm2
    assert results[0].intensity_w_cm2 == dataset[0].intensity_w_cm2
    assert results[0].integration_time_ms == 10.0
    assert results[0].averages == 2
    assert results[0].spectrometer_serial == "SYNTHETIC"
    assert np.array_equal(dataset[0].spectrum.intensities, original)

    scalar_corrected = analyse_dataset(
        dataset,
        [windows[0]],
        background=background,
        transmission_fraction=0.5,
    )
    assert np.isclose(scalar_corrected[0].integrated_signal, 4.0)

    curve = TransmissionCurve(
        wavelengths_nm=np.array([399.0, 405.0]),
        transmission_fraction=np.array([0.5, 0.5]),
        source="synthetic-filter.csv",
    )
    curve_corrected = analyse_dataset(
        dataset,
        [windows[0]],
        background=background,
        transmission_curve=curve,
    )
    assert np.isclose(curve_corrected[0].integrated_signal, 4.0)
    assert curve_corrected[0].transmission_source == "synthetic-filter.csv"

    try:
        analyse_dataset(
            dataset,
            [windows[0]],
            transmission_fraction=1e-8,
        )
    except ValueError as error:
        assert "threshold" in str(error)
    else:
        raise AssertionError("Unsafe low-transmission correction was accepted.")

    mismatched_background = BackgroundSpectrum(
        name="wrong",
        spectrum=background.spectrum.copy(),
    )
    mismatched_background.spectrum.integration_time_ms = 20.0
    try:
        analyse_dataset(dataset, [windows[0]], background=mismatched_background)
    except ValueError as error:
        assert "integration time" in str(error)
    else:
        raise AssertionError("Mismatched background settings were accepted.")

    figure, _ = plot_harmonics_vs_waveplate(
        results,
        sample_angle_deg=0.0,
    )
    figure.canvas.draw()

    figure, _ = plot_rotation_dependence(
        results,
        waveplate_angle_deg=0.0,
        polar=True,
    )
    figure.canvas.draw()

    with tempfile.TemporaryDirectory(prefix="harmonic_analysis_") as temporary:
        path = save_results_csv(
            results,
            Path(temporary) / "harmonic_signals.csv",
        )
        assert path.exists()
        restored = load_results_csv(path)
        assert [result.as_dict() for result in restored] == [
            result.as_dict() for result in results
        ]

        with path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            legacy_rows = list(reader)
            legacy_fields = [
                field
                for field in (reader.fieldnames or [])
                if field
                not in {
                    "target_power_mw",
                    "power_rms_mw",
                    "power_measurement_duration_s",
                }
            ]

        legacy_path = Path(temporary) / "legacy_harmonic_signals.csv"
        with legacy_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=legacy_fields,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(legacy_rows)

        legacy_results = load_results_csv(legacy_path)
        assert all(result.target_power_mw is None for result in legacy_results)
        assert all(result.power_rms_mw is None for result in legacy_results)
        assert all(
            result.power_measurement_duration_s is None
            for result in legacy_results
        )
        assert [result.power_mw for result in legacy_results] == [
            result.power_mw for result in results
        ]

    print("HARMONIC ANALYSIS TEST PASSED")


if __name__ == "__main__":
    main()
