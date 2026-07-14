import logging

from hardware.config import HARDWARE
from hardware.devices.rotation.brushed_stage import RotationStage

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)

stage = RotationStage(
    name="Waveplate",
    serial=HARDWARE.waveplate_serial,
)

with stage:

    print(stage.info())

    start = stage.position

    stage.move_by(2)

    print(stage.position)

    stage.move_to(start)

    print(stage.position)