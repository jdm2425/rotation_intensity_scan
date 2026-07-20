"""Hardware-free regression tests for the reusable PI linear-stage driver."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time
from types import SimpleNamespace
import unittest

import hardware.devices.linear.pi_stage as pi_stage_module
from hardware.devices.linear.pi_stage import (
    PILinearStage,
    PIStageConfig,
    PIStageIdentityError,
    PIStageLimitError,
    PIStageMotionError,
    PIStagePositionError,
    PIStageProtocolError,
    PIStageStateError,
    PIStageTimeoutError,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration_s: float) -> None:
        self.now += float(duration_s)


class FakeGCSDevice:
    """Small GCS2-shaped fake; it never imports or accesses PI hardware."""

    def __init__(
        self,
        *,
        identity: str = (
            "Physik Instrumente (PI), C-891.120200, "
            "S/N 118054611, FW 1.0\n"
        ),
        axes: tuple[str, ...] = ("1",),
    ) -> None:
        self.identity = identity
        self.axes = axes
        self.stage_assignment = "V-408.132020"
        self.motor_enabled = True
        self.servo_enabled = True
        self.referenced = True
        self.live_min_mm = -13.0
        self.live_max_mm = 13.0
        self.position_mm = 0.0
        self.target_mm = 0.0
        self.on_target = True
        self.velocity_mm_s = 1.0
        self.auto_update_position = True
        self.ont_responses: deque[bool] = deque()
        self.unsupported_queries: set[str] = set()
        self.query_errors: dict[str, Exception] = {}
        self.mov_error: Exception | None = None
        self.vel_error: Exception | None = None
        self.ignore_velocity_command = False
        self.calls: list[tuple] = []
        self.commands: list[tuple] = []
        self.close_count = 0

    def ConnectUSB(self, serialnum: str) -> None:
        self.calls.append(("ConnectUSB", serialnum))

    def CloseConnection(self) -> None:
        self.calls.append(("CloseConnection",))
        self.close_count += 1

    def qIDN(self) -> str:
        self.calls.append(("qIDN",))
        return self.identity

    def qSAI(self) -> list[str]:
        self.calls.append(("qSAI",))
        return list(self.axes)

    def qCST(self, axis: str) -> dict[str, str]:
        return self._query("qCST", axis, self.stage_assignment)

    def qEAX(self, axis: str) -> dict[str, bool]:
        return self._query("qEAX", axis, self.motor_enabled)

    def qSVO(self, axis: str) -> dict[str, bool]:
        return self._query("qSVO", axis, self.servo_enabled)

    def qFRF(self, axis: str) -> dict[str, bool]:
        return self._query("qFRF", axis, self.referenced)

    def qTMN(self, axis: str) -> dict[str, float]:
        return self._query("qTMN", axis, self.live_min_mm)

    def qTMX(self, axis: str) -> dict[str, float]:
        return self._query("qTMX", axis, self.live_max_mm)

    def qPOS(self, axis: str) -> dict[str, float]:
        return self._query("qPOS", axis, self.position_mm)

    def qMOV(self, axis: str) -> dict[str, float]:
        return self._query("qMOV", axis, self.target_mm)

    def qONT(self, axis: str) -> dict[str, bool]:
        if self.ont_responses:
            response = self.ont_responses.popleft()
            if response and self.auto_update_position:
                self.position_mm = self.target_mm
            self.on_target = response
        return self._query("qONT", axis, self.on_target)

    def qVEL(self, axis: str) -> dict[str, float]:
        return self._query("qVEL", axis, self.velocity_mm_s)

    def EAX(self, axis: str, value: bool) -> None:
        self.calls.append(("EAX", axis, value))
        self.commands.append(("EAX", axis, value))
        self.motor_enabled = bool(value)

    def SVO(self, axis: str, value: bool) -> None:
        self.calls.append(("SVO", axis, value))
        self.commands.append(("SVO", axis, value))
        self.servo_enabled = bool(value)

    def VEL(self, axis: str, value: float) -> None:
        self.calls.append(("VEL", axis, value))
        self.commands.append(("VEL", axis, value))
        if self.vel_error is not None:
            raise self.vel_error
        if not self.ignore_velocity_command:
            self.velocity_mm_s = float(value)

    def MOV(self, axis: str, value: float) -> None:
        self.calls.append(("MOV", axis, value))
        self.commands.append(("MOV", axis, value))
        if self.mov_error is not None:
            raise self.mov_error
        self.target_mm = float(value)
        self.on_target = False

    def HLT(self, axis: str, noraise: bool = False) -> None:
        self.calls.append(("HLT", axis, noraise))
        self.commands.append(("HLT", axis, noraise))
        self.on_target = True

    def _query(self, name: str, axis: str, value):
        self.calls.append((name, axis))
        if name in self.unsupported_queries:
            raise RuntimeError(f"{name} is not supported by fake firmware")
        if name in self.query_errors:
            raise self.query_errors[name]
        return {axis: value}


def connected_stage(
    fake: FakeGCSDevice | None = None,
    *,
    config: PIStageConfig | None = None,
    clock: FakeClock | None = None,
) -> tuple[PILinearStage, FakeGCSDevice]:
    device = fake or FakeGCSDevice()
    stage = PILinearStage(
        config=config,
        gcs_device=device,
        monotonic=clock.monotonic if clock else time.monotonic,
        sleep=clock.sleep if clock else time.sleep,
    )
    stage.connect()
    return stage, device


class PIStageConnectionTests(unittest.TestCase):
    def test_import_is_lazy_and_fake_connect_snapshot_is_read_only(self) -> None:
        self.assertNotIn("pipython", pi_stage_module.__dict__)
        fake = FakeGCSDevice()
        families: list[str] = []

        def factory(family: str) -> FakeGCSDevice:
            families.append(family)
            return fake

        stage = PILinearStage(gcs_device_factory=factory)
        stage.connect()

        self.assertEqual(families, ["C-891"])
        self.assertTrue(stage.connected)
        snapshot = stage.snapshot
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertIn("C-891.120200", snapshot.identity)
        self.assertEqual(snapshot.axes, ("1",))
        self.assertEqual(snapshot.stage_assignment, "V-408.132020")
        self.assertTrue(snapshot.motor_enabled)
        self.assertTrue(snapshot.servo_enabled)
        self.assertTrue(snapshot.referenced)
        self.assertEqual(snapshot.live_min_mm, -13.0)
        self.assertEqual(snapshot.live_max_mm, 13.0)
        self.assertEqual(snapshot.position_mm, 0.0)
        self.assertEqual(snapshot.target_position_mm, 0.0)
        self.assertTrue(snapshot.on_target)
        self.assertEqual(snapshot.velocity_mm_s, 1.0)
        self.assertEqual(snapshot.query_failures, ())
        self.assertEqual(fake.commands, [])

        expected_queries = {
            "qIDN",
            "qSAI",
            "qCST",
            "qEAX",
            "qSVO",
            "qFRF",
            "qTMN",
            "qTMX",
            "qPOS",
            "qMOV",
            "qONT",
            "qVEL",
        }
        observed_queries = {
            call[0] for call in fake.calls if call[0].startswith("q")
        }
        self.assertEqual(observed_queries, expected_queries)

    def test_model_and_serial_identity_mismatches_are_rejected(self) -> None:
        identities = (
            "PI, C-891.1202000, S/N 118054611, FW 1.0",
            "PI, C-891.120200, S/N 1180546119, FW 1.0",
        )
        for identity in identities:
            with self.subTest(identity=identity):
                fake = FakeGCSDevice(identity=identity)
                stage = PILinearStage(gcs_device=fake)
                with self.assertRaises(PIStageIdentityError):
                    stage.connect()
                self.assertFalse(stage.connected)
                self.assertEqual(fake.close_count, 1)

    def test_configured_axis_must_be_reported_by_qsai(self) -> None:
        fake = FakeGCSDevice(axes=("2",))
        stage = PILinearStage(gcs_device=fake)
        with self.assertRaises(PIStageIdentityError):
            stage.connect()
        self.assertEqual(fake.close_count, 1)

    def test_unsupported_optional_query_is_recorded_not_fatal(self) -> None:
        fake = FakeGCSDevice()
        fake.unsupported_queries.add("qVEL")
        stage, _ = connected_stage(fake)
        snapshot = stage.snapshot
        assert snapshot is not None
        self.assertTrue(stage.connected)
        self.assertIsNone(snapshot.velocity_mm_s)
        self.assertEqual(snapshot.failed_query_names, ("qVEL",))
        self.assertIn("not supported", snapshot.query_failures[0].message)

    def test_project_config_conversion_is_structural(self) -> None:
        project_config = SimpleNamespace(
            serial="ABC123",
            controller_model="C-891.CUSTOM",
            stage_model="CUSTOM-STAGE",
            axis="X",
            name="Reusable Test Stage",
            application_min_mm=-2.0,
            application_max_mm=3.0,
            position_tolerance_mm=0.002,
            motion_timeout_s=7.0,
            velocity_mm_s=0.5,
        )
        config = PIStageConfig.from_project_config(
            project_config,
            poll_interval_s=0.02,
        )
        self.assertEqual(config.serial, "ABC123")
        self.assertEqual(config.expected_controller_model, "C-891.CUSTOM")
        self.assertEqual(config.configured_stage_model, "CUSTOM-STAGE")
        self.assertEqual(config.axis, "X")
        self.assertEqual(config.configured_velocity_mm_s, 0.5)
        self.assertEqual(config.poll_interval_s, 0.02)

    def test_disconnect_is_idempotent_and_preserves_enabled_state(self) -> None:
        stage, fake = connected_stage()
        stage.disconnect()
        stage.disconnect()
        self.assertFalse(stage.connected)
        self.assertEqual(fake.close_count, 1)
        self.assertNotIn(("EAX", "1", False), fake.commands)
        self.assertNotIn(("SVO", "1", False), fake.commands)


class PIStagePreparationTests(unittest.TestCase):
    def test_unreferenced_axis_refuses_prepare_before_any_command(self) -> None:
        fake = FakeGCSDevice()
        fake.referenced = False
        fake.motor_enabled = False
        fake.servo_enabled = False
        stage, _ = connected_stage(fake)

        with self.assertRaises(PIStageStateError):
            stage.prepare_for_closed_loop()
        self.assertEqual(fake.commands, [])

    def test_prepare_enables_motor_and_servo_only_after_reference_check(self) -> None:
        fake = FakeGCSDevice()
        fake.motor_enabled = False
        fake.servo_enabled = False
        stage, _ = connected_stage(fake)

        state = stage.prepare_for_closed_loop()

        self.assertTrue(state.referenced)
        self.assertTrue(state.motor_enabled)
        self.assertTrue(state.servo_enabled)
        self.assertFalse(state.motor_was_enabled)
        self.assertFalse(state.servo_was_enabled)
        self.assertEqual(
            fake.commands,
            [("EAX", "1", True), ("SVO", "1", True)],
        )

    def test_prepare_does_not_rewrite_an_already_ready_axis(self) -> None:
        stage, fake = connected_stage()
        state = stage.prepare_for_closed_loop()
        self.assertTrue(state.motor_was_enabled)
        self.assertTrue(state.servo_was_enabled)
        self.assertEqual(fake.commands, [])

    def test_configured_velocity_is_reduced_and_verified(self) -> None:
        fake = FakeGCSDevice()
        fake.velocity_mm_s = 200.0
        config = PIStageConfig(configured_velocity_mm_s=1.0)
        stage, _ = connected_stage(fake, config=config)

        observed = stage.apply_configured_velocity()

        self.assertEqual(observed, 1.0)
        self.assertIn(("VEL", "1", 1.0), fake.commands)
        assert stage.snapshot is not None
        self.assertEqual(stage.snapshot.velocity_mm_s, 1.0)

    def test_configured_velocity_retains_a_slower_live_velocity(self) -> None:
        fake = FakeGCSDevice()
        fake.velocity_mm_s = 0.5
        config = PIStageConfig(configured_velocity_mm_s=1.0)
        stage, _ = connected_stage(fake, config=config)

        observed = stage.apply_configured_velocity()

        self.assertEqual(observed, 0.5)
        self.assertFalse(any(command[0] == "VEL" for command in fake.commands))

    def test_configured_velocity_requires_matching_readback(self) -> None:
        fake = FakeGCSDevice()
        fake.velocity_mm_s = 200.0
        fake.ignore_velocity_command = True
        config = PIStageConfig(configured_velocity_mm_s=1.0)
        stage, _ = connected_stage(fake, config=config)

        with self.assertRaises(PIStageStateError):
            stage.apply_configured_velocity()

    def test_missing_configured_velocity_leaves_controller_unchanged(self) -> None:
        fake = FakeGCSDevice()
        fake.velocity_mm_s = 3.0
        config = PIStageConfig(configured_velocity_mm_s=None)
        stage, _ = connected_stage(fake, config=config)

        self.assertEqual(stage.apply_configured_velocity(), 3.0)
        self.assertFalse(any(command[0] == "VEL" for command in fake.commands))


class PIStageMotionTests(unittest.TestCase):
    def test_motion_uses_intersection_of_application_and_live_limits(self) -> None:
        config = PIStageConfig(
            application_min_mm=-10.0,
            application_max_mm=10.0,
        )
        stage, fake = connected_stage(config=config)
        fake.live_min_mm = -5.0
        fake.live_max_mm = 8.0

        limits = stage.motion_limits()
        self.assertEqual(limits.allowed_min_mm, -5.0)
        self.assertEqual(limits.allowed_max_mm, 8.0)

        for target in (-5.01, 8.01):
            with self.subTest(target=target):
                with self.assertRaises(PIStageLimitError):
                    stage.move_absolute_mm(target)
        self.assertFalse(any(command[0] == "MOV" for command in fake.commands))

    def test_nonfinite_target_is_rejected_before_motion(self) -> None:
        stage, fake = connected_stage()
        for target in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    stage.move_absolute_mm(target)
        self.assertFalse(any(command[0] == "MOV" for command in fake.commands))

    def test_move_refuses_unready_state_without_enabling_it(self) -> None:
        fake = FakeGCSDevice()
        stage, _ = connected_stage(fake)
        fake.servo_enabled = False
        with self.assertRaises(PIStageStateError):
            stage.move_absolute_mm(1.0)
        self.assertFalse(any(command[0] == "MOV" for command in fake.commands))
        self.assertNotIn(("SVO", "1", True), fake.commands)

    def test_successful_move_waits_and_verifies_final_position(self) -> None:
        clock = FakeClock()
        stage, fake = connected_stage(clock=clock)
        fake.ont_responses.extend((False, False, True))

        result = stage.move_absolute_mm(2.5)

        self.assertEqual(result.target_position_mm, 2.5)
        self.assertEqual(result.final_position_mm, 2.5)
        self.assertAlmostEqual(result.elapsed_s, 0.1)
        self.assertEqual(result.limits.allowed_min_mm, -12.0)
        self.assertEqual(result.limits.allowed_max_mm, 12.0)
        self.assertNotIn(("HLT", "1", True), fake.commands)

    def test_timeout_uses_smooth_halt(self) -> None:
        clock = FakeClock()
        config = PIStageConfig(
            motion_timeout_s=0.11,
            poll_interval_s=0.05,
        )
        stage, fake = connected_stage(config=config, clock=clock)
        fake.ont_responses.extend((False, False, False, False, False))

        with self.assertRaises(PIStageTimeoutError):
            stage.move_absolute_mm(1.0)

        self.assertIn(("HLT", "1", True), fake.commands)
        self.assertFalse(any(command[0] == "STP" for command in fake.commands))

    def test_poll_query_error_after_mov_uses_smooth_halt(self) -> None:
        stage, fake = connected_stage()
        fake.query_errors["qONT"] = RuntimeError("lost ONT response")

        with self.assertRaises(PIStageProtocolError):
            stage.move_absolute_mm(1.0)

        self.assertIn(("HLT", "1", True), fake.commands)

    def test_mov_command_error_is_wrapped_and_uses_smooth_halt(self) -> None:
        stage, fake = connected_stage()
        fake.mov_error = RuntimeError("controller rejected MOV")

        with self.assertRaises(PIStageMotionError) as raised:
            stage.move_absolute_mm(1.0)

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertIn(("HLT", "1", True), fake.commands)

    def test_final_tolerance_failure_uses_smooth_halt(self) -> None:
        config = PIStageConfig(final_tolerance_mm=0.001)
        stage, fake = connected_stage(config=config)
        fake.auto_update_position = False
        fake.ont_responses.append(True)

        with self.assertRaises(PIStagePositionError):
            stage.move_absolute_mm(1.0)

        self.assertIn(("HLT", "1", True), fake.commands)


@dataclass
class ConcurrencyProbe:
    active: int = 0
    maximum_active: int = 0

    def __post_init__(self) -> None:
        self.lock = threading.Lock()

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


class SlowPositionFake(FakeGCSDevice):
    def __init__(self, probe: ConcurrencyProbe, identity: str) -> None:
        super().__init__(identity=identity)
        self.probe = probe
        self.slow_queries = False

    def qPOS(self, axis: str) -> dict[str, float]:
        if not self.slow_queries:
            return super().qPOS(axis)
        self.probe.enter()
        try:
            time.sleep(0.02)
            return super().qPOS(axis)
        finally:
            self.probe.leave()


class PIStageSerializationTests(unittest.TestCase):
    def test_gcs_calls_are_serialized_across_driver_instances(self) -> None:
        probe = ConcurrencyProbe()
        first_fake = SlowPositionFake(
            probe,
            "PI, C-891.FIRST, S/N FIRST, FW 1.0",
        )
        second_fake = SlowPositionFake(
            probe,
            "PI, C-891.SECOND, S/N SECOND, FW 1.0",
        )
        first = PILinearStage(
            PIStageConfig(
                serial="FIRST",
                expected_controller_model="C-891.FIRST",
            ),
            gcs_device=first_fake,
        )
        second = PILinearStage(
            PIStageConfig(
                serial="SECOND",
                expected_controller_model="C-891.SECOND",
            ),
            gcs_device=second_fake,
        )
        first.connect()
        second.connect()
        first_fake.slow_queries = True
        second_fake.slow_queries = True
        barrier = threading.Barrier(3)
        errors: list[BaseException] = []

        def read_position(stage: PILinearStage) -> None:
            try:
                barrier.wait()
                _ = stage.position_mm
            except BaseException as exc:  # collected and asserted in main thread
                errors.append(exc)

        threads = (
            threading.Thread(target=read_position, args=(first,)),
            threading.Thread(target=read_position, args=(second,)),
        )
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(probe.maximum_active, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
