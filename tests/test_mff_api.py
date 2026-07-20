"""Operator-approved low-level Kinesis shutter diagnostic.

This intentionally bypasses :class:`BeamShutter` to diagnose the vendor API.
Normal code and normal shutter tests must use the project driver instead.
"""

from __future__ import annotations

from hardware.config import SHUTTER


def main() -> None:
    from pylablib.devices import Thorlabs

    device = Thorlabs.MFF(SHUTTER.serial)
    try:
        print("Initial status:", device.get_status())
        device.move_to_state(1)  # Project mapping: 1 = beam closed.
        device.wait_for_status(
            ["moving_fw", "moving_bk"],
            enabled=False,
            timeout=5.0,
            period=0.05,
        )
        print("Closed status:", device.get_status())
    finally:
        try:
            device.move_to_state(1)
            device.wait_for_status(
                ["moving_fw", "moving_bk"],
                enabled=False,
                timeout=5.0,
                period=0.05,
            )
        finally:
            device.close()

    print("LOW-LEVEL MFF TEST PASSED (final command was close)")


if __name__ == "__main__":
    main()
