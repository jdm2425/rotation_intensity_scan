from hardware.devices.baseOLD import HardwareDevice


class Dummy(HardwareDevice):

    def connect(self):

        print("Connecting")

        self._connected = True

    def disconnect(self):

        print("Disconnecting")

        self._connected = False


with Dummy("Dummy Device") as dev:

    print(dev)

print(dev)