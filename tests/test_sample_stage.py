from pylablib.devices import Thorlabs

stage = Thorlabs.KinesisMotor("55447814")

print("Device info:")
print(stage.get_device_info())

print()

print("Full info:")
print(stage.get_full_info())


print("Stage settings: ")
print(stage.get_settings())

print("Stage status: ")
print(stage.get_status())

