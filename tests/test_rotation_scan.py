from experiments.rotation_scan import RotationScan

scan = RotationScan(

    angles=[0, 5, 10, 15],

    test_mode=True,

)

results = scan.execute()

print()

print("=" * 60)

print("Collected", len(results), "spectra")

for point in results:

    print(
        f"{point['angle_deg']:5.1f}°",
        len(point["spectrum"].wavelengths),
        "pixels",
    )

print("=" * 60)