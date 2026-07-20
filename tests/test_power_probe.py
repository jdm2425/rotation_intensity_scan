"""Hardware-free safety-order tests for the retractable power probe."""

from __future__ import annotations

from hardware.power_probe import (
    PowerProbeConfigurationError,
    PowerProbeMeasurementError,
    PowerProbeSafetyError,
    RetractablePowerProbe,
)


class FakeShutter:
    def __init__(self, events: list[tuple]):
        self.events = events
        self.state = "open"
        self.fail_close = False

    @property
    def is_closed(self):
        return self.state == "closed"

    @property
    def is_open(self):
        return self.state == "open"

    def close(self):
        self.events.append(("shutter", "close"))
        if not self.fail_close:
            self.state = "closed"

    def open(self):
        self.events.append(("shutter", "open"))
        self.state = "open"


class FakeStage:
    def __init__(self, events: list[tuple]):
        self.events = events
        self.position_mm = 8.0

    def move_absolute_mm(self, value: float):
        if self.events[-1] != ("shutter", "close"):
            raise AssertionError("Stage moved without an immediately verified close.")
        self.position_mm = float(value)
        self.events.append(("stage", self.position_mm))


class FakeMeter:
    def __init__(self, events: list[tuple], trace=object()):
        self.events = events
        self.trace = trace
        self.error = None

    def acquire_trace(self, duration_s, *, poll_interval_s):
        self.events.append(("meter", duration_s, poll_interval_s))
        if self.error is not None:
            raise self.error
        return self.trace


def _probe(events):
    shutter = FakeShutter(events)
    stage = FakeStage(events)
    meter = FakeMeter(events)
    return (
        RetractablePowerProbe(
            shutter=shutter,
            insertion_stage=stage,
            power_meter=meter,
            in_position_mm=0.0,
            out_position_mm=8.0,
            position_tolerance_mm=0.01,
            sleep=lambda duration: events.append(("settle", duration)),
        ),
        shutter,
        stage,
        meter,
    )


def _raises(exception_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except exception_type as error:
        return error
    raise AssertionError(f"Expected {exception_type.__name__}.")


def test_one_shot_trace() -> None:
    events: list[tuple] = []
    probe, shutter, stage, meter = _probe(events)
    assert probe.acquire_trace(duration_s=10.0, settle_time_s=3.0) is meter.trace
    assert events == [
        ("shutter", "close"),
        ("stage", 0.0),
        ("shutter", "close"),
        ("shutter", "open"),
        ("settle", 3.0),
        ("meter", 10.0, 0.1),
        ("shutter", "close"),
        ("shutter", "close"),
        ("stage", 8.0),
    ]
    assert shutter.is_closed and stage.position_mm == 8.0 and probe.is_out
    probe.require_out()
    stage.position_mm = 0.0
    _raises(PowerProbeSafetyError, probe.require_out)
    stage.position_mm = 8.0


def test_persistent_session_inserts_and_retracts_once() -> None:
    events: list[tuple] = []
    probe, shutter, stage, meter = _probe(events)

    with probe.measurement_session() as session:
        assert session.active
        assert probe.is_in
        session.prepare_for_motion()
        assert session.acquire_trace(duration_s=1.0) is meter.trace
        session.prepare_for_motion()
        assert session.acquire_trace(
            duration_s=2.0,
            settle_time_s=0.5,
            poll_interval_s=0.2,
        ) is meter.trace
        assert probe.is_in
        assert shutter.is_closed

    assert not session.active
    assert probe.is_out
    assert shutter.is_closed
    assert events.count(("stage", 0.0)) == 1
    assert events.count(("stage", 8.0)) == 1
    assert events.count(("meter", 1.0, 0.1)) == 1
    assert events.count(("meter", 2.0, 0.2)) == 1
    assert events.count(("shutter", "open")) == 2


def test_measurement_failure_recovers_safe_state() -> None:
    events: list[tuple] = []
    probe, shutter, _, meter = _probe(events)
    meter.error = RuntimeError("meter offline")
    error = _raises(
        PowerProbeMeasurementError,
        probe.acquire_trace,
        duration_s=1.0,
    )
    assert "No power was inferred" in str(error)
    assert shutter.is_closed and probe.is_out

    events.clear()
    with _session_error_context(probe, PowerProbeMeasurementError):
        with probe.measurement_session() as session:
            session.acquire_trace(duration_s=1.0)
    assert shutter.is_closed and probe.is_out


def test_shutter_failure_prevents_motion() -> None:
    events: list[tuple] = []
    probe, shutter, _, _ = _probe(events)
    shutter.state = "open"
    shutter.fail_close = True
    _raises(PowerProbeSafetyError, probe.acquire_trace, duration_s=1.0)
    assert not any(event[0] == "stage" for event in events)


def test_unconfigured_positions_are_rejected() -> None:
    events: list[tuple] = []
    _, shutter, stage, meter = _probe(events)
    unconfigured = RetractablePowerProbe(
        shutter=shutter,
        insertion_stage=stage,
        power_meter=meter,
        in_position_mm=None,
        out_position_mm=None,
    )
    _raises(
        PowerProbeConfigurationError,
        unconfigured.acquire_trace,
        duration_s=1.0,
    )


class _session_error_context:
    def __init__(self, probe, expected):
        self.probe = probe
        self.expected = expected

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None or not issubclass(exc_type, self.expected):
            raise AssertionError(f"Expected {self.expected.__name__}.")
        return True


def main() -> None:
    test_one_shot_trace()
    test_persistent_session_inserts_and_retracts_once()
    test_measurement_failure_recovers_safe_state()
    test_shutter_failure_prevents_motion()
    test_unconfigured_positions_are_rejected()
    print("POWER PROBE TEST PASSED")


if __name__ == "__main__":
    main()
