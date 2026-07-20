"""Hardware-free smoke test for the common device lifecycle."""

from hardware.devices.base import HardwareDevice


class Dummy(HardwareDevice):
    def connect(self) -> None:
        self._set_connected(True)

    def disconnect(self) -> None:
        self._set_connected(False)


def main() -> None:
    device = Dummy("Dummy Device")
    assert not device.connected

    with device as connected_device:
        assert connected_device is device
        assert device.connected

    assert not device.connected
    print("BASE DEVICE TEST PASSED")


if __name__ == "__main__":
    main()
