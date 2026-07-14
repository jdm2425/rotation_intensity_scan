from pylablib.devices import Thorlabs

mff = Thorlabs.MFF("37008491")

print(mff.get_status())

print("Next command:")

mff.move_to_state(0)

import time
time.sleep(0.2)

print(mff.get_status())

print("Next command:")

time.sleep(1)

print(mff.get_status())