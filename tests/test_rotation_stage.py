"""Operator-approved reversible motion test for the configured waveplate."""

from __future__ import annotations

import logging

from hardware.config import WAVEPLATE
from hardware.devices.rotation import RotationStage


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    stage = RotationStage(serial=WAVEPLATE.serial, name=WAVEPLATE.name)

    with stage:
        print(stage.info())
        start = stage.position
        try:
            stage.move_by(2.0)
            print(f"Moved to {stage.position:.4f} deg")
        finally:
            stage.move_to(start)
            print(f"Returned to {stage.position:.4f} deg")


if __name__ == "__main__":
    main()
