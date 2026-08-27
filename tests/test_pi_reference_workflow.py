"""Hardware-free regression for explicit PI reference-switch recovery."""

from hardware.devices.linear.pi_stage import PIStageConfig, PILinearStage
from tests.test_pi_linear_stage import FakeClock, FakeGCSDevice


def main() -> None:
    fake = FakeGCSDevice()
    fake.referenced = False
    fake.motor_enabled = False
    fake.servo_enabled = False
    clock = FakeClock()
    stage = PILinearStage(
        PIStageConfig(configured_velocity_mm_s=None),
        gcs_device=fake,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    stage.connect()
    snapshot = stage.reference_to_switch()
    assert snapshot.referenced is True
    assert ("EAX", "1", True) in fake.commands
    assert ("SVO", "1", True) not in fake.commands
    assert ("FRF", "1") in fake.commands
    print("PI REFERENCE WORKFLOW TEST PASSED")


if __name__ == "__main__":
    main()
