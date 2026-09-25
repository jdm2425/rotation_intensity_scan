"""
live_spectrometer.py

Standalone live viewer for the Ocean SR spectrometer.

This utility does not connect to the rotation stages or beam shutter.

Keyboard controls
-----------------
Q / Escape
    Quit cleanly.

S
    Save the current spectrum as a compressed NPZ file.

+ / =
    Double the integration time.

-
    Halve the integration time.

A
    Toggle automatic y-axis scaling.

R
    Reset the plot limits.

B
    Capture the current raw spectrum as the background. This overwrites
    the single background file stored beside this module.

G
    Toggle background subtraction on or off.

X
    Enter exact x-axis limits directly in the plot window.

Y
    Enter exact y-axis limits directly in the plot window.

Usage
-----
Run with the default settings:

    python -m tools.live_spectrometer

Specify acquisition settings:

    python -m tools.live_spectrometer \
        --integration-time-ms 20 \
        --averages 3

Specify display limits:

    python -m tools.live_spectrometer \
        --x-min 350 \
        --x-max 800 \
        --y-min 0 \
        --y-max 50000

When y limits are omitted, autoscaling uses only the wavelengths in the
current visible x-axis range. The plot toolbar can therefore be used to
zoom into a harmonic while the live y scale follows that region. Press A
to freeze/unfreeze the y scale.
"""

from __future__ import annotations

import argparse
import inspect
from dataclasses import is_dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from hardware.devices.spectrometer.ocean_sr import OceanSR
from hardware.devices.spectrometer.spectrum import Spectrum


DEFAULT_SERIAL = "SR600415"
DEFAULT_INTEGRATION_TIME_MS = 10.0
DEFAULT_AVERAGES = 1
DEFAULT_REFRESH_INTERVAL_S = 0.05

MIN_INTEGRATION_TIME_MS = 0.01
MAX_INTEGRATION_TIME_MS = 60_000.0

DEFAULT_SATURATION_LEVEL = 65_535.0
DEFAULT_BACKGROUND_PATH = Path(__file__).with_name(
    "live_spectrometer_background.npz"
)


class LiveSpectrometer:
    """
    Interactive live spectrum viewer.
    """

    def __init__(
        self,
        *,
        spectrometer: OceanSR,
        integration_time_ms: float,
        averages: int,
        output_directory: str | Path,
        refresh_interval_s: float = DEFAULT_REFRESH_INTERVAL_S,
        saturation_level: float = DEFAULT_SATURATION_LEVEL,
        x_min: float | None = None,
        x_max: float | None = None,
        y_min: float | None = None,
        y_max: float | None = None,
        autoscale_y: bool = True,
        background_path: str | Path = DEFAULT_BACKGROUND_PATH,
    ) -> None:

        if integration_time_ms <= 0:
            raise ValueError(
                "Integration time must be greater than zero."
            )

        if averages < 1:
            raise ValueError(
                "Averages must be at least one."
            )

        if refresh_interval_s <= 0:
            raise ValueError(
                "Refresh interval must be greater than zero."
            )

        self.spectrometer = spectrometer

        self.integration_time_ms = float(
            integration_time_ms
        )

        self.averages = int(averages)

        self.output_directory = Path(
            output_directory
        )

        self.refresh_interval_s = float(
            refresh_interval_s
        )

        self.saturation_level = float(
            saturation_level
        )

        self.initial_x_limits = (
            x_min,
            x_max,
        )

        self.initial_y_limits = (
            y_min,
            y_max,
        )

        self.autoscale_y = bool(autoscale_y)
        self.background_path = Path(background_path)
        self.background_wavelengths: np.ndarray | None = None
        self.background_intensities: np.ndarray | None = None
        self.background_integration_time_ms: float | None = None
        self.background_enabled = False

        self.running = False
        self.connected = False

        self.current_spectrum: Spectrum | None = None
        self.current_raw_spectrum: Spectrum | None = None

        self.figure = None
        self.axes = None
        self.line = None
        self.status_text = None
        self.controls_text = None

        self._limit_entry_axis: str | None = None
        self._limit_entry_buffer = ""

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Connect, display live spectra, and disconnect cleanly.
        """

        print()
        print("=" * 60)
        print("Ocean SR live spectrometer")
        print("=" * 60)
        print(f"Serial:              {DEFAULT_SERIAL}")
        print(
            "Integration time:    "
            f"{self.integration_time_ms:.3f} ms"
        )
        print(f"Averages:            {self.averages}")
        print()
        print("Controls:")
        print("  Q / Escape    Quit")
        print("  S             Save spectrum")
        print("  + / =         Double integration time")
        print("  -             Halve integration time")
        print("  A             Toggle y-axis autoscaling")
        print("  R             Reset plot limits")
        print("  B             Capture/replace background")
        print("  G             Toggle background subtraction")
        print("  X             Set x-axis limits")
        print("  Y             Set y-axis limits")
        print("=" * 60)

        try:
            self._connect()

            self._apply_acquisition_settings()

            self._load_background()

            first_raw_spectrum = self._acquire()
            first_spectrum = self._apply_background(first_raw_spectrum)

            self.current_raw_spectrum = first_raw_spectrum
            self.current_spectrum = first_spectrum

            self._create_plot(first_spectrum)

            self.running = True

            while (
                self.running
                and self.figure is not None
                and plt.fignum_exists(
                    self.figure.number
                )
            ):
                raw_spectrum = self._acquire()
                spectrum = self._apply_background(raw_spectrum)

                self.current_raw_spectrum = raw_spectrum
                self.current_spectrum = spectrum

                self._update_plot(spectrum)

                plt.pause(
                    self.refresh_interval_s
                )

        except KeyboardInterrupt:
            print("\nKeyboard interrupt received.")

        finally:
            self.running = False

            self._disconnect()

            if self.figure is not None:
                plt.close(self.figure)

            print("Live spectrometer closed cleanly.")

    # ------------------------------------------------------------------
    # Hardware connection
    # ------------------------------------------------------------------

    def _connect(self) -> None:

        if self.connected:
            return

        print("Connecting to spectrometer...")

        self.spectrometer.connect()

        self.connected = True

        print("Spectrometer connected.")

    def _disconnect(self) -> None:

        if not self.connected:
            return

        print("Disconnecting spectrometer...")

        try:
            disconnect = getattr(
                self.spectrometer,
                "disconnect",
                None,
            )

            if callable(disconnect):
                disconnect()

            else:
                close = getattr(
                    self.spectrometer,
                    "close",
                    None,
                )

                if callable(close):
                    close()

        finally:
            self.connected = False

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def _acquire(self) -> Spectrum:
        """
        Acquire one spectrum using the current settings.
        """

        acquire_method = self.spectrometer.acquire

        parameters = inspect.signature(
            acquire_method
        ).parameters

        keyword_arguments: dict[str, Any] = {}

        if "integration_time_ms" in parameters:
            keyword_arguments[
                "integration_time_ms"
            ] = self.integration_time_ms

        if "averages" in parameters:
            keyword_arguments[
                "averages"
            ] = self.averages

        spectrum = acquire_method(
            **keyword_arguments
        )

        if not isinstance(spectrum, Spectrum):
            raise TypeError(
                "OceanSR.acquire() must return a Spectrum "
                f"object, not {type(spectrum).__name__}."
            )

        wavelengths = np.asarray(
            spectrum.wavelengths
        )

        intensities = np.asarray(
            spectrum.intensities
        )

        if wavelengths.ndim != 1:
            raise ValueError(
                "Spectrum wavelengths must be one-dimensional."
            )

        if intensities.ndim != 1:
            raise ValueError(
                "Spectrum intensities must be one-dimensional."
            )

        if wavelengths.shape != intensities.shape:
            raise ValueError(
                "Spectrum wavelengths and intensities "
                "must have matching shapes."
            )

        return spectrum

    def _apply_background(self, spectrum: Spectrum) -> Spectrum:
        """Return a background-subtracted copy when subtraction is enabled."""

        if not self.background_enabled:
            return spectrum

        if (
            self.background_wavelengths is None
            or self.background_intensities is None
            or self.background_integration_time_ms is None
        ):
            return spectrum

        wavelengths = np.asarray(spectrum.wavelengths, dtype=float)

        if (
            wavelengths.shape != self.background_wavelengths.shape
            or not np.allclose(wavelengths, self.background_wavelengths)
        ):
            print("Background disabled: wavelength calibration does not match.")
            self.background_enabled = False
            return spectrum

        scale = (
            float(spectrum.integration_time_ms)
            / self.background_integration_time_ms
        )

        corrected = np.asarray(spectrum.intensities, dtype=float) - (
            self.background_intensities * scale
        )

        return replace(spectrum, intensities=corrected)

    def _load_background(self) -> bool:
        """Load the persistent background if one has previously been saved."""

        if not self.background_path.exists():
            print(f"No saved background found at: {self.background_path}")
            return False

        try:
            with np.load(self.background_path, allow_pickle=False) as arrays:
                wavelengths = np.asarray(arrays["wavelengths"], dtype=float)
                intensities = np.asarray(arrays["intensities"], dtype=float)
                integration_time_ms = float(
                    np.asarray(arrays["integration_time_ms"]).reshape(-1)[0]
                )

            if wavelengths.ndim != 1 or wavelengths.shape != intensities.shape:
                raise ValueError("background arrays must be matching 1D arrays")
            if integration_time_ms <= 0:
                raise ValueError("background integration time must be positive")

        except (OSError, KeyError, TypeError, ValueError) as error:
            print(f"Could not load background {self.background_path}: {error}")
            return False

        self.background_wavelengths = wavelengths
        self.background_intensities = intensities
        self.background_integration_time_ms = integration_time_ms
        print(f"Background available (subtraction OFF): {self.background_path}")
        return True

    def capture_background(self) -> Path | None:
        """Save the current raw spectrum as the single persistent background."""

        spectrum = self.current_raw_spectrum
        if spectrum is None:
            print("No raw spectrum is available to use as a background.")
            return None

        wavelengths = np.asarray(spectrum.wavelengths, dtype=float).copy()
        intensities = np.asarray(spectrum.intensities, dtype=float).copy()
        integration_time_ms = float(spectrum.integration_time_ms)

        self.background_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self.background_path,
            wavelengths=wavelengths,
            intensities=intensities,
            integration_time_ms=np.asarray(integration_time_ms, dtype=float),
        )

        self.background_wavelengths = wavelengths
        self.background_intensities = intensities
        self.background_integration_time_ms = integration_time_ms
        self.background_enabled = True
        print(f"Background saved and enabled: {self.background_path}")
        return self.background_path

    def _apply_acquisition_settings(self) -> None:
        """
        Apply integration time and averaging when the driver
        exposes setter methods or writable properties.

        Some OceanSR implementations instead accept these settings
        directly in acquire(); both forms are supported.
        """

        self._set_driver_value(
            method_names=(
                "set_integration_time_ms",
                "set_integration_time",
            ),
            property_names=(
                "integration_time_ms",
            ),
            value=self.integration_time_ms,
        )

        self._set_driver_value(
            method_names=(
                "set_averages",
                "set_average_count",
            ),
            property_names=(
                "averages",
                "average_count",
            ),
            value=self.averages,
        )

    def _set_driver_value(
        self,
        *,
        method_names: tuple[str, ...],
        property_names: tuple[str, ...],
        value,
    ) -> bool:
        """
        Set a driver value using its first available public API.
        """

        for method_name in method_names:
            method = getattr(
                self.spectrometer,
                method_name,
                None,
            )

            if callable(method):
                method(value)
                return True

        for property_name in property_names:
            if not hasattr(
                self.spectrometer,
                property_name,
            ):
                continue

            try:
                setattr(
                    self.spectrometer,
                    property_name,
                    value,
                )
                return True

            except (
                AttributeError,
                TypeError,
            ):
                continue

        return False

    # ------------------------------------------------------------------
    # Plot creation
    # ------------------------------------------------------------------

    def _create_plot(
        self,
        spectrum: Spectrum,
    ) -> None:

        plt.ion()

        self.figure, self.axes = plt.subplots()

        self.figure.canvas.manager.set_window_title(
            "Ocean SR Live Spectrum"
        )

        wavelengths = np.asarray(
            spectrum.wavelengths,
            dtype=float,
        )

        intensities = np.asarray(
            spectrum.intensities,
            dtype=float,
        )

        (self.line,) = self.axes.plot(
            wavelengths,
            intensities,
        )

        self.axes.set_xlabel(
            "Wavelength (nm)"
        )

        self.axes.set_ylabel(
            "Counts"
        )

        self.axes.grid(
            visible=True,
            alpha=0.25,
        )

        self.status_text = self.axes.text(
            0.01,
            0.99,
            "",
            transform=self.axes.transAxes,
            horizontalalignment="left",
            verticalalignment="top",
        )

        self.controls_text = self.figure.text(
            0.5,
            0.985,
            "S save   +/- integration   A autoscale   X/Y limits   "
            "B set background   G toggle background   R reset   Q quit",
            horizontalalignment="center",
            verticalalignment="top",
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": "0.75",
                "alpha": 0.9,
            },
        )

        self.figure.canvas.mpl_connect(
            "key_press_event",
            self._on_key_press,
        )

        self.figure.canvas.mpl_connect(
            "close_event",
            self._on_close,
        )

        self._reset_plot_limits(
            spectrum
        )

        self._update_plot(
            spectrum
        )

        self.figure.tight_layout(
            rect=(0.0, 0.0, 1.0, 0.94)
        )

        self.figure.show()

    def _update_plot(
        self,
        spectrum: Spectrum,
    ) -> None:

        if (
            self.axes is None
            or self.line is None
            or self.figure is None
        ):
            return

        wavelengths = np.asarray(
            spectrum.wavelengths,
            dtype=float,
        )

        intensities = np.asarray(
            spectrum.intensities,
            dtype=float,
        )

        self.line.set_data(
            wavelengths,
            intensities,
        )

        if self.autoscale_y:
            self._autoscale_y(
                wavelengths,
                intensities
            )

        peak_counts = float(
            np.max(intensities)
        )

        peak_index = int(
            np.argmax(intensities)
        )

        peak_wavelength_nm = float(
            wavelengths[peak_index]
        )

        saturated = (
            peak_counts >= self.saturation_level
        )

        saturation_status = (
            "SATURATED"
            if saturated
            else "OK"
        )

        displayed_integration_time = getattr(
            spectrum,
            "integration_time_ms",
            self.integration_time_ms,
        )

        displayed_averages = getattr(
            spectrum,
            "averages",
            self.averages,
        )

        self.status_text.set_text(
            "\n".join(
                (
                    "Integration: "
                    f"{float(displayed_integration_time):.3f} ms",
                    f"Averages: {int(displayed_averages)}",
                    f"Peak: {peak_counts:.1f} counts",
                    "Peak wavelength: "
                    f"{peak_wavelength_nm:.2f} nm",
                    f"Detector: {saturation_status}",
                    "Background: "
                    f"{'ON' if self.background_enabled else 'OFF'}"
                    f" ({'saved' if self.background_intensities is not None else 'none'})",
                )
            )
        )

        if self._limit_entry_axis is None:
            self.axes.set_title(
                "Ocean SR Live Spectrum"
            )

        self.figure.canvas.draw_idle()

    def _autoscale_y(
        self,
        wavelengths: np.ndarray,
        intensities: np.ndarray,
    ) -> None:

        if self.axes is None:
            return

        x_limit_1, x_limit_2 = self.axes.get_xlim()
        x_min = min(x_limit_1, x_limit_2)
        x_max = max(x_limit_1, x_limit_2)

        visible = (
            np.isfinite(wavelengths)
            & np.isfinite(intensities)
            & (wavelengths >= x_min)
            & (wavelengths <= x_max)
        )

        finite_values = intensities[visible]

        if finite_values.size == 0:
            return

        minimum = float(
            np.min(finite_values)
        )

        maximum = float(
            np.max(finite_values)
        )

        if maximum <= minimum:
            padding = max(
                abs(maximum) * 0.05,
                1.0,
            )

        else:
            padding = (
                maximum - minimum
            ) * 0.08

        lower_limit = min(
            0.0,
            minimum - padding,
        )

        upper_limit = (
            maximum + padding
        )

        self.axes.set_ylim(
            lower_limit,
            upper_limit,
        )

    def _reset_plot_limits(
        self,
        spectrum: Spectrum | None = None,
    ) -> None:

        if self.axes is None:
            return

        spectrum = (
            spectrum
            or self.current_spectrum
        )

        if spectrum is None:
            return

        wavelengths = np.asarray(
            spectrum.wavelengths,
            dtype=float,
        )

        intensities = np.asarray(
            spectrum.intensities,
            dtype=float,
        )

        x_min, x_max = self.initial_x_limits

        self.axes.set_xlim(
            float(
                np.min(wavelengths)
                if x_min is None
                else x_min
            ),
            float(
                np.max(wavelengths)
                if x_max is None
                else x_max
            ),
        )

        y_min, y_max = self.initial_y_limits

        if (
            y_min is not None
            or y_max is not None
        ):
            current_min = float(
                np.min(intensities)
            )

            current_max = float(
                np.max(intensities)
            )

            if current_max <= current_min:
                current_max = current_min + 1.0

            self.axes.set_ylim(
                current_min
                if y_min is None
                else y_min,
                current_max
                if y_max is None
                else y_max,
            )

            self.autoscale_y = False

        else:
            self.autoscale_y = True

            self._autoscale_y(
                wavelengths,
                intensities
            )

        self.figure.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Keyboard controls
    # ------------------------------------------------------------------

    def _on_key_press(
        self,
        event,
    ) -> None:

        key = (
            event.key or ""
        ).lower()

        if self._limit_entry_axis is not None:
            self._handle_limit_entry_key(key)
            return

        if key in {
            "q",
            "escape",
        }:
            self.running = False
            return

        if key == "s":
            self.save_current_spectrum()
            return

        if key == "b":
            self.capture_background()
            return

        if key == "g":
            if self.background_intensities is None:
                print("No background is available. Press B to capture one.")
            else:
                self.background_enabled = not self.background_enabled
                print(
                    "Background subtraction: "
                    f"{'ON' if self.background_enabled else 'OFF'}"
                )
            return

        if key == "x":
            self._start_limit_entry(axis="x")
            return

        if key == "y":
            self._start_limit_entry(axis="y")
            return

        if key in {
            "+",
            "=",
        }:
            self._change_integration_time(
                factor=2.0
            )
            return

        if key in {
            "-",
            "_",
        }:
            self._change_integration_time(
                factor=0.5
            )
            return

        if key == "a":
            self.autoscale_y = (
                not self.autoscale_y
            )

            print(
                "Y-axis autoscaling: "
                f"{'ON' if self.autoscale_y else 'OFF'}"
            )

            if (
                self.autoscale_y
                and self.current_spectrum is not None
            ):
                self._autoscale_y(
                    np.asarray(
                        self.current_spectrum.wavelengths,
                        dtype=float,
                    ),
                    np.asarray(
                        self.current_spectrum.intensities,
                        dtype=float,
                    )
                )

            return

        if key == "r":
            self._reset_plot_limits()
            print("Plot limits reset.")

    def _start_limit_entry(self, *, axis: str) -> None:
        """Start capturing a pair of numeric limits from plot key events."""

        self._limit_entry_axis = axis
        self._limit_entry_buffer = ""
        self._show_limit_entry()

    def _handle_limit_entry_key(self, key: str) -> None:
        """Handle one key while an in-plot limit entry is active."""

        if key == "escape":
            self._finish_limit_entry("Limit entry cancelled.")
            return

        if key in {"enter", "return"}:
            self._apply_limit_entry()
            return

        if key == "backspace":
            self._limit_entry_buffer = self._limit_entry_buffer[:-1]
        elif key in {" ", "space", ","}:
            if self._limit_entry_buffer and not self._limit_entry_buffer.endswith(" "):
                self._limit_entry_buffer += " "
        elif len(key) == 1 and key in "0123456789.-+e":
            self._limit_entry_buffer += key

        self._show_limit_entry()

    def _show_limit_entry(self) -> None:
        if self.axes is None or self.figure is None:
            return

        axis = str(self._limit_entry_axis).upper()
        entered = self._limit_entry_buffer or "_"
        self.axes.set_title(
            f"Set {axis} limits: {entered}  "
            "(type MIN MAX, Enter apply, Esc cancel)"
        )
        self.figure.canvas.draw_idle()

    def _apply_limit_entry(self) -> None:
        axis = self._limit_entry_axis
        parts = self._limit_entry_buffer.replace(",", " ").split()

        try:
            if len(parts) != 2:
                raise ValueError("enter exactly two numbers: MIN MAX")
            lower, upper = map(float, parts)
            if not np.isfinite(lower) or not np.isfinite(upper):
                raise ValueError("limits must be finite numbers")
            if upper <= lower:
                raise ValueError("maximum must be greater than minimum")
        except ValueError as error:
            self._finish_limit_entry(f"Invalid limits: {error}")
            return

        if self.axes is None or self.current_spectrum is None:
            self._finish_limit_entry("Limit entry cancelled.")
            return

        if axis == "x":
            self.axes.set_xlim(lower, upper)
            if self.autoscale_y:
                self._autoscale_y(
                    np.asarray(self.current_spectrum.wavelengths, dtype=float),
                    np.asarray(self.current_spectrum.intensities, dtype=float),
                )
        else:
            self.axes.set_ylim(lower, upper)
            self.autoscale_y = False

        self._finish_limit_entry(
            f"{str(axis).upper()} limits set to {lower:g}, {upper:g}."
        )

    def _finish_limit_entry(self, message: str) -> None:
        self._limit_entry_axis = None
        self._limit_entry_buffer = ""
        print(message)
        if self.axes is not None:
            self.axes.set_title("Ocean SR Live Spectrum")
        if self.figure is not None:
            self.figure.canvas.draw_idle()

    def _on_close(
        self,
        _event,
    ) -> None:

        self.running = False

    def _change_integration_time(
        self,
        *,
        factor: float,
    ) -> None:

        new_value = (
            self.integration_time_ms
            * factor
        )

        new_value = min(
            max(
                new_value,
                MIN_INTEGRATION_TIME_MS,
            ),
            MAX_INTEGRATION_TIME_MS,
        )

        self.integration_time_ms = (
            new_value
        )

        self._apply_acquisition_settings()

        print(
            "Integration time changed to "
            f"{self.integration_time_ms:.3f} ms"
        )

    # ------------------------------------------------------------------
    # Manual saving
    # ------------------------------------------------------------------

    def save_current_spectrum(
        self,
    ) -> Path | None:
        """
        Save the currently displayed spectrum.
        """

        spectrum = self.current_spectrum

        if spectrum is None:
            print(
                "No spectrum is available to save."
            )
            return None

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        filename = (
            f"live_spectrum_{timestamp}.npz"
        )

        path = (
            self.output_directory
            / filename
        )

        np.savez_compressed(
            path,
            wavelengths=np.asarray(
                spectrum.wavelengths,
                dtype=float,
            ),
            intensities=np.asarray(
                spectrum.intensities,
                dtype=float,
            ),
            integration_time_ms=np.asarray(
                spectrum.integration_time_ms,
                dtype=float,
            ),
            serial=np.asarray(
                spectrum.serial,
                dtype=str,
            ),
            averages=np.asarray(
                spectrum.averages,
                dtype=int,
            ),
            dark_corrected=np.asarray(
                spectrum.dark_corrected,
                dtype=bool,
            ),
            nonlinearity_corrected=np.asarray(
                spectrum.nonlinearity_corrected,
                dtype=bool,
            ),
            timestamp=np.asarray(
                getattr(
                    spectrum,
                    "timestamp",
                    datetime.now().timestamp(),
                ),
                dtype=float,
            ),
        )

        print(f"Spectrum saved: {path}")

        return path


# ======================================================================
# OceanSR construction
# ======================================================================


def create_spectrometer(
    serial: str,
    backend: str | None = None,
) -> OceanSR:
    """
    Construct OceanSR while supporting the common constructor forms
    used during development of this project.

    Supported forms include:

        OceanSR(serial="SR...")
        OceanSR(serial_number="SR...")
        OceanSR("SR...")
        OceanSR(config)
    """

    parameters = inspect.signature(
        OceanSR
    ).parameters

    if "serial" in parameters:
        arguments = {"serial": serial}
        config = _find_spectrometer_config()
        selected_backend = backend
        if selected_backend is None and config is not None:
            selected_backend = getattr(config, "backend", None)
        if "backend" in parameters and selected_backend is not None:
            arguments["backend"] = str(selected_backend)
        return OceanSR(**arguments)

    if "serial_number" in parameters:
        return OceanSR(
            serial_number=serial
        )

    if "config" in parameters:
        config = _find_spectrometer_config()

        if config is None:
            raise RuntimeError(
                "OceanSR expects a config object, but no "
                "spectrometer configuration was found in "
                "hardware.config."
            )

        config = _replace_config_serial(
            config,
            serial,
        )

        return OceanSR(
            config=config
        )

    try:
        return OceanSR(serial)

    except TypeError as error:
        raise TypeError(
            "Could not construct OceanSR. Expected its constructor "
            "to accept serial, serial_number, a positional serial, "
            "or a spectrometer config object."
        ) from error


def _find_spectrometer_config():
    """
    Locate the project's configured spectrometer without imposing
    one exact hardware.config layout.
    """

    try:
        import hardware.config as hardware_config

    except ImportError:
        return None

    direct_names = (
        "SPECTROMETER",
        "SPECTROMETER_CONFIG",
    )

    for name in direct_names:
        value = getattr(
            hardware_config,
            name,
            None,
        )

        if value is not None:
            return value

    hardware = getattr(
        hardware_config,
        "HARDWARE",
        None,
    )

    if hardware is not None:
        value = getattr(
            hardware,
            "spectrometer",
            None,
        )

        if value is not None:
            return value

    return None


def _replace_config_serial(
    config,
    serial: str,
):
    """
    Return a config object using the requested serial when possible.
    """

    if is_dataclass(config):
        fields = getattr(
            config,
            "__dataclass_fields__",
            {},
        )

        if "serial" in fields:
            return replace(
                config,
                serial=serial,
            )

        if "serial_number" in fields:
            return replace(
                config,
                serial_number=serial,
            )

    return config


# ======================================================================
# Command-line interface
# ======================================================================


def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Display a continuously updating Ocean SR spectrum."
        )
    )

    parser.add_argument(
        "--serial",
        default=DEFAULT_SERIAL,
        help=(
            "Ocean SR serial number. "
            f"Default: {DEFAULT_SERIAL}"
        ),
    )

    parser.add_argument(
        "--integration-time-ms",
        type=float,
        default=DEFAULT_INTEGRATION_TIME_MS,
        help=(
            "Initial integration time in milliseconds. "
            f"Default: {DEFAULT_INTEGRATION_TIME_MS}"
        ),
    )

    parser.add_argument(
        "--backend",
        choices=("pyseabreeze", "cseabreeze", "seabreeze", "auto"),
        default=None,
        help=(
            "SeaBreeze implementation. Default: hardware.config "
            "SPECTROMETER.backend (currently pyseabreeze)."
        ),
    )

    parser.add_argument(
        "--averages",
        type=int,
        default=DEFAULT_AVERAGES,
        help=(
            "Number of spectra to average. "
            f"Default: {DEFAULT_AVERAGES}"
        ),
    )

    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path(
            "results"
        ) / "live_spectrometer",
        help=(
            "Directory used when S is pressed. "
            "Default: results/live_spectrometer"
        ),
    )

    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=DEFAULT_REFRESH_INTERVAL_S,
        help=(
            "Minimum pause between plot updates in seconds. "
            f"Default: {DEFAULT_REFRESH_INTERVAL_S}"
        ),
    )

    parser.add_argument(
        "--x-min",
        type=float,
        default=None,
        help="Initial minimum displayed wavelength.",
    )

    parser.add_argument(
        "--x-max",
        type=float,
        default=None,
        help="Initial maximum displayed wavelength.",
    )

    parser.add_argument(
        "--y-min",
        type=float,
        default=None,
        help="Initial minimum displayed count value.",
    )

    parser.add_argument(
        "--y-max",
        type=float,
        default=None,
        help="Initial maximum displayed count value.",
    )

    parser.add_argument(
        "--saturation-level",
        type=float,
        default=DEFAULT_SATURATION_LEVEL,
        help=(
            "Count threshold used for the saturation warning. "
            f"Default: {DEFAULT_SATURATION_LEVEL}"
        ),
    )

    return parser.parse_args()


def main() -> None:

    arguments = parse_arguments()

    spectrometer = create_spectrometer(
        arguments.serial,
        backend=arguments.backend,
    )

    viewer = LiveSpectrometer(
        spectrometer=spectrometer,
        integration_time_ms=(
            arguments.integration_time_ms
        ),
        averages=arguments.averages,
        output_directory=(
            arguments.output_directory
        ),
        refresh_interval_s=(
            arguments.refresh_interval
        ),
        saturation_level=(
            arguments.saturation_level
        ),
        x_min=arguments.x_min,
        x_max=arguments.x_max,
        y_min=arguments.y_min,
        y_max=arguments.y_max,
        autoscale_y=(
            arguments.y_min is None
            and arguments.y_max is None
        ),
    )

    viewer.run()


if __name__ == "__main__":
    main()
