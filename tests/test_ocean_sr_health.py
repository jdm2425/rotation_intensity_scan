"""Hardware-free backend-selection and health tests for the Ocean driver."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hardware.devices.spectrometer.ocean_sr import OceanSR


@dataclass
class FakeDescriptor:
    serial_number: str


class FakeSpectrometer:
    def __init__(self, descriptor: FakeDescriptor) -> None:
        self.serial_number = descriptor.serial_number
        self.integration_time_us = 0
        self.closed = False

    def integration_time_micros(self, value: int) -> None:
        self.integration_time_us = int(value)

    def wavelengths(self) -> np.ndarray:
        return np.asarray([400.0, 500.0, 600.0])

    def intensities(self, **_kwargs) -> np.ndarray:
        return np.asarray([10.0, 20.0, 30.0])

    def close(self) -> None:
        self.closed = True


class BackendHarness:
    def __init__(self, serials: dict[str, list[str]]) -> None:
        self.serials = serials
        self.failures: dict[str, Exception] = {}
        self.loads: list[str] = []
        self.shutdowns: list[str] = []
        self.instances: list[FakeSpectrometer] = []

    def load(self, backend: str):
        self.loads.append(backend)
        if backend in self.failures:
            raise self.failures[backend]

        def list_devices() -> list[FakeDescriptor]:
            return [FakeDescriptor(serial) for serial in self.serials[backend]]

        def create(descriptor: FakeDescriptor) -> FakeSpectrometer:
            instance = FakeSpectrometer(descriptor)
            self.instances.append(instance)
            return instance

        def shutdown() -> None:
            self.shutdowns.append(backend)

        return create, list_devices, shutdown


def main() -> None:
    py_harness = BackendHarness({"pyseabreeze": ["FAKE-SR"]})
    spectrometer = OceanSR(
        serial="FAKE-SR",
        backend="pyseabreeze",
        seabreeze_loader=py_harness.load,
    )
    spectrometer.connect()
    assert spectrometer.connected
    assert spectrometer.active_backend == "pyseabreeze"
    assert spectrometer.info()["active_backend"] == "pyseabreeze"
    assert py_harness.instances[0].integration_time_us == 10_000
    spectrum = spectrometer.acquire(averages=2)
    assert np.array_equal(spectrum.wavelengths, [400.0, 500.0, 600.0])
    assert np.array_equal(spectrum.intensities, [10.0, 20.0, 30.0])
    assert spectrometer.check_connection() is True

    py_harness.serials["pyseabreeze"] = ["OTHER-SR"]
    try:
        spectrometer.check_connection()
    except RuntimeError as error:
        assert "no longer present on USB" in str(error)
        assert "OTHER-SR" in str(error)
    else:  # pragma: no cover
        raise AssertionError("A missing Ocean spectrometer was reported connected.")
    spectrometer.disconnect()
    assert py_harness.instances[0].closed
    assert py_harness.shutdowns == ["pyseabreeze"]

    native_harness = BackendHarness({"cseabreeze": ["NATIVE-SR"]})
    native = OceanSR(
        serial="NATIVE-SR",
        backend="seabreeze",
        seabreeze_loader=native_harness.load,
    )
    native.connect()
    assert native.backend == "cseabreeze"
    assert native.active_backend == "cseabreeze"
    assert native_harness.loads == ["cseabreeze"]
    native.disconnect()
    assert native_harness.shutdowns == ["cseabreeze"]

    auto_harness = BackendHarness(
        {
            "pyseabreeze": ["PY-ONLY"],
            "cseabreeze": ["AUTO-SR"],
        }
    )
    automatic = OceanSR(
        serial="AUTO-SR",
        backend="auto",
        seabreeze_loader=auto_harness.load,
    )
    automatic.connect()
    assert automatic.active_backend == "cseabreeze"
    assert auto_harness.loads == ["pyseabreeze", "cseabreeze"]
    assert auto_harness.shutdowns == ["pyseabreeze"]
    automatic.disconnect()
    assert auto_harness.shutdowns == ["pyseabreeze", "cseabreeze"]

    failed_harness = BackendHarness(
        {"pyseabreeze": [], "cseabreeze": ["FALLBACK-SR"]}
    )
    failed_harness.failures["pyseabreeze"] = RuntimeError("backend unavailable")
    fallback = OceanSR(
        serial="FALLBACK-SR",
        backend="auto",
        seabreeze_loader=failed_harness.load,
    )
    fallback.connect()
    assert fallback.active_backend == "cseabreeze"
    fallback.disconnect()

    disconnected = OceanSR(
        serial="FAKE-SR",
        seabreeze_loader=py_harness.load,
    )
    try:
        disconnected.check_connection()
    except RuntimeError as error:
        assert "not connected" in str(error)
    else:  # pragma: no cover
        raise AssertionError("A disconnected Ocean spectrometer passed its health check.")

    try:
        OceanSR(serial="FAKE-SR", backend="not-a-backend")
    except ValueError as error:
        assert "Unsupported SeaBreeze backend" in str(error)
    else:  # pragma: no cover
        raise AssertionError("An invalid SeaBreeze backend was accepted.")

    print("OCEAN SR BACKEND/HEALTH TEST PASSED")


if __name__ == "__main__":
    main()
