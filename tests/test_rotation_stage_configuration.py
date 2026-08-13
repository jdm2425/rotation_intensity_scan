from __future__ import annotations

from collections import namedtuple
from unittest.mock import patch

from hardware.devices.rotation import RotationStage


Velocity = namedtuple(
    "Velocity",
    ("min_velocity", "acceleration", "max_velocity"),
)


class FakeKinesisMotor:
    last_instance = None

    def __init__(self, serial: str, *, scale: str) -> None:
        self.serial = serial
        self.scale = scale
        self.velocity_calls: list[float] = []
        self.closed = False
        FakeKinesisMotor.last_instance = self

    def setup_velocity(self, *, max_velocity: float):
        self.velocity_calls.append(float(max_velocity))
        return Velocity(0.0, 10.0, float(max_velocity))

    def close(self) -> None:
        self.closed = True


def test_configured_rotation_velocity_is_applied_and_bounded() -> None:
    with patch(
        "hardware.devices.rotation.rotation_stage.Thorlabs.KinesisMotor",
        FakeKinesisMotor,
    ):
        stage = RotationStage(
            serial="fake",
            maximum_velocity_deg_s=25.0,
        )
        stage.connect()
        fake = FakeKinesisMotor.last_instance
        assert fake.velocity_calls == [25.0]
        stage.disconnect()
        assert fake.closed

    try:
        RotationStage(serial="fake", maximum_velocity_deg_s=25.1)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected PRM1-Z8 velocity above 25 deg/s to fail.")


if __name__ == "__main__":
    test_configured_rotation_velocity_is_applied_and_bounded()
    print("ROTATION STAGE CONFIGURATION TEST PASSED")
