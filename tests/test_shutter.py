"""Operator-approved test of the configured beam shutter."""

from __future__ import annotations

import logging

from hardware.config import SHUTTER
from hardware.devices.shutter import BeamShutter


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    shutter = BeamShutter(name=SHUTTER.name, serial=SHUTTER.serial)

    with shutter:
        try:
            shutter.close()
            assert shutter.is_closed
            print(shutter.info())

            shutter.open()
            assert shutter.is_open
            print(shutter.info())
        finally:
            shutter.close()
            if not shutter.is_closed:
                raise RuntimeError("Shutter did not finish in the closed state.")

    print("SHUTTER TEST PASSED (final state verified closed)")


if __name__ == "__main__":
    main()
