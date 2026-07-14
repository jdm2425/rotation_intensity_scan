import logging

from hardware.config import HARDWARE
from hardware.devices.shutter import BeamShutter

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)

shutter = BeamShutter(
    name="Beam Shutter",
    serial=HARDWARE.shutter_serial,
)

with shutter:

    print(shutter.info())

    shutter.close()

    print(shutter.info())

    shutter.open()

    print(shutter.info())

    shutter.toggle()

    print(shutter.info())

    shutter.toggle()

    print(shutter.info())