"""Hardware-free persistence test for shared raw power-meter traces."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from analysis.measurement import Measurement
from data.data_loader import load_experiment
from data.data_writer import DataWriter
from data.power_measurement import PowerMeasurementAttempt
from hardware.devices.power_meter.models import PowerSample, PowerTrace
from hardware.devices.spectrometer.spectrum import Spectrum


def _spectrum(value: float) -> Spectrum:
    return Spectrum(
        wavelengths=np.asarray([399.0, 400.0, 401.0]),
        intensities=np.asarray([value, value + 1.0, value]),
        integration_time_ms=10.0,
        serial="FAKE-SPECTROMETER",
        averages=1,
    )


def _trace() -> PowerTrace:
    return PowerTrace(
        trace_id="trace-shared-by-intensity-block",
        requested_duration_s=10.0,
        elapsed_duration_s=10.1,
        started_at_unix_s=1234.5,
        device_serial="3144168",
        sensor_serial="3141552",
        measurement_mode="Power",
        wavelength_option="broadband",
        range_option="300mW",
        batch_sizes=(2, 1),
        samples=(
            PowerSample(
                batch_index=0,
                index_in_batch=0,
                raw_value=0.010,
                raw_timestamp=0.1,
                raw_status=0,
                power_w=0.010,
                timestamp_s=0.1,
                valid_for_statistics=True,
            ),
            PowerSample(
                batch_index=0,
                index_in_batch=1,
                raw_value=0.0,
                raw_timestamp=0.2,
                raw_status=0,
                power_w=0.0,
                timestamp_s=0.2,
                valid_for_statistics=False,
                invalid_reasons=("value_not_positive",),
            ),
            PowerSample(
                batch_index=1,
                index_in_batch=0,
                raw_value=None,
                raw_timestamp=0.3,
                raw_status=3,
                power_w=None,
                timestamp_s=0.3,
                valid_for_statistics=False,
                invalid_reasons=("value_missing", "status_missing"),
            ),
        ),
    )


def main() -> None:
    trace = _trace()
    statistics = trace.statistics

    with tempfile.TemporaryDirectory(prefix="power_trace_round_trip_") as tmp:
        with DataWriter(
            output_directory=Path(tmp),
            experiment_name="PowerTraceRoundTrip",
        ) as writer:
            writer.save_metadata(config={}, hardware_info={})
            attempt = PowerMeasurementAttempt(
                attempt_id="attempt-shared-by-intensity-block",
                attempted_at_unix_s=1234.4,
                waveplate_angle_deg=5.0,
                cadence="per_intensity",
                status="measured_with_invalid_samples",
                fundamental_wavelength_nm=2000.0,
                trace_id=trace.trace_id,
                error="One zero sample was retained and excluded.",
                maximum_allowed_power_mw=20.0,
            )
            writer.save_power_attempt(attempt, trace)
            for index, sample_angle in enumerate((0.0, 10.0), start=1):
                measurement = Measurement(
                    timestamp=2000.0 + index,
                    waveplate_angle_deg=5.0,
                    sample_angle_deg=sample_angle,
                    power_mw=statistics.arithmetic_mean_power_mw,
                    power_rms_mw=(
                        statistics.absolute_root_mean_square_power_mw
                    ),
                    power_std_mw=(
                        statistics.population_standard_deviation_mw
                    ),
                    power_measurement_duration_s=trace.elapsed_duration_s,
                    power_measurement_id=attempt.attempt_id,
                    power_trace_id=trace.trace_id,
                    power_measurement_status=(
                        "measured_with_invalid_samples"
                    ),
                    power_measurement_error=attempt.error,
                    power_valid_sample_count=statistics.valid_sample_count,
                    power_total_sample_count=statistics.total_sample_count,
                    power_trace=trace,
                    spectrum=_spectrum(float(index)),
                )
                measurement.compute_statistics()
                writer.save_result(measurement)

            assert writer.power_trace_count == 1
            root = writer.experiment_directory

        dataset = load_experiment(root)
        assert len(dataset.power_traces) == 1
        assert len(dataset.power_attempts) == 1
        loaded_trace = dataset.get_power_trace(trace.trace_id)
        assert loaded_trace.raw_values == (0.010, 0.0, None)
        assert loaded_trace.raw_statuses == (0, 0, 3)
        assert loaded_trace.statistics.valid_sample_count == 1
        assert loaded_trace.statistics.invalid_sample_count == 2
        assert loaded_trace.statistics.arithmetic_mean_power_mw == 10.0
        assert dataset[0].power_trace is loaded_trace
        assert dataset[1].power_trace is loaded_trace
        assert dataset[0].power_measurement_id == attempt.attempt_id
        assert dataset[0].power_measurement_id == dataset[1].power_measurement_id

        trace_path = root / "power_measurements" / "power_000001.npz"
        with np.load(trace_path, allow_pickle=False) as archive:
            assert all(archive[key].dtype != object for key in archive.files)

    print("POWER TRACE ROUND-TRIP TEST PASSED")


if __name__ == "__main__":
    main()
