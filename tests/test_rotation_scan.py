"""Hardware-free check of an intensity-major rotation scan sequence."""

from __future__ import annotations

from experiments.scan_runner import ScanRunner


class FakeMonitor:
    def __init__(self) -> None:
        self.started: list[tuple[float, float]] = []

    def measurement_started(
        self,
        *,
        sample_angle: float,
        waveplate_angle: float,
    ) -> None:
        self.started.append((waveplate_angle, sample_angle))


class FakeExperiment:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def scan_started(self) -> None:
        self.events.append(("scan_started",))

    def prepare_intensity(self, *, waveplate_angle: float) -> None:
        self.events.append(("prepare_intensity", waveplate_angle))

    def measure(
        self,
        *,
        waveplate_angle: float,
        sample_angle: float,
        replicate_index: int = 1,
        replicate_count: int = 1,
    ) -> tuple:
        result = (waveplate_angle, sample_angle)
        self.events.append(("measure", *result))
        return result


def main() -> None:
    experiment = FakeExperiment()
    monitor = FakeMonitor()
    results = list(
        ScanRunner(experiment=experiment, monitor=monitor).run(
            waveplate_angles=[0.0, 5.0],
            sample_angles=[0.0, 10.0, 20.0],
        )
    )

    expected = [
        (0.0, 0.0),
        (0.0, 10.0),
        (0.0, 20.0),
        (5.0, 0.0),
        (5.0, 10.0),
        (5.0, 20.0),
    ]
    assert results == expected
    assert monitor.started == expected
    assert [event for event in experiment.events if event[0] == "prepare_intensity"] == [
        ("prepare_intensity", 0.0),
        ("prepare_intensity", 5.0),
    ]

    repeated = list(
        ScanRunner(experiment=FakeExperiment(), monitor=FakeMonitor()).run(
            waveplate_angles=[2.0],
            sample_angles=[3.0],
            spectra_per_point=3,
        )
    )
    assert repeated == [(2.0, 3.0)] * 3
    print("ROTATION SCAN ORDER TEST PASSED")


if __name__ == "__main__":
    main()
