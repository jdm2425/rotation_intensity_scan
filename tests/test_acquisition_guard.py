"""Hardware-free shutter-finally and sample-beam guard tests."""

from __future__ import annotations

from acquisition.acquisition import Acquisition


class Shutter:
    def __init__(self):
        self.state = "closed"
        self.events = []
        self.fail_open = False

    def open(self):
        self.events.append("open")
        self.state = "open"
        if self.fail_open:
            raise RuntimeError("partial open failure")

    def close(self):
        self.events.append("close")
        self.state = "closed"


class Spectrometer:
    serial = "FAKE"

    def __init__(self):
        self.calls = 0

    def acquire(self, *, averages):
        self.calls += 1
        return ("spectrum", averages)


def _raises(function):
    try:
        function()
    except RuntimeError:
        return
    raise AssertionError("Expected RuntimeError.")


def main() -> None:
    shutter = Shutter()
    spectrometer = Spectrometer()
    guard_calls = []
    acquisition = Acquisition(
        spectrometer=spectrometer,
        shutter=shutter,
        shutter_open_delay=0.0,
        before_open=lambda: guard_calls.append("guard"),
    )
    assert acquisition.acquire(averages=3) == ("spectrum", 3)
    assert guard_calls == ["guard"]
    assert shutter.events == ["open", "close"]
    assert shutter.state == "closed"

    shutter.events.clear()
    shutter.fail_open = True
    _raises(lambda: acquisition.acquire(averages=1))
    assert shutter.events == ["open", "close"]
    assert shutter.state == "closed"

    shutter.events.clear()
    guarded = Acquisition(
        spectrometer=spectrometer,
        shutter=shutter,
        before_open=lambda: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    _raises(lambda: guarded.acquire(averages=1))
    assert shutter.events == ["close"]
    assert shutter.state == "closed"

    print("ACQUISITION GUARD TEST PASSED")


if __name__ == "__main__":
    main()
