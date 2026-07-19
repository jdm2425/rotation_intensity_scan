"""
test_round_trip.py

Verify that measurements can be saved and loaded again without
losing spectrum data or metadata.
"""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path

import numpy as np

from analysis.measurement import Measurement
from data.data_loader import load_experiment
from data.data_writer import DataWriter
from hardware.devices.spectrometer.spectrum import Spectrum


def create_fake_measurement(index: int) -> Measurement:
    """
    Create deterministic synthetic data for persistence testing.

    Fake data are used so this test does not require laboratory hardware.
    """

    wavelengths = np.linspace(
        200.0,
        900.0,
        2048,
    )

    intensities = (
        5000.0
        + index * 100.0
        + 1000.0 * np.sin(wavelengths / 20.0)
    )

    spectrum = Spectrum(
        wavelengths=wavelengths,
        intensities=intensities,
        integration_time_ms=10.0,
        serial="TEST-SPECTROMETER",
        averages=2,
        dark_corrected=False,
        nonlinearity_corrected=False,
    )

    measurement = Measurement(
        timestamp=float(index),
        waveplate_angle_deg=index * 5.0,
        sample_angle_deg=index * 10.0,
        power_mw=100.0 + index,
        fluence_mj_cm2=0.25,
        intensity_w_cm2=1.2e8,
        spectrum=spectrum,
        metadata={
            "analysis": {
                "integration_bounds_nm": [400.0, 500.0],
                "method": "sum",
            },
            "corrections": {
                "background_applied": False,
                "filter": None,
            },
        },
    )

    measurement.compute_statistics()

    return measurement


def main() -> None:

    print()
    print("=" * 60)
    print("Round-trip save/load test")
    print("=" * 60)

    temporary_root = Path(
        tempfile.mkdtemp(
            prefix="rotation_intensity_round_trip_"
        )
    )

    try:

        originals: list[Measurement] = []

        with DataWriter(
            output_directory=temporary_root,
            experiment_name="RoundTripTest",
        ) as writer:

            writer.save_metadata(
                config={
                    "test": True,
                    "waveplate_angles_deg": [0.0, 5.0, 10.0],
                },
                hardware_info={
                    "spectrometer": {
                        "serial": "TEST-SPECTROMETER",
                    }
                },
                extra_metadata={
                    "operator": "round-trip-test",
                },
            )

            for index in range(5):

                measurement = create_fake_measurement(index)

                originals.append(measurement)

                writer.save_result(measurement)

            experiment_directory = writer.experiment_directory

        print(f"Saved to: {experiment_directory}")

        dataset = load_experiment(
            experiment_directory
        )

        print(f"Loaded {len(dataset)} measurements.")

        assert len(dataset) == len(originals)

        assert dataset.metadata["format_version"] == 2
        assert dataset.metadata["operator"] == "round-trip-test"
        assert dataset.config["test"] is True
        assert dataset.config["waveplate_angles_deg"] == [
            0.0,
            5.0,
            10.0,
        ]
        assert (
            dataset.hardware["spectrometer"]["serial"]
            == "TEST-SPECTROMETER"
        )

        for index, (original, loaded) in enumerate(
            zip(originals, dataset.measurements),
            start=1,
        ):

            assert loaded.spectrum is not None

            assert np.allclose(
                original.spectrum.wavelengths,
                loaded.spectrum.wavelengths,
            )

            assert np.allclose(
                original.spectrum.intensities,
                loaded.spectrum.intensities,
            )

            assert (
                original.waveplate_angle_deg
                == loaded.waveplate_angle_deg
            )

            assert (
                original.sample_angle_deg
                == loaded.sample_angle_deg
            )

            assert (
                original.integration_time_ms
                == loaded.integration_time_ms
            )

            assert original.averages == loaded.averages

            assert (
                original.spectrum.serial
                == loaded.spectrum.serial
            )

            assert (
                original.spectrum.dark_corrected
                == loaded.spectrum.dark_corrected
            )

            assert (
                original.spectrum.nonlinearity_corrected
                == loaded.spectrum.nonlinearity_corrected
            )

            assert np.isclose(
                original.spectrum.timestamp,
                loaded.spectrum.timestamp,
            )

            assert np.isclose(
                original.timestamp,
                loaded.timestamp,
            )

            assert original.power_mw == loaded.power_mw
            assert original.fluence_mj_cm2 == loaded.fluence_mj_cm2
            assert original.intensity_w_cm2 == loaded.intensity_w_cm2
            assert original.saturated == loaded.saturated
            assert original.metadata == loaded.metadata

            assert np.isclose(
                original.peak_counts,
                loaded.peak_counts,
            )

            assert np.isclose(
                original.integrated_counts,
                loaded.integrated_counts,
            )

            spectrum_path = (
                experiment_directory
                / "spectra"
                / f"spectrum_{index:06d}.npz"
            )

            with np.load(
                spectrum_path,
                allow_pickle=False,
            ) as archive:
                assert all(
                    archive[key].dtype != object
                    for key in archive.files
                )

            print(f"Measurement {index}: OK")

        # Verify that datasets written before format version 2, which do
        # not have the measurement_metadata column, still load safely.
        measurements_path = (
            experiment_directory / "measurements.csv"
        )

        with measurements_path.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            legacy_rows = list(csv.DictReader(file))

        legacy_fields = [
            field
            for field in DataWriter.CSV_FIELDS
            if field != "measurement_metadata"
        ]

        with measurements_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=legacy_fields,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(legacy_rows)

        legacy_dataset = load_experiment(
            experiment_directory
        )

        assert all(
            measurement.metadata == {}
            for measurement in legacy_dataset
        )

        print("Legacy metadata-free CSV: OK")

        print()
        print("=" * 60)
        print("ROUND-TRIP TEST PASSED")
        print("=" * 60)

    finally:

        shutil.rmtree(
            temporary_root,
            ignore_errors=True,
        )


if __name__ == "__main__":
    main()
