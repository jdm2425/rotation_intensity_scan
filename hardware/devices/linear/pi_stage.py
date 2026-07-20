"""Safe, reusable PI GCS driver for a single-axis linear stage.

The driver deliberately keeps connection and status inspection read-only.  It
does not run PI's startup helper, select a stage database entry, reference an
axis, phase-find a motor, redefine its position, or write persistent
parameters.  The only state-changing preparation it exposes is an explicit,
reference-gated request to enable the motor and servo, plus a verified request
to reduce the active velocity to a configured value.

``PIPython`` is imported only when a real device is constructed.  Supplying a
fake GCS device or factory therefore keeps unit tests entirely hardware-free.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import logging
import math
import re
import threading
import time
from typing import Any, TypeVar

from hardware.devices.base import HardwareDevice, HardwareError

logger = logging.getLogger(__name__)


DEFAULT_CONTROLLER_MODEL = "C-891.120200"
DEFAULT_CONTROLLER_SERIAL = "118054611"
DEFAULT_CONTROLLER_FAMILY = "C-891"
DEFAULT_AXIS = "1"


class PIStageError(HardwareError):
    """Base class for PI linear-stage failures."""


class PIStageConnectionError(PIStageError):
    """Raised when the controller cannot be opened or closed cleanly."""


class PIStageIdentityError(PIStageConnectionError):
    """Raised when live controller identity does not match configuration."""


class PIStageProtocolError(PIStageError):
    """Raised when a required GCS response cannot be interpreted safely."""


class PIStageStateError(PIStageError):
    """Raised when the controller is not in a safe state for an operation."""


class PIStageLimitError(PIStageError, ValueError):
    """Raised when a target or reported travel range is unsafe."""


class PIStageMotionError(PIStageError):
    """Base class for errors after an absolute move has been requested."""


class PIStageTimeoutError(PIStageMotionError, TimeoutError):
    """Raised when the controller does not report on-target in time."""


class PIStagePositionError(PIStageMotionError):
    """Raised when the final position is outside the configured tolerance."""


@dataclass(frozen=True)
class PIStageConfig:
    """Controller identity, software limits, and bounded-motion settings.

    ``application_min_mm`` and ``application_max_mm`` are an additional
    software safety envelope.  Every move also queries the controller's live
    ``TMN?`` and ``TMX?`` values and uses the intersection of both ranges.

    ``configured_velocity_mm_s is the exact controller velocity applied and
    verified whenever the stage connects. When it is None, the existing
    controller velocity is preserved.
    """

    serial: str = DEFAULT_CONTROLLER_SERIAL
    expected_controller_model: str = DEFAULT_CONTROLLER_MODEL
    controller_family: str = DEFAULT_CONTROLLER_FAMILY
    axis: str = DEFAULT_AXIS
    name: str = "PI Linear Stage"
    application_min_mm: float = -12.0
    application_max_mm: float = 12.0
    final_tolerance_mm: float = 0.01
    motion_timeout_s: float = 30.0
    poll_interval_s: float = 0.05
    configured_stage_model: str | None = "V-408.132020"
    configured_velocity_mm_s: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "serial",
            "expected_controller_model",
            "controller_family",
            "axis",
            "name",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty.")

        minimum = _finite_float(
            self.application_min_mm,
            field_name="application_min_mm",
        )
        maximum = _finite_float(
            self.application_max_mm,
            field_name="application_max_mm",
        )
        if minimum >= maximum:
            raise ValueError(
                "application_min_mm must be less than application_max_mm."
            )

        tolerance = _finite_float(
            self.final_tolerance_mm,
            field_name="final_tolerance_mm",
        )
        if tolerance < 0.0:
            raise ValueError("final_tolerance_mm must be non-negative.")

        timeout = _finite_float(
            self.motion_timeout_s,
            field_name="motion_timeout_s",
        )
        if timeout <= 0.0:
            raise ValueError("motion_timeout_s must be positive.")

        poll_interval = _finite_float(
            self.poll_interval_s,
            field_name="poll_interval_s",
        )
        if poll_interval <= 0.0:
            raise ValueError("poll_interval_s must be positive.")

        if self.configured_velocity_mm_s is not None:
            velocity = _finite_float(
                self.configured_velocity_mm_s,
                field_name="configured_velocity_mm_s",
            )
            if velocity <= 0.0:
                raise ValueError(
                    "configured_velocity_mm_s must be positive when set."
                )

    @classmethod
    def from_project_config(
        cls,
        config: object,
        *,
        controller_family: str = DEFAULT_CONTROLLER_FAMILY,
        poll_interval_s: float = 0.05,
    ) -> PIStageConfig:
        """Build from the repository's structurally compatible config object.

        The generic driver intentionally does not import ``hardware.config``;
        this converter keeps it reusable in other projects while accepting the
        current project's ``LinearStageConfig``.
        """

        try:
            return cls(
                serial=str(getattr(config, "serial")),
                expected_controller_model=str(
                    getattr(config, "controller_model")
                ),
                controller_family=controller_family,
                axis=str(getattr(config, "axis")),
                name=str(getattr(config, "name")),
                application_min_mm=float(
                    getattr(config, "application_min_mm")
                ),
                application_max_mm=float(
                    getattr(config, "application_max_mm")
                ),
                final_tolerance_mm=float(
                    getattr(config, "position_tolerance_mm")
                ),
                motion_timeout_s=float(
                    getattr(config, "motion_timeout_s")
                ),
                poll_interval_s=poll_interval_s,
                configured_stage_model=_optional_string_attribute(
                    config,
                    "stage_model",
                ),
                configured_velocity_mm_s=_optional_float_attribute(
                    config,
                    "velocity_mm_s",
                ),
            )
        except AttributeError as exc:
            raise ValueError(
                "Project linear-stage config is missing a required attribute."
            ) from exc


@dataclass(frozen=True)
class PIQueryFailure:
    """One optional read-only status query that was unavailable or invalid."""

    query: str
    error_type: str
    message: str


@dataclass(frozen=True)
class PIStageSnapshot:
    """Read-only controller and axis state captured at one point in time."""

    identity: str
    axes: tuple[str, ...]
    configured_axis: str
    stage_assignment: str | None
    motor_enabled: bool | None
    servo_enabled: bool | None
    referenced: bool | None
    live_min_mm: float | None
    live_max_mm: float | None
    position_mm: float | None
    target_position_mm: float | None
    on_target: bool | None
    velocity_mm_s: float | None
    query_failures: tuple[PIQueryFailure, ...] = ()

    @property
    def failed_query_names(self) -> tuple[str, ...]:
        """Names of optional queries which did not return usable data."""

        return tuple(failure.query for failure in self.query_failures)


@dataclass(frozen=True)
class PIClosedLoopState:
    """Verified state after explicit closed-loop preparation."""

    referenced: bool
    motor_enabled: bool
    servo_enabled: bool
    motor_was_enabled: bool
    servo_was_enabled: bool


@dataclass(frozen=True)
class PIMotionLimits:
    """Application, controller, and effective absolute-motion limits."""

    application_min_mm: float
    application_max_mm: float
    live_min_mm: float
    live_max_mm: float
    allowed_min_mm: float
    allowed_max_mm: float


@dataclass(frozen=True)
class PIMotionResult:
    """Verified result of one blocking absolute move."""

    target_position_mm: float
    final_position_mm: float
    elapsed_s: float
    limits: PIMotionLimits


_T = TypeVar("_T")


class PILinearStage(HardwareDevice):
    """Single-axis PI C-891 linear-stage driver using PI's GCS interface."""

    # PI documents the GCS DLL as not thread-safe.  This lock is shared by all
    # instances, including instances which wrap different controller objects.
    _gcs_call_lock = threading.RLock()

    def __init__(
        self,
        config: PIStageConfig | None = None,
        *,
        gcs_device: Any | None = None,
        gcs_device_factory: Callable[[str], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a disconnected stage without importing or opening PI APIs.

        ``gcs_device`` and ``gcs_device_factory`` are dependency-injection
        hooks for hardware-free tests and alternative PI gateways.  They are
        mutually exclusive.
        """

        self.config = config or PIStageConfig()
        super().__init__(name=self.config.name)

        if gcs_device is not None and gcs_device_factory is not None:
            raise ValueError(
                "Pass either gcs_device or gcs_device_factory, not both."
            )
        if not callable(monotonic):
            raise TypeError("monotonic must be callable.")
        if not callable(sleep):
            raise TypeError("sleep must be callable.")

        self._injected_device = gcs_device
        self._device_factory = gcs_device_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._device: Any | None = None
        self._snapshot: PIStageSnapshot | None = None
        self._motion_lock = threading.RLock()

    @classmethod
    def from_project_config(
        cls,
        config: object,
        *,
        controller_family: str = DEFAULT_CONTROLLER_FAMILY,
        poll_interval_s: float = 0.05,
        **kwargs: Any,
    ) -> PILinearStage:
        """Construct from ``hardware.config.LinearStageConfig`` by structure."""

        driver_config = PIStageConfig.from_project_config(
            config,
            controller_family=controller_family,
            poll_interval_s=poll_interval_s,
        )
        return cls(driver_config, **kwargs)

    @property
    def serial(self) -> str:
        """Configured USB controller serial number."""

        return self.config.serial

    @property
    def axis(self) -> str:
        """Configured GCS axis identifier."""

        return self.config.axis

    @property
    def snapshot(self) -> PIStageSnapshot | None:
        """Most recent read-only status snapshot, if one has been captured."""

        return self._snapshot

    def connect(self) -> None:
        """Open USB, strictly validate identity/axis, and query status only."""

        if self.connected:
            return

        device: Any | None = None
        try:
            with self._gcs_call_lock:
                device = self._make_gcs_device()
                device.ConnectUSB(serialnum=self.config.serial)

            identity = str(self._invoke(device, "qIDN")).strip()
            self._validate_identity(identity)

            axes = _normalise_axes(self._invoke(device, "qSAI"))
            if self.axis not in axes:
                raise PIStageIdentityError(
                    f"Configured PI axis {self.axis!r} is not active. "
                    f"Controller reported axes {axes!r}."
                )

            snapshot = self._capture_snapshot(
                device=device,
                identity=identity,
                axes=axes,
            )
            expected_stage = self.config.configured_stage_model
            if expected_stage is not None:
                if snapshot.stage_assignment is None:
                    raise PIStageIdentityError(
                        "Could not verify the configured PI stage assignment "
                        f"{expected_stage!r} with CST?."
                    )
                if not _contains_identity_field(
                    snapshot.stage_assignment,
                    expected_stage,
                ):
                    raise PIStageIdentityError(
                        "PI stage assignment does not match configuration: "
                        f"expected {expected_stage!r}, observed "
                        f"{snapshot.stage_assignment!r}."
                    )
        except PIStageError:
            self._close_after_failed_connect(device)
            raise
        except Exception as exc:
            self._close_after_failed_connect(device)
            raise PIStageConnectionError(
                "Failed to connect to PI controller "
                f"{self.config.expected_controller_model!r} with serial "
                f"{self.serial!r}."
            ) from exc

        self._device = device
        self._snapshot = snapshot
        self._set_connected(True)

        try:
            applied_velocity = (
                self.apply_configured_velocity()
            )

        except Exception:
            try:
                self.disconnect()
            except Exception:
                logger.exception(
                    "Failed to disconnect PI controller after "
                    "velocity configuration failed."
                )

            raise

        logger.info(
            "%s connected: %s (axis %s), velocity %.6g mm/s.",
            self.name,
            identity,
            self.axis,
            applied_velocity,
        )

    def disconnect(self) -> None:
        """Close the connection idempotently without changing axis state."""

        if not self.connected and self._device is None:
            return

        close_error: Exception | None = None
        device = self._device
        try:
            if device is not None:
                self._invoke(device, "CloseConnection")
        except Exception as exc:  # state is still cleared deterministically
            close_error = exc
        finally:
            self._device = None
            self._set_connected(False)

        if close_error is not None:
            raise PIStageConnectionError(
                f"Failed to close PI controller {self.serial!r} cleanly."
            ) from close_error

    def refresh_snapshot(self) -> PIStageSnapshot:
        """Repeat the documented read-only identity and axis-status queries."""

        self.require_connection()
        device = self._connected_device()
        identity = str(self._invoke(device, "qIDN")).strip()
        self._validate_identity(identity)
        axes = _normalise_axes(self._invoke(device, "qSAI"))
        if self.axis not in axes:
            raise PIStageIdentityError(
                f"Configured PI axis {self.axis!r} is no longer active; "
                f"controller reported {axes!r}."
            )
        snapshot = self._capture_snapshot(
            device=device,
            identity=identity,
            axes=axes,
        )
        self._snapshot = snapshot
        return snapshot

    def prepare_for_closed_loop(self) -> PIClosedLoopState:
        """Explicitly enable motor/servo, but only on a referenced axis.

        This method never performs reference motion or changes the position
        definition.  If ``FRF?`` is false or unavailable it raises before any
        state-changing GCS command is sent.
        """

        self.require_connection()
        referenced = self._required_bool_query("qFRF")
        if not referenced:
            raise PIStageStateError(
                f"PI axis {self.axis!r} is not referenced. Closed-loop "
                "preparation was refused; reference it explicitly with an "
                "operator-approved procedure before using this driver."
            )

        motor_was_enabled = self._required_bool_query("qEAX")
        servo_was_enabled = self._required_bool_query("qSVO")

        if not motor_was_enabled:
            self._closed_loop_command("EAX", True)
        motor_enabled = self._required_bool_query("qEAX")
        if not motor_enabled:
            raise PIStageStateError(
                f"PI axis {self.axis!r} did not report motor enabled after EAX."
            )

        if not servo_was_enabled:
            self._closed_loop_command("SVO", True)
        servo_enabled = self._required_bool_query("qSVO")
        referenced_after = self._required_bool_query("qFRF")

        if not referenced_after:
            raise PIStageStateError(
                f"PI axis {self.axis!r} lost its referenced state during "
                "closed-loop preparation."
            )
        if not servo_enabled:
            raise PIStageStateError(
                f"PI axis {self.axis!r} did not report servo enabled after SVO."
            )

        return PIClosedLoopState(
            referenced=referenced_after,
            motor_enabled=motor_enabled,
            servo_enabled=servo_enabled,
            motor_was_enabled=motor_was_enabled,
            servo_was_enabled=servo_was_enabled,
        )

    def apply_configured_velocity(self) -> float:
        """
        Apply and verify the configured controller velocity.

        When configured_velocity_mm_s is None, the controller's existing
        velocity is left unchanged. Otherwise, the configured value is
        written to the controller and verified by reading it back.
        """

        self.require_connection()

        configured = self.config.configured_velocity_mm_s

        if configured is None:
            current = self._required_float_query("qVEL")

            if current <= 0.0:
                raise PIStageStateError(
                    f"PI axis {self.axis!r} reported a non-positive "
                    f"velocity ({current} mm/s)."
                )

            return current

        target = _finite_float(
            configured,
            field_name="configured_velocity_mm_s",
        )

        if target <= 0.0:
            raise PIStageStateError(
                "Configured PI velocity must be positive."
            )

        try:
            self._command(
                "VEL",
                self.axis,
                target,
            )

        except Exception as exc:
            raise PIStageStateError(
                f"PI controller rejected configured velocity "
                f"{target} mm/s for axis {self.axis!r}."
            ) from exc

        observed = self._required_float_query(
            "qVEL"
        )

        if not math.isclose(
            observed,
            target,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise PIStageStateError(
                f"PI axis {self.axis!r} did not retain the "
                f"configured velocity: requested={target} mm/s, "
                f"observed={observed} mm/s."
            )

        self.refresh_snapshot()

        logger.info(
            "%s velocity set to %.6g mm/s.",
            self.name,
            observed,
        )

        return observed

    @property
    def position_mm(self) -> float:
        """Current live axis position in millimetres."""

        self.require_connection()
        return self._required_float_query("qPOS")

    @property
    def current_position_mm(self) -> float:
        """Explicit alias for :attr:`position_mm`."""

        return self.position_mm

    def motion_limits(self) -> PIMotionLimits:
        """Query and intersect live controller limits with application limits."""

        self.require_connection()
        try:
            live_minimum = self._required_float_query("qTMN")
            live_maximum = self._required_float_query("qTMX")
        except PIStageProtocolError as exc:
            raise PIStageLimitError(
                "Cannot establish safe PI travel bounds from TMN?/TMX?."
            ) from exc

        if live_minimum >= live_maximum:
            raise PIStageLimitError(
                "PI controller reported an invalid travel range: "
                f"{live_minimum} to {live_maximum} mm."
            )

        application_minimum = float(self.config.application_min_mm)
        application_maximum = float(self.config.application_max_mm)
        allowed_minimum = max(application_minimum, live_minimum)
        allowed_maximum = min(application_maximum, live_maximum)
        if allowed_minimum > allowed_maximum:
            raise PIStageLimitError(
                "Configured application limits do not overlap the PI "
                "controller's live travel limits: "
                f"application=[{application_minimum}, {application_maximum}] "
                f"mm, live=[{live_minimum}, {live_maximum}] mm."
            )

        return PIMotionLimits(
            application_min_mm=application_minimum,
            application_max_mm=application_maximum,
            live_min_mm=live_minimum,
            live_max_mm=live_maximum,
            allowed_min_mm=allowed_minimum,
            allowed_max_mm=allowed_maximum,
        )

    def move_absolute_mm(
        self,
        target_position_mm: float,
        *,
        timeout_s: float | None = None,
    ) -> PIMotionResult:
        """Move to a finite, doubly bounded target and verify final position.

        The call blocks on ``ONT?`` with a monotonic timeout.  Any failure after
        ``MOV`` is attempted invokes the controller's smooth ``HLT`` command in
        best-effort cleanup before the original error is raised.
        """

        self.require_connection()
        target = _finite_float(
            target_position_mm,
            field_name="target_position_mm",
        )
        timeout = (
            float(self.config.motion_timeout_s)
            if timeout_s is None
            else _finite_float(timeout_s, field_name="timeout_s")
        )
        if timeout <= 0.0:
            raise ValueError("timeout_s must be positive.")

        with self._motion_lock:
            limits = self.motion_limits()
            if not limits.allowed_min_mm <= target <= limits.allowed_max_mm:
                raise PIStageLimitError(
                    f"Requested PI target {target} mm is outside the effective "
                    f"safe range [{limits.allowed_min_mm}, "
                    f"{limits.allowed_max_mm}] mm (application and live "
                    "controller limits intersected)."
                )

            self._require_motion_ready()
            start = self._monotonic()
            move_attempted = False
            try:
                move_attempted = True
                try:
                    self._command("MOV", self.axis, target)
                except Exception as exc:
                    raise PIStageMotionError(
                        f"PI controller rejected absolute move of axis "
                        f"{self.axis!r} to {target} mm."
                    ) from exc

                while not self._required_bool_query("qONT"):
                    elapsed = self._monotonic() - start
                    if elapsed >= timeout:
                        raise PIStageTimeoutError(
                            f"PI axis {self.axis!r} did not reach {target} mm "
                            f"within {timeout} s."
                        )
                    self._sleep(
                        min(
                            float(self.config.poll_interval_s),
                            max(0.0, timeout - elapsed),
                        )
                    )

                final_position = self._required_float_query("qPOS")
                if (
                    abs(final_position - target)
                    > float(self.config.final_tolerance_mm)
                ):
                    raise PIStagePositionError(
                        f"PI axis {self.axis!r} reported on-target but final "
                        f"position {final_position} mm differs from target "
                        f"{target} mm by more than "
                        f"{self.config.final_tolerance_mm} mm."
                    )
            except Exception:
                if move_attempted:
                    self._halt_best_effort()
                raise

            return PIMotionResult(
                target_position_mm=target,
                final_position_mm=final_position,
                elapsed_s=max(0.0, self._monotonic() - start),
                limits=limits,
            )

    def halt(self) -> None:
        """Request a smooth halt of this axis without clearing controller error."""

        self.require_connection()
        try:
            self._command("HLT", self.axis, noraise=True)
        except Exception as exc:
            raise PIStageMotionError(
                f"Failed to halt PI axis {self.axis!r} smoothly."
            ) from exc

    def info(self) -> dict[str, Any]:
        """Return configuration and the most recent read-only snapshot."""

        snapshot = self._snapshot
        return {
            "name": self.name,
            "connected": self.connected,
            "serial": self.serial,
            "expected_controller_model": (
                self.config.expected_controller_model
            ),
            "configured_stage_model": self.config.configured_stage_model,
            "axis": self.axis,
            "application_min_mm": self.config.application_min_mm,
            "application_max_mm": self.config.application_max_mm,
            "configured_velocity_mm_s": (
                self.config.configured_velocity_mm_s
            ),
            "identity": snapshot.identity if snapshot is not None else None,
            "stage_assignment": (
                snapshot.stage_assignment if snapshot is not None else None
            ),
            "position_mm": snapshot.position_mm if snapshot is not None else None,
            "live_min_mm": snapshot.live_min_mm if snapshot is not None else None,
            "live_max_mm": snapshot.live_max_mm if snapshot is not None else None,
            "motor_enabled": (
                snapshot.motor_enabled if snapshot is not None else None
            ),
            "servo_enabled": (
                snapshot.servo_enabled if snapshot is not None else None
            ),
            "referenced": snapshot.referenced if snapshot is not None else None,
            "velocity_mm_s": (
                snapshot.velocity_mm_s if snapshot is not None else None
            ),
            "snapshot_query_failures": (
                [failure.query for failure in snapshot.query_failures]
                if snapshot is not None
                else []
            ),
        }

    def _make_gcs_device(self) -> Any:
        if self._injected_device is not None:
            return self._injected_device
        factory = self._device_factory or _load_default_gcs_factory()
        return factory(self.config.controller_family)

    @classmethod
    def _invoke(
        cls,
        device: Any,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        with cls._gcs_call_lock:
            method = getattr(device, method_name)
            return method(*args, **kwargs)

    def _command(
        self,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return self._invoke(
            self._connected_device(),
            method_name,
            *args,
            **kwargs,
        )

    def _connected_device(self) -> Any:
        device = self._device
        if not self.connected or device is None:
            self.require_connection()
            raise PIStageConnectionError(
                f"{self.name} has no active GCS device object."
            )
        return device

    def _validate_identity(self, identity: str) -> None:
        if not identity:
            raise PIStageIdentityError(
                "PI controller returned an empty *IDN? response."
            )

        missing: list[str] = []
        if not _contains_identity_field(
            identity,
            self.config.expected_controller_model,
        ):
            missing.append(
                "model " + repr(self.config.expected_controller_model)
            )
        if not _contains_identity_field(identity, self.serial):
            missing.append("serial " + repr(self.serial))
        if missing:
            raise PIStageIdentityError(
                "PI *IDN? response did not match configured "
                + " and ".join(missing)
                + f". Observed: {identity!r}."
            )

    def _capture_snapshot(
        self,
        *,
        device: Any,
        identity: str,
        axes: tuple[str, ...],
    ) -> PIStageSnapshot:
        failures: list[PIQueryFailure] = []

        def optional(
            query_name: str,
            converter: Callable[[Any], _T],
        ) -> _T | None:
            try:
                raw = self._invoke(device, query_name, self.axis)
                return converter(_axis_value(raw, self.axis, query_name))
            except Exception as exc:
                failures.append(
                    PIQueryFailure(
                        query=query_name,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                return None

        return PIStageSnapshot(
            identity=identity,
            axes=axes,
            configured_axis=self.axis,
            stage_assignment=optional("qCST", _as_string),
            motor_enabled=optional("qEAX", _as_bool),
            servo_enabled=optional("qSVO", _as_bool),
            referenced=optional("qFRF", _as_bool),
            live_min_mm=optional("qTMN", _as_finite_float),
            live_max_mm=optional("qTMX", _as_finite_float),
            position_mm=optional("qPOS", _as_finite_float),
            target_position_mm=optional("qMOV", _as_finite_float),
            on_target=optional("qONT", _as_bool),
            velocity_mm_s=optional("qVEL", _as_finite_float),
            query_failures=tuple(failures),
        )

    def _required_axis_query(
        self,
        query_name: str,
        converter: Callable[[Any], _T],
    ) -> _T:
        try:
            raw = self._command(query_name, self.axis)
            value = _axis_value(raw, self.axis, query_name)
            return converter(value)
        except PIStageError:
            raise
        except Exception as exc:
            raise PIStageProtocolError(
                f"Required PI query {query_name} failed for axis "
                f"{self.axis!r}: {exc}"
            ) from exc

    def _required_bool_query(self, query_name: str) -> bool:
        return self._required_axis_query(query_name, _as_bool)

    def _required_float_query(self, query_name: str) -> float:
        return self._required_axis_query(query_name, _as_finite_float)

    def _require_motion_ready(self) -> None:
        if not self._required_bool_query("qFRF"):
            raise PIStageStateError(
                f"PI axis {self.axis!r} is not referenced; movement refused."
            )
        if not self._required_bool_query("qEAX"):
            raise PIStageStateError(
                f"PI axis {self.axis!r} motor is disabled; call "
                "prepare_for_closed_loop() explicitly."
            )
        if not self._required_bool_query("qSVO"):
            raise PIStageStateError(
                f"PI axis {self.axis!r} servo is disabled; call "
                "prepare_for_closed_loop() explicitly."
            )

    def _closed_loop_command(self, command_name: str, state: bool) -> None:
        try:
            self._command(command_name, self.axis, state)
        except Exception as exc:
            raise PIStageStateError(
                f"Failed to set {command_name}={state} for PI axis "
                f"{self.axis!r}."
            ) from exc

    def _halt_best_effort(self) -> None:
        try:
            self._command("HLT", self.axis, noraise=True)
        except Exception:
            logger.exception(
                "Failed to halt PI axis %s after a motion error.",
                self.axis,
            )

    def _close_after_failed_connect(self, device: Any | None) -> None:
        if device is None:
            return
        try:
            self._invoke(device, "CloseConnection")
        except Exception:
            logger.exception(
                "Failed to close PI controller after connection validation "
                "failed."
            )


def _load_default_gcs_factory() -> Callable[[str], Any]:
    """Load PI's optional factory only when real hardware is requested."""

    try:
        from pipython import GCSDevice
    except ImportError as exc:
        raise PIStageConnectionError(
            "PIPython is required for a real PI stage connection. Install "
            "the verified PI Python package, or inject a GCS device/factory "
            "for hardware-free use."
        ) from exc
    return GCSDevice


def _normalise_axes(raw_axes: Any) -> tuple[str, ...]:
    if isinstance(raw_axes, Mapping):
        values: Iterable[Any] = raw_axes.keys()
    elif isinstance(raw_axes, str):
        values = re.split(r"[,\s]+", raw_axes.strip())
    else:
        try:
            values = iter(raw_axes)
        except TypeError as exc:
            raise PIStageProtocolError(
                f"Cannot interpret qSAI response {raw_axes!r}."
            ) from exc

    axes = tuple(str(value).strip() for value in values if str(value).strip())
    if not axes:
        raise PIStageProtocolError(
            f"PI controller reported no active axes via qSAI: {raw_axes!r}."
        )
    return axes


def _axis_value(raw: Any, axis: str, query_name: str) -> Any:
    if isinstance(raw, Mapping):
        if axis in raw:
            return raw[axis]
        for key, value in raw.items():
            if str(key) == axis:
                return value
        raise PIStageProtocolError(
            f"{query_name} response has no value for axis {axis!r}: {raw!r}."
        )

    if isinstance(raw, (list, tuple)):
        if len(raw) != 1:
            raise PIStageProtocolError(
                f"{query_name} returned {len(raw)} values for one axis: "
                f"{raw!r}."
            )
        return raw[0]
    return raw


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().casefold()
        if normalised in {"1", "true", "on", "yes"}:
            return True
        if normalised in {"0", "false", "off", "no"}:
            return False
        raise PIStageProtocolError(
            f"Cannot interpret PI boolean value {value!r}."
        )
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise PIStageProtocolError(f"Cannot interpret PI boolean value {value!r}.")


def _as_string(value: Any) -> str:
    return str(value).strip()


def _as_finite_float(value: Any) -> float:
    return _finite_float(value, field_name="PI query value")


def _finite_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number, not bool.")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{field_name} must be finite.")
    return converted


def _contains_identity_field(identity: str, expected: str) -> bool:
    # Boundary matching rejects partial serial/model matches while accepting PI
    # responses that prefix a serial with labels such as "S/N" or "SN".
    pattern = rf"(?<![A-Za-z0-9]){re.escape(str(expected).strip())}(?![A-Za-z0-9])"
    return re.search(pattern, identity, flags=re.IGNORECASE) is not None


def _optional_string_attribute(config: object, name: str) -> str | None:
    value = getattr(config, name, None)
    return None if value is None else str(value)


def _optional_float_attribute(config: object, name: str) -> float | None:
    value = getattr(config, name, None)
    return None if value is None else float(value)
