"""Hardware-free fake-COM tests for the Ophir Juno power-meter driver."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import math
import threading
from unittest.mock import patch

from hardware.devices.power_meter.models import PowerTrace
from hardware.devices.power_meter.ophir_juno import (
    DEFAULT_CONTROLLER_SERIAL,
    DEFAULT_SENSOR_SERIAL,
    OphirConfigurationError,
    OphirConnectionError,
    OphirDataError,
    OphirDependencyError,
    OphirIdentityError,
    OphirJunoPowerMeter,
    OphirThreadError,
    ophir_status_name,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = 100.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.current

    def sleep(self, duration: float) -> None:
        self.sleep_calls.append(duration)
        self.current += duration


class FakeOphirCom:
    """Small implementation of only the official COM calls used by the driver."""

    def __init__(self) -> None:
        self.scan_serials = [DEFAULT_CONTROLLER_SERIAL]
        self.controller_info = (
            "Juno",
            "1.53",
            DEFAULT_CONTROLLER_SERIAL,
        )
        self.sensor_exists = True
        self.sensor_info = (
            DEFAULT_SENSOR_SERIAL,
            "Thermopile",
            "3A-P-V1",
        )
        self.handle = 73
        self.mode_index = 0
        self.mode_options = ("Energy", "Power")
        self.wavelength_index = 0
        self.wavelength_options = ("1064nm", "2000nm")
        self.range_index = 0
        self.range_options = ("Auto", "50 mW", "500 mW")
        self.data_batches: list[object] = []
        self.failures: dict[str, BaseException] = {}
        self.calls: list[tuple[object, ...]] = []
        self.call_thread_ids: list[int] = []

    def _record(self, name: str, *args: object) -> None:
        self.calls.append((name, *args))
        self.call_thread_ids.append(threading.get_ident())
        failure = self.failures.get(name)
        if failure is not None:
            raise failure

    def ScanUSB(self):
        self._record("ScanUSB")
        return tuple(self.scan_serials)

    def OpenUSBDevice(self, serial: str):
        self._record("OpenUSBDevice", serial)
        return self.handle

    def Close(self, handle: object) -> None:
        self._record("Close", handle)

    def GetDeviceInfo(self, handle: object):
        self._record("GetDeviceInfo", handle)
        return self.controller_info

    def IsSensorExists(self, handle: object, channel: int):
        self._record("IsSensorExists", handle, channel)
        return self.sensor_exists

    def GetSensorInfo(self, handle: object, channel: int):
        self._record("GetSensorInfo", handle, channel)
        return self.sensor_info

    def GetMeasurementMode(self, handle: object, channel: int):
        self._record("GetMeasurementMode", handle, channel)
        return self.mode_index, self.mode_options

    def SetMeasurementMode(
        self,
        handle: object,
        channel: int,
        index: int,
    ) -> None:
        self._record("SetMeasurementMode", handle, channel, index)
        self.mode_index = index

    def GetWavelengths(self, handle: object, channel: int):
        self._record("GetWavelengths", handle, channel)
        return self.wavelength_index, self.wavelength_options

    def SetWavelength(
        self,
        handle: object,
        channel: int,
        index: int,
    ) -> None:
        self._record("SetWavelength", handle, channel, index)
        self.wavelength_index = index

    def GetRanges(self, handle: object, channel: int):
        self._record("GetRanges", handle, channel)
        return self.range_index, self.range_options

    def SetRange(
        self,
        handle: object,
        channel: int,
        index: int,
    ) -> None:
        self._record("SetRange", handle, channel, index)
        self.range_index = index

    def StartStream(self, handle: object, channel: int) -> None:
        self._record("StartStream", handle, channel)

    def StopStream(self, handle: object, channel: int) -> None:
        self._record("StopStream", handle, channel)

    def GetData(self, handle: object, channel: int):
        self._record("GetData", handle, channel)
        if self.data_batches:
            batch = self.data_batches.pop(0)
            if isinstance(batch, BaseException):
                raise batch
            return batch
        return (), (), ()


class FakeComRuntime:
    def __init__(self, com: FakeOphirCom) -> None:
        self.com = com
        self.events: list[tuple[str, int]] = []

    def initialize(self) -> None:
        self.events.append(("initialize", threading.get_ident()))

    def factory(self) -> FakeOphirCom:
        self.events.append(("factory", threading.get_ident()))
        return self.com

    def uninitialize(self) -> None:
        self.events.append(("uninitialize", threading.get_ident()))


def make_meter(
    com: FakeOphirCom,
    *,
    wavelength_name: str | None = "2000 nm",
    fixed_range_name: str | None = "50mw",
    clock: FakeClock | None = None,
) -> tuple[OphirJunoPowerMeter, FakeComRuntime]:
    runtime = FakeComRuntime(com)
    clock = clock or FakeClock()
    meter = OphirJunoPowerMeter(
        wavelength_name=wavelength_name,
        fixed_range_name=fixed_range_name,
        com_factory=runtime.factory,
        com_initialize=runtime.initialize,
        com_uninitialize=runtime.uninitialize,
        monotonic_clock=clock.monotonic,
        wall_clock=lambda: 1_721_380_000.0,
        sleep=clock.sleep,
        trace_id_factory=lambda: "trace-0001",
    )
    return meter, runtime


def assert_raises(exception_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except exception_type as error:
        return error
    raise AssertionError(f"Expected {exception_type.__name__} to be raised.")


def test_named_configuration_identity_and_idempotent_close() -> None:
    com = FakeOphirCom()
    meter, runtime = make_meter(com)
    owner_thread = threading.get_ident()

    meter.connect()
    meter.connect()

    assert meter.connected
    assert meter.identity.controller_serial == DEFAULT_CONTROLLER_SERIAL
    assert meter.identity.sensor_serial == DEFAULT_SENSOR_SERIAL
    assert meter.identity.sensor_name == "3A-P-V1"
    assert meter.configuration.measurement_mode.selected_name == "Power"
    assert meter.configuration.measurement_mode.selected_index == 1
    assert meter.configuration.wavelength.selected_name == "2000nm"
    assert meter.configuration.wavelength.selected_index == 1
    assert meter.configuration.power_range.selected_name == "50 mW"
    assert meter.configuration.power_range.selected_index == 1
    assert ("OpenUSBDevice", DEFAULT_CONTROLLER_SERIAL) in com.calls
    assert ("SetMeasurementMode", com.handle, 0, 1) in com.calls
    assert ("SetWavelength", com.handle, 0, 1) in com.calls
    assert ("SetRange", com.handle, 0, 1) in com.calls
    assert meter.info()["range_option"] == "50 mW"

    assert runtime.events[:2] == [
        ("initialize", owner_thread),
        ("factory", owner_thread),
    ]
    assert set(com.call_thread_ids) == {owner_thread}

    assert meter.check_connection() is True
    com.scan_serials = []
    error = assert_raises(OphirConnectionError, meter.check_connection)
    assert "no longer present on USB" in str(error)
    com.scan_serials = [DEFAULT_CONTROLLER_SERIAL]

    meter.close()
    meter.close()
    assert not meter.connected
    assert com.calls.count(("Close", com.handle)) == 1
    assert runtime.events[-1] == ("uninitialize", owner_thread)
    assert [name for name, _ in runtime.events].count("initialize") == 1
    assert [name for name, _ in runtime.events].count("uninitialize") == 1


def test_serial_and_sensor_validation_cleanup() -> None:
    missing = FakeOphirCom()
    missing.scan_serials = ["OTHER-CONTROLLER"]
    meter, runtime = make_meter(missing)
    error = assert_raises(OphirConnectionError, meter.connect)
    assert DEFAULT_CONTROLLER_SERIAL in str(error)
    assert not any(call[0] == "OpenUSBDevice" for call in missing.calls)
    assert [event[0] for event in runtime.events] == [
        "initialize",
        "factory",
        "uninitialize",
    ]
    assert not meter.connected

    wrong_controller = FakeOphirCom()
    wrong_controller.controller_info = ("Juno", "1.53", "WRONG")
    meter, runtime = make_meter(wrong_controller)
    error = assert_raises(OphirIdentityError, meter.connect)
    assert "expected '3144168'" in str(error)
    assert wrong_controller.calls.count(("Close", wrong_controller.handle)) == 1
    assert runtime.events[-1][0] == "uninitialize"

    missing_sensor = FakeOphirCom()
    missing_sensor.sensor_exists = False
    meter, _ = make_meter(missing_sensor)
    error = assert_raises(OphirIdentityError, meter.connect)
    assert "No Ophir sensor" in str(error)
    assert missing_sensor.calls.count(("Close", missing_sensor.handle)) == 1

    wrong_sensor = FakeOphirCom()
    wrong_sensor.sensor_info = ("WRONG", "Thermopile", "3A-P-V1")
    meter, _ = make_meter(wrong_sensor)
    error = assert_raises(OphirIdentityError, meter.connect)
    assert "expected '3141552'" in str(error)
    assert wrong_sensor.calls.count(("Close", wrong_sensor.handle)) == 1


def test_unavailable_named_option_is_actionable() -> None:
    com = FakeOphirCom()
    meter, runtime = make_meter(com, wavelength_name="2050nm")
    error = assert_raises(OphirConfigurationError, meter.connect)
    assert "2050nm" in str(error)
    assert "1064nm" in str(error)
    assert "2000nm" in str(error)
    assert com.calls.count(("Close", com.handle)) == 1
    assert runtime.events[-1][0] == "uninitialize"
    assert not meter.connected


def test_raw_invalid_values_are_retained_without_prediction() -> None:
    com = FakeOphirCom()
    com.data_batches = [
        (
            (0.010, 0.0, -0.002, None, float("nan"), 0.020, 0.030),
            (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, None),
            (0, 0, 0, 0, 0, 1, 0),
        )
    ]
    meter, _ = make_meter(com)
    meter.connect()
    meter.start_stream()
    samples = meter.read_batch()
    meter.stop_stream()

    assert len(samples) == 7
    assert samples[0].valid_for_statistics
    assert samples[0].power_mw == 10.0
    assert not samples[1].valid_for_statistics
    assert "value_not_positive" in samples[1].invalid_reasons
    assert samples[1].raw_value == 0.0
    assert samples[2].raw_value == -0.002
    assert samples[2].power_w == -0.002
    assert samples[3].raw_value is None
    assert samples[3].power_w is None
    assert math.isnan(samples[4].raw_value)
    assert math.isnan(samples[4].power_w)
    assert samples[5].raw_status == 1
    assert "status_overrange" in samples[5].invalid_reasons
    assert samples[6].raw_timestamp is None
    assert "timestamp_missing" in samples[6].invalid_reasons
    assert ophir_status_name(0) == "ok"
    assert ophir_status_name(1) == "overrange"
    assert ophir_status_name(999) == "unknown_999"

    trace = PowerTrace(
        samples=samples,
        batch_sizes=(7,),
        requested_duration_s=1.0,
        elapsed_duration_s=1.0,
        started_at_unix_s=1_721_380_000.0,
        trace_id="invalid-retention-test",
    )
    statistics = trace.statistics
    assert trace.raw_values[3] is None
    assert trace.raw_statuses == (0, 0, 0, 0, 0, 1, 0)
    assert statistics.total_sample_count == 7
    assert statistics.valid_sample_count == 1
    assert statistics.invalid_sample_count == 6
    assert statistics.arithmetic_mean_power_mw == 10.0
    assert statistics.population_standard_deviation_mw == 0.0
    assert statistics.absolute_root_mean_square_power_mw == 10.0

    assert_raises(FrozenInstanceError, setattr, samples[0], "power_w", 4.0)
    meter.close()

    all_invalid = PowerTrace(
        samples=samples[1:],
        batch_sizes=(6,),
        requested_duration_s=1.0,
        elapsed_duration_s=1.0,
        started_at_unix_s=1_721_380_000.0,
        trace_id="all-invalid-test",
    ).statistics
    assert all_invalid.valid_sample_count == 0
    assert all_invalid.arithmetic_mean_power_w is None
    assert all_invalid.population_standard_deviation_w is None
    assert all_invalid.absolute_root_mean_square_power_w is None
    assert all_invalid.minimum_power_w is None
    assert all_invalid.maximum_power_w is None


def test_trace_batches_statistics_and_stable_id() -> None:
    com = FakeOphirCom()
    com.data_batches = [
        ((0.010, 0.014), (10.0, 10.1), (0, 0)),
        ((), (), ()),
        ((0.018,), (10.2,), (0,)),
    ]
    clock = FakeClock()
    meter, _ = make_meter(com, clock=clock)
    meter.connect()

    trace = meter.acquire_trace(0.3, poll_interval_s=0.1)
    assert trace.trace_id == "trace-0001"
    assert trace.requested_duration_s == 0.3
    assert math.isclose(trace.elapsed_duration_s, 0.3)
    assert trace.batch_sizes == (2, 0, 1)
    assert trace.raw_values == (0.010, 0.014, 0.018)
    assert trace.raw_timestamps == (10.0, 10.1, 10.2)
    assert trace.raw_statuses == (0, 0, 0)
    assert [sample.batch_index for sample in trace.samples] == [0, 0, 2]
    assert trace.device_serial == DEFAULT_CONTROLLER_SERIAL
    assert trace.sensor_serial == DEFAULT_SENSOR_SERIAL
    assert trace.measurement_mode == "Power"
    assert trace.wavelength_option == "2000nm"
    assert trace.range_option == "50 mW"

    statistics = trace.statistics
    values = (0.010, 0.014, 0.018)
    expected_mean = sum(values) / len(values)
    expected_std = math.sqrt(
        sum((value - expected_mean) ** 2 for value in values) / len(values)
    )
    expected_rms = math.sqrt(
        sum(value * value for value in values) / len(values)
    )
    assert math.isclose(statistics.arithmetic_mean_power_w, expected_mean)
    assert math.isclose(
        statistics.population_standard_deviation_w,
        expected_std,
    )
    assert math.isclose(
        statistics.absolute_root_mean_square_power_w,
        expected_rms,
    )
    assert com.calls.count(("StartStream", com.handle, 0)) == 1
    assert com.calls.count(("StopStream", com.handle, 0)) == 1
    assert not meter.streaming
    meter.close()


def test_malformed_or_failed_data_stops_stream() -> None:
    mismatch = FakeOphirCom()
    mismatch.data_batches = [((0.01, 0.02), (1.0,), (0, 0))]
    clock = FakeClock()
    meter, _ = make_meter(mismatch, clock=clock)
    meter.connect()
    error = assert_raises(
        OphirDataError,
        meter.acquire_trace,
        0.1,
        poll_interval_s=0.1,
    )
    assert "mismatched batch lengths" in str(error)
    assert mismatch.calls.count(("StopStream", mismatch.handle, 0)) == 1
    assert not meter.streaming
    meter.close()

    failing = FakeOphirCom()
    failing.data_batches = [RuntimeError("synthetic read failure")]
    clock = FakeClock()
    meter, _ = make_meter(failing, clock=clock)
    meter.connect()
    error = assert_raises(
        OphirDataError,
        meter.acquire_trace,
        0.1,
        poll_interval_s=0.1,
    )
    assert "GetData failed" in str(error)
    assert failing.calls.count(("StopStream", failing.handle, 0)) == 1
    assert not meter.streaming
    meter.close()


def test_settings_cannot_change_while_streaming() -> None:
    com = FakeOphirCom()
    meter, _ = make_meter(com)
    meter.connect()
    meter.start_stream()
    error = assert_raises(
        OphirConfigurationError,
        meter.set_fixed_range,
        "500 mW",
    )
    assert "Stop the Ophir stream" in str(error)
    assert ("SetRange", com.handle, 0, 2) not in com.calls
    meter.stop_stream()

    selection = meter.set_fixed_range("500mw")
    assert selection.selected_name == "500 mW"
    assert ("SetRange", com.handle, 0, 2) in com.calls
    wavelength = meter.set_wavelength("1064 nm")
    assert wavelength.selected_name == "1064nm"
    meter.close()


def test_cross_thread_calls_are_rejected_before_com_use() -> None:
    com = FakeOphirCom()
    meter, _ = make_meter(com)
    meter.connect()
    call_count = len(com.calls)
    errors: list[BaseException] = []

    def use_from_worker() -> None:
        try:
            meter.start_stream()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=use_from_worker)
    worker.start()
    worker.join()

    assert len(errors) == 1
    assert isinstance(errors[0], OphirThreadError)
    assert len(com.calls) == call_count
    assert not meter.streaming
    meter.close()


def test_optional_dependency_is_loaded_only_on_real_connect() -> None:
    meter = OphirJunoPowerMeter()
    assert not meter.connected

    with patch(
        "hardware.devices.power_meter.ophir_juno.importlib.import_module",
        side_effect=ModuleNotFoundError("synthetic missing pywin32"),
    ):
        error = assert_raises(OphirDependencyError, meter.connect)

    assert "pywin32" in str(error)
    assert not meter.connected
    meter.close()


def main() -> None:
    test_named_configuration_identity_and_idempotent_close()
    test_serial_and_sensor_validation_cleanup()
    test_unavailable_named_option_is_actionable()
    test_raw_invalid_values_are_retained_without_prediction()
    test_trace_batches_statistics_and_stable_id()
    test_malformed_or_failed_data_stops_stream()
    test_settings_cannot_change_while_streaming()
    test_cross_thread_calls_are_rejected_before_com_use()
    test_optional_dependency_is_loaded_only_on_real_connect()
    print("OPHIR POWER METER TEST PASSED")


if __name__ == "__main__":
    main()
