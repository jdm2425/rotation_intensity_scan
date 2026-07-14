from hardware.devices.spectrometer.ocean_sr import OceanSR

spec = OceanSR(
    serial="SR600415",
    integration_time_ms=100,
)

print("Connecting...")

spec.connect()

print("Connected.")

print("Acquiring spectrum...")

result = spec.acquire()

print()

print("Pixels:", len(result.wavelengths))

print("First wavelength:", result.wavelengths[0])

print("Last wavelength :", result.wavelengths[-1])

print("Maximum counts:", result.intensities.max())

spec.disconnect()

print()

print("Disconnected.")