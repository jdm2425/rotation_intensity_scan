import numpy as np

from hardware.devices.spectrometer.spectrum import Spectrum
from analysis.measurement import Measurement


def create_fake_measurement(index: int) -> Measurement:
    """
    Create a fake measurement for round-trip testing.
    """

    wavelengths = np.linspace(
        200,
        900,
        2048,
    )

    intensities = (
        np.random.random(2048) * 4000
        + index * 100
    )

    spectrum = Spectrum(
        wavelengths=wavelengths,
        intensities=intensities,
        integration_time_ms=10.0,
        serial="SR600415",
        averages=1,
        dark_corrected=False,
        nonlinearity_corrected=False,
    )

    measurement = Measurement(
        timestamp=float(index),

        waveplate_angle_deg=index * 5.0,

        sample_angle_deg=index * 10.0,

        power_mw=100.0,

        fluence_mj_cm2=0.25,

        intensity_w_cm2=1.2e8,

        spectrum=spectrum,
    )

    measurement.compute_statistics()

    return measurement