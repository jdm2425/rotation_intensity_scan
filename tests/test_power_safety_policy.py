"""Hardware-free incident-power exposure-policy regression tests."""

from __future__ import annotations

import numpy as np

from experiments.experiment_config import PowerMeasurementConfig
from experiments.rotation_intensity_scan import (
    IncidentPowerLimitError,
    RotationIntensityExperiment,
)
from hardware.devices.power_meter.models import PowerSample, PowerTrace
from hardware.devices.spectrometer.spectrum import Spectrum
from hardware.power_probe import PowerProbeMeasurementError


class Stage:
    def __init__(self):
        self.position = 0.0

    def move_to(self, value):
        self.position = float(value)


class Probe:
    def __init__(self, trace_factory):
        self.trace_factory = trace_factory
        self.calls = 0

    def acquire_trace(self, *, duration_s, settle_time_s):
        self.calls += 1
        return self.trace_factory(self.calls, duration_s)


class Acquisition:
    def __init__(self):
        self.calls = 0

    def acquire(self, *, averages):
        self.calls += 1
        return Spectrum(
            wavelengths=np.asarray([399.0, 400.0, 401.0]),
            intensities=np.asarray([1.0, 2.0, 1.0]),
            integration_time_ms=10.0,
            serial="FAKE",
            averages=averages,
        )


class Hardware:
    def __init__(self, probe):
        self.waveplate = Stage()
        self.sample = Stage()
        self.power_probe = probe


def _sample(value_w, *, status=0, valid=True, reasons=()):
    return PowerSample(
        batch_index=0,
        index_in_batch=0,
        raw_value=value_w,
        raw_timestamp=0.1,
        raw_status=status,
        power_w=value_w,
        timestamp_s=0.1,
        valid_for_statistics=valid,
        invalid_reasons=tuple(reasons),
    )


def _trace(trace_id, samples, duration_s=10.0):
    return PowerTrace(
        trace_id=trace_id,
        samples=tuple(samples),
        batch_sizes=(len(samples),),
        requested_duration_s=duration_s,
        elapsed_duration_s=duration_s,
        started_at_unix_s=1.0,
    )


def _experiment(trace_factory, *, cadence="per_intensity", continue_unknown=False):
    probe = Probe(trace_factory)
    acquisition = Acquisition()
    experiment = RotationIntensityExperiment()
    experiment.hardware = Hardware(probe)
    experiment.acquisition = acquisition
    experiment.power_meter_config = PowerMeasurementConfig(
        enabled=True,
        cadence=cadence,
        wavelength_option="verified-band",
        continue_without_power_on_meter_error=continue_unknown,
        maximum_allowed_power_mw=20.0,
        pre_measurement_settle_s=0.0,
    )
    attempts = []
    experiment.power_attempt_callback = (
        lambda attempt, trace: attempts.append((attempt, trace))
    )
    return experiment, probe, acquisition, attempts


def _raises(exception_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except exception_type as error:
        return error
    raise AssertionError(f"Expected {exception_type.__name__}.")


def main() -> None:
    experiment, _, acquisition, attempts = _experiment(
        lambda call, duration: _trace(
            "over-limit",
            [_sample(0.025)],
            duration,
        )
    )
    _raises(
        IncidentPowerLimitError,
        experiment.prepare_intensity,
        waveplate_angle=1.0,
    )
    assert attempts[0][0].status == "over_limit"
    assert acquisition.calls == 0

    experiment, _, acquisition, attempts = _experiment(
        lambda call, duration: _trace(
            "overrange",
            [
                _sample(0.010),
                _sample(
                    0.015,
                    status=1,
                    valid=False,
                    reasons=("status_overrange",),
                ),
            ],
            duration,
        )
    )
    _raises(
        PowerProbeMeasurementError,
        experiment.prepare_intensity,
        waveplate_angle=1.0,
    )
    assert attempts[0][0].status == "unsafe_meter_status"
    assert acquisition.calls == 0

    zero_factory = lambda call, duration: _trace(
        f"zero-{call}",
        [
            _sample(
                0.0,
                valid=False,
                reasons=("value_not_positive",),
            )
        ],
        duration,
    )
    experiment, _, acquisition, attempts = _experiment(zero_factory)
    _raises(
        PowerProbeMeasurementError,
        experiment.prepare_intensity,
        waveplate_angle=1.0,
    )
    assert attempts[0][0].status == "invalid"
    assert acquisition.calls == 0

    experiment, _, acquisition, attempts = _experiment(
        zero_factory,
        continue_unknown=True,
    )
    experiment.prepare_intensity(waveplate_angle=1.0)
    measurement = experiment.measure(
        waveplate_angle=1.0,
        sample_angle=0.0,
    )
    assert measurement.power_mw is None
    assert measurement.power_measurement_status == "invalid"
    assert acquisition.calls == 1

    experiment, probe, acquisition, attempts = _experiment(
        lambda call, duration: _trace(
            f"per-measurement-{call}",
            [_sample(0.010)],
            duration,
        ),
        cadence="per_measurement",
    )
    experiment.prepare_intensity(waveplate_angle=1.0)
    experiment.measure(waveplate_angle=1.0, sample_angle=0.0)
    experiment.measure(waveplate_angle=1.0, sample_angle=10.0)
    assert probe.calls == 2
    assert acquisition.calls == 2
    assert len(attempts) == 2

    print("POWER SAFETY POLICY TEST PASSED")


if __name__ == "__main__":
    main()
