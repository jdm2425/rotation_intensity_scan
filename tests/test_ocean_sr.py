"""Operator-approved acquisition test for the configured spectrometer."""

from __future__ import annotations

from hardware.config import SPECTROMETER
from hardware.devices.spectrometer.ocean_sr import OceanSR


def main() -> None:
    spectrometer = OceanSR(
        serial=SPECTROMETER.serial,
        integration_time_ms=100.0,
    )

    print("Connecting...")
    spectrometer.connect()
    try:
        print("Connected. Acquiring spectrum...")
        result = spectrometer.acquire()
        print("Pixels:", len(result.wavelengths))
        print("First wavelength:", result.wavelengths[0])
        print("Last wavelength :", result.wavelengths[-1])
        print("Maximum counts:", result.intensities.max())
    finally:
        spectrometer.disconnect()

    print("SPECTROMETER TEST PASSED")


if __name__ == "__main__":
    main()
