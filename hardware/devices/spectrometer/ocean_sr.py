"""
ocean_sr.py

Driver for the Ocean Insight SR spectrometer.

Supports both python-seabreeze implementations. The configured SR600415 keeps
``pyseabreeze`` as its explicit default; other models may select
``cseabreeze`` (also accepted as ``seabreeze``) or guarded ``auto`` fallback.

Every acquisition returns a universal Spectrum object.
"""

from __future__ import annotations

import logging
from importlib import import_module
import threading
from typing import Any, Callable

import numpy as np

from hardware.devices.spectrometer.spectrum import Spectrum

logger = logging.getLogger(__name__)

_BACKEND_ALIASES = {
    "pyseabreeze": "pyseabreeze",
    "cseabreeze": "cseabreeze",
    "seabreeze": "cseabreeze",
    "auto": "auto",
}
_AUTO_BACKENDS = ("pyseabreeze", "cseabreeze")
SeaBreezeLoader = Callable[
    [str],
    tuple[type[Any], Callable[[], list[Any]], Callable[[], None]],
]


def _normalise_backend(backend: str) -> str:
    value = str(backend).strip().lower()
    try:
        return _BACKEND_ALIASES[value]
    except KeyError as exc:
        choices = ", ".join(sorted(_BACKEND_ALIASES))
        raise ValueError(
            f"Unsupported SeaBreeze backend {backend!r}; choose one of {choices}."
        ) from exc


def _load_seabreeze_backend(
    backend: str,
) -> tuple[type[Any], Callable[[], list[Any]], Callable[[], None]]:
    """Create bindings isolated from the high-level module's backend cache."""

    try:
        backend_module = import_module(f"seabreeze.{backend}")
        spectrometers = import_module("seabreeze.spectrometers")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"SeaBreeze backend {backend!r} is not installed. Install "
            "requirements-hardware.txt before connecting an Ocean spectrometer."
        ) from exc

    try:
        api = backend_module.SeaBreezeAPI()
    except Exception as exc:
        raise RuntimeError(
            f"SeaBreeze backend {backend!r} could not be initialised: {exc}"
        ) from exc

    class BackendSpectrometer(spectrometers.Spectrometer):
        _backend = backend_module

    BackendSpectrometer.__name__ = f"{backend.title()}Spectrometer"
    return BackendSpectrometer, api.list_devices, api.shutdown


def _shutdown_seabreeze_backend(
    shutdown: Callable[[], None] | None,
    backend: str,
) -> None:
    if shutdown is None:
        return
    try:
        shutdown()
    except Exception:
        logger.exception("Failed to shut down SeaBreeze backend %s.", backend)


class OceanSR:
    """
    Ocean Insight SR spectrometer.

    Parameters
    ----------
    serial
        Spectrometer serial number.

    integration_time_ms
        Exposure time.

    backend
        ``pyseabreeze`` for the pure-Python implementation, ``cseabreeze``
        (or its ``seabreeze`` alias) for the native implementation, or
        ``auto`` to try both in that order.

    """

    def __init__(
        self,
        serial: str = "SR600415",
        integration_time_ms: float = 10.0,
        backend: str = "pyseabreeze",
        *,
        seabreeze_loader: SeaBreezeLoader | None = None,
    ):

        self.serial = str(serial)
        self.backend = _normalise_backend(backend)

        self.integration_time_ms = float(
            integration_time_ms
        )

        self._device = None
        self._active_backend: str | None = None
        self._list_devices: Callable[[], list[Any]] | None = None
        self._shutdown_backend: Callable[[], None] | None = None
        self._seabreeze_loader = seabreeze_loader or _load_seabreeze_backend

    _backend_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:

        return self._device is not None

    @property
    def active_backend(self) -> str | None:
        """Backend that owns the current connection, if connected."""

        return self._active_backend

    def connect(self):

        if self.connected:
            return

        candidates = (
            _AUTO_BACKENDS if self.backend == "auto" else (self.backend,)
        )
        failures: list[str] = []
        with self._backend_lock:
            for backend in candidates:
                shutdown_backend: Callable[[], None] | None = None
                try:
                    (
                        spectrometer_class,
                        list_devices,
                        shutdown_backend,
                    ) = self._seabreeze_loader(backend)
                    devices = list(list_devices())
                except Exception as exc:
                    _shutdown_seabreeze_backend(shutdown_backend, backend)
                    failures.append(f"{backend}: {exc}")
                    continue

                serials = [
                    str(device.serial_number)
                    for device in devices
                    if getattr(device, "serial_number", None) is not None
                ]
                logger.info(
                    "SeaBreeze backend %s found %d spectrometer(s): %s",
                    backend,
                    len(serials),
                    ", ".join(serials) or "none",
                )
                descriptor = next(
                    (
                        device
                        for device in devices
                        if str(getattr(device, "serial_number", "")) == self.serial
                    ),
                    None,
                )
                if descriptor is None:
                    found = ", ".join(serials) or "none"
                    failures.append(
                        f"{backend}: serial {self.serial!r} not found (found: {found})"
                    )
                    _shutdown_seabreeze_backend(shutdown_backend, backend)
                    continue

                device = None
                try:
                    device = spectrometer_class(descriptor)
                    self._device = device
                    self._active_backend = backend
                    self._list_devices = list_devices
                    self._shutdown_backend = shutdown_backend
                    self.set_integration_time(self.integration_time_ms)
                except Exception as exc:
                    self._device = None
                    self._active_backend = None
                    self._list_devices = None
                    self._shutdown_backend = None
                    if device is not None:
                        try:
                            device.close()
                        except Exception:
                            logger.exception(
                                "Failed to close Ocean spectrometer after a "
                                "connection error."
                            )
                    _shutdown_seabreeze_backend(shutdown_backend, backend)
                    failures.append(f"{backend}: {exc}")
                    continue

                logger.info(
                    "Connected to Ocean spectrometer %s using %s.",
                    self.serial,
                    backend,
                )
                return

        detail = "; ".join(failures) or "no backend attempts completed"
        raise RuntimeError(
            f"Could not connect to Ocean spectrometer {self.serial!r}. {detail}"
        )

    def info(self):
        """
        Return spectrometer information.
        """

        return {
            "name": "Spectrometer",
            "serial": self.serial,
            "connected": self.connected,
            "integration_time_ms": self.integration_time_ms,
            "configured_backend": self.backend,
            "active_backend": self.active_backend,
        }
    def disconnect(self):

        if not self.connected:
            return

        logger.info(
            "Disconnecting spectrometer..."
        )

        try:
            self._device.close()
        finally:
            self._device = None
            self._active_backend = None
            self._list_devices = None
            shutdown_backend = self._shutdown_backend
            self._shutdown_backend = None
            if shutdown_backend is not None:
                shutdown_backend()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_integration_time(
        self,
        integration_time_ms: float,
    ):
        """
        Set exposure time.
        """

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        self.integration_time_ms = float(
            integration_time_ms
        )

        self._device.integration_time_micros(
            int(
                self.integration_time_ms
                * 1000
            )
        )

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def acquire(
        self,
        *,
        averages: int = 1,
    ) -> Spectrum:
        """
        Acquire one spectrum.

        Parameters
        ----------
        averages
            Number of spectra to average.
        """

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        averages = max(
            1,
            int(averages),
        )

        wavelengths = np.asarray(
            self._device.wavelengths()
        )

        summed = None

        for _ in range(averages):

            counts = np.asarray(
                self._device.intensities(
                    correct_dark_counts=False,
                    correct_nonlinearity=False,
                ),
                dtype=float,
            )

            if summed is None:

                summed = counts

            else:

                summed += counts

        intensities = summed / averages

        return Spectrum(
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=self.integration_time_ms,
            serial=self.serial,
            averages=averages,
            dark_corrected=False,
            nonlinearity_corrected=False,
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def pixels(self) -> int:

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        return len(
            self._device.wavelengths()
        )

    def check_connection(self) -> bool:
        """Verify that the configured spectrometer is still USB-enumerated."""

        if not self.connected:
            raise RuntimeError("Spectrometer not connected.")
        if self._active_backend is None or self._list_devices is None:
            raise RuntimeError("Spectrometer connection has no active backend.")

        with self._backend_lock:
            detected_serials = {
                str(device.serial_number)
                for device in self._list_devices()
                if getattr(device, "serial_number", None) is not None
            }
        if self.serial not in detected_serials:
            found = ", ".join(sorted(detected_serials)) or "none"
            raise RuntimeError(
                f"Ocean spectrometer {self.serial!r} is no longer present "
                f"on USB (found: {found})."
            )
        return True

    @property
    def wavelength_range(self):

        if not self.connected:

            raise RuntimeError(
                "Spectrometer not connected."
            )

        wl = self._device.wavelengths()

        return (
            float(wl[0]),
            float(wl[-1]),
        )

    # ------------------------------------------------------------------

    def __enter__(self):

        self.connect()

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):

        self.disconnect()

        return False

    # ------------------------------------------------------------------

    def __repr__(self):

        if self.connected:

            lo, hi = self.wavelength_range

            return (
                f"<OceanSR "
                f"{self.serial} "
                f"{self.active_backend} "
                f"{self.pixels} px "
                f"{lo:.1f}-{hi:.1f} nm>"
            )

        return (
            f"<OceanSR "
            f"{self.serial} "
            f"(disconnected)>"
        )
