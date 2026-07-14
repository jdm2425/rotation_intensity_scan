"""
Test the complete hardware stack.

This test exercises the HardwareManager exactly as experiment code
will use it.

Expected behaviour
------------------
- Connect both rotation stages
- Connect shutter
- Print device summary
- Move waveplate +2°
- Move waveplate back
- Move sample +5°
- Move sample back
- Close shutter
- Open shutter
- Disconnect everything
"""

from hardware.hardware_manager import HardwareManager


def main():

    with HardwareManager() as hw:

        print()
        print("========== Hardware Summary ==========")
        print(hw.summary())

        # -------------------------------------------------
        # Waveplate
        # -------------------------------------------------

        print()
        print("Testing waveplate...")

        start = hw.waveplate.position

        print(f"Start : {start:.4f}°")

        hw.waveplate.move_by(2)

        print(f"Moved : {hw.waveplate.position:.4f}°")

        hw.waveplate.move_to(start)

        print(f"Final : {hw.waveplate.position:.4f}°")

        # -------------------------------------------------
        # Sample stage
        # -------------------------------------------------

        print()
        print("Testing sample stage...")

        start = hw.sample.position

        print(f"Start : {start:.4f}°")

        hw.sample.move_by(5)

        print(f"Moved : {hw.sample.position:.4f}°")

        hw.sample.move_to(start)

        print(f"Final : {hw.sample.position:.4f}°")

        # -------------------------------------------------
        # Shutter
        # -------------------------------------------------

        print()
        print("Testing shutter...")

        hw.close_beam()
        print("Beam closed")

        hw.open_beam()
        print("Beam opened")

    print()
    print("======================================")
    print("HardwareManager test PASSED.")
    print("======================================")


if __name__ == "__main__":
    main()