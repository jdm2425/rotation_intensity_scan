"""Reusable Ophir Juno USB power-meter driver.

The driver uses Ophir's installed ``OphirLMMeasurement`` COM server through
pywin32.  pywin32 is imported lazily only when a real connection is requested,
so importing this module and running fake-device tests has no hardware or COM
side effects.

Ophir COM objects are apartment-threaded.  Connection, configuration,
streaming, data retrieval, and cleanup must therefore all occur on the thread
which called :meth:`connect`.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import math
import threading
import time
from typing import Callable
from uuid import uuid4

from hardware.devices.base import HardwareDevice, HardwareError
from hardware.devices.power_meter.models import PowerSample, PowerTrace

logger = logging.getLogger(__name__)


OPHIR_COM_PROG_ID = "OphirLMMeasurement.CoLMMeasurement"
DEFAULT_CONTROLLER_SERIAL = "3144168"
DEFAULT_SENSOR_SERIAL = "3141552"
DEFAULT_CHANNEL = 0
POWER_MODE_NAME = "Power"


# Names are taken from the Status enum shipped with StarLab 3.80.  Unknown
# numeric statuses remain available verbatim on PowerSample.raw_status.
OPHIR_STATUS_NAMES = {
    0: "ok",
    1: "overrange",
    2: "way_overrange",
    3: "missing",
    4: "energy_reset",
    5: "energy_waiting",
    6: "energy_summing",
    7: "energy_timeout",
    8: "energy_peak_over",
    9: "energy_over",
    0x010000: "x_ok",
    0x010001: "x_error",
    0x020000: "y_ok",
    0x020001: "y_error",
    0x030000: "size_ok",
    0x030001: "size_error",
    0x030002: "accuracy_warning",
    0x040001: "setting_changed",
    0x050000: "frequency",
    0x100000: "temperature",
    0x200000: "alert_hot",
    0x300000: "pulse_width",
    0x400000: "pfp_energy",
}


class OphirPowerMeterError(HardwareError):
    """Base exception for the Ophir power-meter driver."""


class OphirDependencyError(OphirPowerMeterError):
    """Raised when the optional Windows COM dependency is unavailable."""


class OphirConnectionError(OphirPowerMeterError):
    """Raised when the controller cannot be discovered or opened."""


class OphirIdentityError(OphirPowerMeterError):
    """Raised when connected hardware does not match configured serials."""


class OphirConfigurationError(OphirPowerMeterError):
    """Raised when a requested returned option cannot be selected."""


class OphirDataError(OphirPowerMeterError):
    """Raised for malformed or failed streamed data retrieval."""


class OphirThreadError(OphirPowerMeterError):
    """Raised before an Ophir COM object would be used on another thread."""


@dataclass(frozen=True, slots=True)
class OphirDeviceIdentity:
    """Identity returned by the Juno controller and attached sensor."""

    controller_name: str
    controller_rom_version: str
    controller_serial: str
    sensor_serial: str
    sensor_type: str
    sensor_name: str
    channel: int


@dataclass(frozen=True, slots=True)
class OphirOptionSelection:
    """One selected setting and the option names returned by the meter."""

    selected_index: int
    selected_name: str
    available_options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OphirConfiguration:
    """Verified meter settings after device readback."""

    measurement_mode: OphirOptionSelection
    wavelength: OphirOptionSelection
    power_range: OphirOptionSelection


def ophir_status_name(raw_status: object) -> str:
    """Return a descriptive name without modifying the raw status value."""

    try:
        numeric = int(raw_status)
    except (TypeError, ValueError, OverflowError):
        return "unknown"

    try:
        exactly_integral = bool(raw_status == numeric)
    except Exception:
        exactly_integral = False
    if not exactly_integral:
        return "unknown"
    return OPHIR_STATUS_NAMES.get(numeric, f"unknown_{numeric}")


def _default_com_initialize() -> None:
    try:
        pythoncom = importlib.import_module("pythoncom")
    except (ImportError, OSError) as exc:
        raise OphirDependencyError(
            "Ophir Juno control requires the optional 'pywin32' package and "
            "the OphirLMMeasurement COM server installed with StarLab."
        ) from exc
    pythoncom.CoInitialize()


def _default_com_uninitialize() -> None:
    pythoncom = importlib.import_module("pythoncom")
    pythoncom.CoUninitialize()


def _default_com_factory() -> object:
    try:
        win32_client = importlib.import_module("win32com.client")
    except (ImportError, OSError) as exc:
        raise OphirDependencyError(
            "Ophir Juno control requires the optional 'pywin32' package and "
            "the OphirLMMeasurement COM server installed with StarLab."
        ) from exc

    try:
        return win32_client.Dispatch(OPHIR_COM_PROG_ID)
    except Exception as exc:
        raise OphirConnectionError(
            "Could not create OphirLMMeasurement COM object. Close StarLab, "
            "confirm its COM component is installed, and try again."
        ) from exc


def _no_op() -> None:
    return None


def _option_key(option: str) -> str:
    return "".join(str(option).split()).casefold()


def _as_sequence(value: object, *, description: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise OphirDataError(
            f"Ophir returned a non-sequence for {description}: {value!r}."
        ) from exc


def _parse_finite_number(
    raw_value: object,
    *,
    field: str,
) -> tuple[float | None, str | None]:
    if raw_value is None:
        return None, f"{field}_missing"
    if isinstance(raw_value, bool):
        return None, f"{field}_not_numeric"
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError, OverflowError):
        return None, f"{field}_not_numeric"
    if not math.isfinite(parsed):
        return parsed, f"{field}_not_finite"
    return parsed, None


class OphirJunoPowerMeter(HardwareDevice):
    """Ophir Juno controller with one USB-connected power sensor.

    Parameters named ``*_name`` are matched against strings returned by the
    device.  Their numeric list indices are discovered at runtime and never
    hardcoded.  If wavelength or range is ``None``, the current returned option
    is retained and recorded.

    A custom ``com_factory`` makes the class fully testable without pywin32 or
    hardware.  Optional initialize/uninitialize callbacks must be supplied as
    a pair when a custom COM runtime needs them.
    """

    def __init__(
        self,
        *,
        controller_serial: str = DEFAULT_CONTROLLER_SERIAL,
        sensor_serial: str = DEFAULT_SENSOR_SERIAL,
        channel: int = DEFAULT_CHANNEL,
        wavelength_name: str | None = None,
        fixed_range_name: str | None = None,
        name: str = "Ophir Juno power meter",
        com_factory: Callable[[], object] | None = None,
        com_initialize: Callable[[], None] | None = None,
        com_uninitialize: Callable[[], None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        trace_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        super().__init__(name=name)

        if not str(controller_serial).strip():
            raise ValueError("controller_serial cannot be empty.")
        if not str(sensor_serial).strip():
            raise ValueError("sensor_serial cannot be empty.")
        if int(channel) < 0:
            raise ValueError("channel must be non-negative.")
        if wavelength_name is not None and not str(wavelength_name).strip():
            raise ValueError("wavelength_name cannot be empty.")
        if fixed_range_name is not None and not str(fixed_range_name).strip():
            raise ValueError("fixed_range_name cannot be empty.")
        if (com_initialize is None) != (com_uninitialize is None):
            raise ValueError(
                "com_initialize and com_uninitialize must be supplied together."
            )

        self.controller_serial = str(controller_serial).strip()
        self.sensor_serial = str(sensor_serial).strip()
        self.channel = int(channel)
        self.wavelength_name = (
            None if wavelength_name is None else str(wavelength_name).strip()
        )
        self.fixed_range_name = (
            None
            if fixed_range_name is None
            else str(fixed_range_name).strip()
        )

        if com_factory is None:
            self._com_factory = _default_com_factory
            self._com_initialize = com_initialize or _default_com_initialize
            self._com_uninitialize = (
                com_uninitialize or _default_com_uninitialize
            )
        else:
            self._com_factory = com_factory
            self._com_initialize = com_initialize or _no_op
            self._com_uninitialize = com_uninitialize or _no_op

        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._trace_id_factory = trace_id_factory

        self._com: object | None = None
        self._handle: object | None = None
        self._owner_thread_id: int | None = None
        self._com_initialized = False
        self._streaming = False
        self._next_batch_index = 0
        self._identity: OphirDeviceIdentity | None = None
        self._configuration: OphirConfiguration | None = None

    # ------------------------------------------------------------------
    # Connection and COM ownership
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self.connected:
            self._require_owner_thread()
            return

        self._owner_thread_id = threading.get_ident()
        try:
            self._com_initialize()
            self._com_initialized = True
            self._com = self._com_factory()

            scanned_serials = tuple(
                str(serial).strip()
                for serial in _as_sequence(
                    self._invoke("ScanUSB"),
                    description="ScanUSB serial numbers",
                )
            )
            if self.controller_serial not in scanned_serials:
                found = ", ".join(scanned_serials) or "none"
                raise OphirConnectionError(
                    f"Configured Ophir controller {self.controller_serial!r} "
                    f"was not found by ScanUSB (found: {found})."
                )

            self._handle = self._invoke(
                "OpenUSBDevice",
                self.controller_serial,
            )
            if self._handle is None:
                raise OphirConnectionError(
                    "OpenUSBDevice returned no handle for controller "
                    f"{self.controller_serial!r}."
                )

            self._identity = self._read_and_validate_identity()
            self._configuration = self._configure_for_power()
            self._set_connected(True)
            logger.info(
                "%s connected: controller %s, sensor %s",
                self.name,
                self.controller_serial,
                self.sensor_serial,
            )
        except BaseException as exc:
            self._cleanup_failed_connect()
            if isinstance(exc, OphirPowerMeterError):
                raise
            if isinstance(exc, Exception):
                raise OphirConnectionError(
                    f"Failed to connect to {self.name}: {exc}"
                ) from exc
            raise

    def disconnect(self) -> None:
        if (
            not self.connected
            and self._com is None
            and not self._com_initialized
        ):
            return

        self._require_owner_thread()
        cleanup_errors: list[BaseException] = []

        if self._streaming and self._com is not None and self._handle is not None:
            try:
                self._invoke("StopStream", self._handle, self.channel)
            except BaseException as exc:
                cleanup_errors.append(exc)
            finally:
                self._streaming = False

        if self._com is not None and self._handle is not None:
            try:
                self._invoke("Close", self._handle)
            except BaseException as exc:
                cleanup_errors.append(exc)

        self._handle = None
        self._com = None
        self._streaming = False
        self._set_connected(False)

        if self._com_initialized:
            try:
                self._com_uninitialize()
            except BaseException as exc:
                cleanup_errors.append(exc)
            finally:
                self._com_initialized = False

        self._owner_thread_id = None
        if cleanup_errors:
            first = cleanup_errors[0]
            raise OphirConnectionError(
                f"Failed to cleanly disconnect {self.name}: {first}"
            ) from first

    def close(self) -> None:
        """Idempotent alias used by generic device-owning code."""

        self.disconnect()

    def _cleanup_failed_connect(self) -> None:
        if self._com is not None and self._handle is not None:
            try:
                close = getattr(self._com, "Close")
                close(self._handle)
            except Exception:
                logger.exception(
                    "%s: cleanup failed while closing a partial connection",
                    self.name,
                )

        self._handle = None
        self._com = None
        self._streaming = False
        self._identity = None
        self._configuration = None
        self._set_connected(False)

        if self._com_initialized:
            try:
                self._com_uninitialize()
            except Exception:
                logger.exception(
                    "%s: COM uninitialization failed after connection error",
                    self.name,
                )
            finally:
                self._com_initialized = False
        self._owner_thread_id = None

    def _require_owner_thread(self) -> None:
        if (
            self._owner_thread_id is not None
            and threading.get_ident() != self._owner_thread_id
        ):
            raise OphirThreadError(
                f"{self.name} COM lifecycle belongs to thread "
                f"{self._owner_thread_id}; current thread is "
                f"{threading.get_ident()}. Connect, read, and close on the "
                "same thread."
            )

    def _invoke(self, method_name: str, *args: object) -> object:
        self._require_owner_thread()
        if self._com is None:
            raise OphirConnectionError(
                f"Cannot call {method_name}: {self.name} COM object is absent."
            )
        try:
            method = getattr(self._com, method_name)
            return method(*args)
        except OphirPowerMeterError:
            raise
        except Exception as exc:
            raise OphirConnectionError(
                f"Ophir COM call {method_name} failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Identity and named configuration
    # ------------------------------------------------------------------

    def _read_and_validate_identity(self) -> OphirDeviceIdentity:
        device_info = _as_sequence(
            self._invoke("GetDeviceInfo", self._handle),
            description="GetDeviceInfo response",
        )
        if len(device_info) != 3:
            raise OphirIdentityError(
                "GetDeviceInfo must return device name, ROM version, and "
                f"serial number; received {device_info!r}."
            )
        controller_name, rom_version, returned_controller_serial = (
            str(value).strip() for value in device_info
        )
        if returned_controller_serial != self.controller_serial:
            raise OphirIdentityError(
                "Opened Ophir controller serial does not match configuration: "
                f"expected {self.controller_serial!r}, received "
                f"{returned_controller_serial!r}."
            )

        sensor_exists = bool(
            self._invoke("IsSensorExists", self._handle, self.channel)
        )
        if not sensor_exists:
            raise OphirIdentityError(
                f"No Ophir sensor is present on channel {self.channel}."
            )

        sensor_info = _as_sequence(
            self._invoke("GetSensorInfo", self._handle, self.channel),
            description="GetSensorInfo response",
        )
        if len(sensor_info) != 3:
            raise OphirIdentityError(
                "GetSensorInfo must return sensor serial, type, and name; "
                f"received {sensor_info!r}."
            )
        returned_sensor_serial, sensor_type, sensor_name = (
            str(value).strip() for value in sensor_info
        )
        if returned_sensor_serial != self.sensor_serial:
            raise OphirIdentityError(
                "Attached Ophir sensor serial does not match configuration: "
                f"expected {self.sensor_serial!r}, received "
                f"{returned_sensor_serial!r}."
            )

        return OphirDeviceIdentity(
            controller_name=controller_name,
            controller_rom_version=rom_version,
            controller_serial=returned_controller_serial,
            sensor_serial=returned_sensor_serial,
            sensor_type=sensor_type,
            sensor_name=sensor_name,
            channel=self.channel,
        )

    def _configure_for_power(self) -> OphirConfiguration:
        measurement_mode = self._select_named_option(
            getter_name="GetMeasurementMode",
            setter_name="SetMeasurementMode",
            requested_name=POWER_MODE_NAME,
        )
        wavelength = self._select_named_option(
            getter_name="GetWavelengths",
            setter_name="SetWavelength",
            requested_name=self.wavelength_name,
        )
        power_range = self._select_named_option(
            getter_name="GetRanges",
            setter_name="SetRange",
            requested_name=self.fixed_range_name,
        )
        return OphirConfiguration(
            measurement_mode=measurement_mode,
            wavelength=wavelength,
            power_range=power_range,
        )

    def _get_option_selection(self, getter_name: str) -> OphirOptionSelection:
        response = _as_sequence(
            self._invoke(getter_name, self._handle, self.channel),
            description=f"{getter_name} response",
        )
        if len(response) != 2:
            raise OphirConfigurationError(
                f"{getter_name} must return current index and options; "
                f"received {response!r}."
            )
        raw_index, raw_options = response
        try:
            selected_index = int(raw_index)
        except (TypeError, ValueError, OverflowError) as exc:
            raise OphirConfigurationError(
                f"{getter_name} returned invalid current index {raw_index!r}."
            ) from exc
        options = tuple(
            str(option).strip()
            for option in _as_sequence(
                raw_options,
                description=f"{getter_name} options",
            )
        )
        if not options:
            raise OphirConfigurationError(
                f"{getter_name} returned no selectable options."
            )
        if not 0 <= selected_index < len(options):
            raise OphirConfigurationError(
                f"{getter_name} returned current index {selected_index}, but "
                f"only {len(options)} options exist: {options!r}."
            )
        return OphirOptionSelection(
            selected_index=selected_index,
            selected_name=options[selected_index],
            available_options=options,
        )

    def _select_named_option(
        self,
        *,
        getter_name: str,
        setter_name: str,
        requested_name: str | None,
    ) -> OphirOptionSelection:
        current = self._get_option_selection(getter_name)
        if requested_name is None:
            return current

        requested_key = _option_key(requested_name)
        matching_indices = [
            index
            for index, option in enumerate(current.available_options)
            if _option_key(option) == requested_key
        ]
        if not matching_indices:
            raise OphirConfigurationError(
                f"Requested option {requested_name!r} is unavailable for "
                f"{getter_name}. Returned options: "
                f"{current.available_options!r}."
            )
        if len(matching_indices) > 1:
            raise OphirConfigurationError(
                f"Requested option {requested_name!r} is ambiguous in "
                f"returned options {current.available_options!r}."
            )

        requested_index = matching_indices[0]
        self._invoke(
            setter_name,
            self._handle,
            self.channel,
            requested_index,
        )
        verified = self._get_option_selection(getter_name)
        if _option_key(verified.selected_name) != requested_key:
            raise OphirConfigurationError(
                f"{setter_name} did not select {requested_name!r}; readback "
                f"is {verified.selected_name!r}."
            )
        return verified

    @property
    def identity(self) -> OphirDeviceIdentity:
        self.require_connection()
        self._require_owner_thread()
        assert self._identity is not None
        return self._identity

    @property
    def configuration(self) -> OphirConfiguration:
        self.require_connection()
        self._require_owner_thread()
        assert self._configuration is not None
        return self._configuration

    def set_wavelength(self, returned_option_name: str) -> OphirOptionSelection:
        """Select a wavelength by a name returned from ``GetWavelengths``."""

        self._require_idle_connection()
        selection = self._select_named_option(
            getter_name="GetWavelengths",
            setter_name="SetWavelength",
            requested_name=returned_option_name,
        )
        assert self._configuration is not None
        self._configuration = OphirConfiguration(
            measurement_mode=self._configuration.measurement_mode,
            wavelength=selection,
            power_range=self._configuration.power_range,
        )
        self.wavelength_name = selection.selected_name
        return selection

    def set_fixed_range(
        self,
        returned_option_name: str,
    ) -> OphirOptionSelection:
        """Select a power range by a name returned from ``GetRanges``."""

        self._require_idle_connection()
        selection = self._select_named_option(
            getter_name="GetRanges",
            setter_name="SetRange",
            requested_name=returned_option_name,
        )
        assert self._configuration is not None
        self._configuration = OphirConfiguration(
            measurement_mode=self._configuration.measurement_mode,
            wavelength=self._configuration.wavelength,
            power_range=selection,
        )
        self.fixed_range_name = selection.selected_name
        return selection

    def _require_idle_connection(self) -> None:
        self.require_connection()
        self._require_owner_thread()
        if self._streaming:
            raise OphirConfigurationError(
                "Stop the Ophir stream before changing meter settings."
            )

    # ------------------------------------------------------------------
    # Streaming and raw-data preservation
    # ------------------------------------------------------------------

    @property
    def streaming(self) -> bool:
        return self._streaming

    def start_stream(self) -> None:
        self.require_connection()
        self._require_owner_thread()
        if self._streaming:
            return
        self._invoke("StartStream", self._handle, self.channel)
        self._streaming = True
        self._next_batch_index = 0

    def stop_stream(self) -> None:
        self.require_connection()
        self._require_owner_thread()
        if not self._streaming:
            return
        try:
            self._invoke("StopStream", self._handle, self.channel)
        finally:
            self._streaming = False

    def read_batch(self) -> tuple[PowerSample, ...]:
        """Read one complete ``GetData`` batch without filtering samples."""

        self.require_connection()
        self._require_owner_thread()
        if not self._streaming:
            raise OphirDataError(
                "Start the Ophir stream before requesting a data batch."
            )

        try:
            raw_response = self._invoke("GetData", self._handle, self.channel)
        except OphirConnectionError as exc:
            raise OphirDataError(f"Ophir GetData failed: {exc}") from exc
        response = _as_sequence(
            raw_response,
            description="GetData response",
        )
        if len(response) != 3:
            raise OphirDataError(
                "GetData must return values, timestamps, and statuses; "
                f"received {response!r}."
            )
        values = _as_sequence(response[0], description="GetData values")
        timestamps = _as_sequence(
            response[1],
            description="GetData timestamps",
        )
        statuses = _as_sequence(response[2], description="GetData statuses")
        if not (len(values) == len(timestamps) == len(statuses)):
            raise OphirDataError(
                "GetData returned mismatched batch lengths: "
                f"values={len(values)}, timestamps={len(timestamps)}, "
                f"statuses={len(statuses)}. No samples were truncated."
            )

        batch_index = self._next_batch_index
        self._next_batch_index += 1
        return tuple(
            self._make_sample(
                batch_index=batch_index,
                index_in_batch=index,
                raw_value=raw_value,
                raw_timestamp=raw_timestamp,
                raw_status=raw_status,
            )
            for index, (raw_value, raw_timestamp, raw_status) in enumerate(
                zip(values, timestamps, statuses)
            )
        )

    def _make_sample(
        self,
        *,
        batch_index: int,
        index_in_batch: int,
        raw_value: object,
        raw_timestamp: object,
        raw_status: object,
    ) -> PowerSample:
        power_w, value_issue = _parse_finite_number(
            raw_value,
            field="value",
        )
        timestamp_s, timestamp_issue = _parse_finite_number(
            raw_timestamp,
            field="timestamp",
        )

        reasons: list[str] = []
        if value_issue is not None:
            reasons.append(value_issue)
        elif power_w is not None and power_w <= 0.0:
            reasons.append("value_not_positive")
        if timestamp_issue is not None:
            reasons.append(timestamp_issue)

        if raw_status is None:
            reasons.append("status_missing")
        elif ophir_status_name(raw_status) != "ok":
            reasons.append(f"status_{ophir_status_name(raw_status)}")

        return PowerSample(
            batch_index=batch_index,
            index_in_batch=index_in_batch,
            raw_value=raw_value,
            raw_timestamp=raw_timestamp,
            raw_status=raw_status,
            power_w=power_w,
            timestamp_s=timestamp_s,
            valid_for_statistics=not reasons,
            invalid_reasons=tuple(reasons),
        )

    def acquire_trace(
        self,
        duration_s: float,
        *,
        poll_interval_s: float = 0.1,
    ) -> PowerTrace:
        """Stream for a requested duration and return every received sample."""

        self._require_idle_connection()
        duration = float(duration_s)
        poll_interval = float(poll_interval_s)
        if not math.isfinite(duration) or duration <= 0.0:
            raise ValueError("duration_s must be finite and greater than zero.")
        if not math.isfinite(poll_interval) or poll_interval <= 0.0:
            raise ValueError(
                "poll_interval_s must be finite and greater than zero."
            )

        identity = self.identity
        configuration = self.configuration
        samples: list[PowerSample] = []
        batch_sizes: list[int] = []

        self.start_stream()
        try:
            started_at_unix_s = float(self._wall_clock())
            start_monotonic = float(self._monotonic_clock())
            if not math.isfinite(started_at_unix_s):
                raise OphirDataError(
                    "The wall clock returned a non-finite start time."
                )
            if not math.isfinite(start_monotonic):
                raise OphirDataError(
                    "The monotonic clock returned a non-finite start time."
                )
            deadline = start_monotonic + duration
            clock_resolution = max(math.ulp(deadline) * 2.0, 1e-12)
            while True:
                current = float(self._monotonic_clock())
                if not math.isfinite(current):
                    raise OphirDataError(
                        "The monotonic clock returned a non-finite value "
                        "during power sampling."
                    )
                if current < start_monotonic:
                    raise OphirDataError(
                        "The monotonic clock moved backwards during power "
                        "sampling."
                    )
                remaining = deadline - current
                if remaining <= clock_resolution:
                    break
                sleep_duration = min(poll_interval, remaining)
                self._sleep(sleep_duration)
                after_sleep = float(self._monotonic_clock())
                if not math.isfinite(after_sleep):
                    raise OphirDataError(
                        "The monotonic clock returned a non-finite value "
                        "after waiting for power-meter data."
                    )
                if after_sleep <= current:
                    raise OphirDataError(
                        "The monotonic clock did not advance while waiting for "
                        "power-meter data."
                    )
                batch = self.read_batch()
                batch_sizes.append(len(batch))
                samples.extend(batch)

            elapsed = float(self._monotonic_clock()) - start_monotonic
        except BaseException:
            try:
                self.stop_stream()
            except Exception:
                logger.exception(
                    "%s: failed to stop stream after acquisition error",
                    self.name,
                )
            raise
        else:
            self.stop_stream()

        return PowerTrace(
            samples=tuple(samples),
            batch_sizes=tuple(batch_sizes),
            requested_duration_s=duration,
            elapsed_duration_s=elapsed,
            started_at_unix_s=started_at_unix_s,
            trace_id=self._trace_id_factory(),
            source_unit="W",
            device_serial=identity.controller_serial,
            sensor_serial=identity.sensor_serial,
            measurement_mode=configuration.measurement_mode.selected_name,
            wavelength_option=configuration.wavelength.selected_name,
            range_option=configuration.power_range.selected_name,
        )

    # ------------------------------------------------------------------
    # Information
    # ------------------------------------------------------------------

    def info(self) -> dict:
        identity = self._identity
        configuration = self._configuration
        return {
            "name": self.name,
            "connected": self.connected,
            "controller_serial": self.controller_serial,
            "sensor_serial": self.sensor_serial,
            "channel": self.channel,
            "controller_name": (
                None if identity is None else identity.controller_name
            ),
            "sensor_name": None if identity is None else identity.sensor_name,
            "measurement_mode": (
                None
                if configuration is None
                else configuration.measurement_mode.selected_name
            ),
            "wavelength_option": (
                None
                if configuration is None
                else configuration.wavelength.selected_name
            ),
            "range_option": (
                None
                if configuration is None
                else configuration.power_range.selected_name
            ),
            "streaming": self.streaming,
        }

    def check_connection(self) -> bool:
        """Verify USB presence, then the controller and sensor identities."""

        self.require_connection()
        self._require_owner_thread()
        scanned_serials = tuple(
            str(serial).strip()
            for serial in _as_sequence(
                self._invoke("ScanUSB"),
                description="ScanUSB serial numbers",
            )
        )
        if self.controller_serial not in scanned_serials:
            found = ", ".join(scanned_serials) or "none"
            raise OphirConnectionError(
                f"Ophir controller {self.controller_serial!r} is no longer "
                f"present on USB (found: {found})."
            )
        self._identity = self._read_and_validate_identity()
        return True
