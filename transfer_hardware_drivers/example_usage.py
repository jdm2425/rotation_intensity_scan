"""Examples for the portable hardware drivers.

Nothing runs merely by importing this module. Replace placeholder serials and
review all positions before explicitly calling one of these functions.
"""

from __future__ import annotations

from hardware_drivers import BeamShutter, PILinearStage, PIStageConfig, RotationStage


def inspect_pi_stage() -> None:
    """Connect read-only and print PI identity/state without moving."""

    config = PIStageConfig(
        serial="REPLACE_PI_SERIAL",
        expected_controller_model="C-891.120200",
        controller_family="C-891",
        configured_stage_model="V-408.132020",
        axis="1",
        application_min_mm=-12.0,
        application_max_mm=12.0,
        configured_velocity_mm_s=None,
    )
    with PILinearStage(config=config) as stage:
        print(stage.refresh_snapshot())
        print(stage.motion_limits())


def move_pi_with_closed_shutter(target_mm: float) -> None:
    """Move the PI stage only after closing and verifying the shutter."""

    shutter = BeamShutter(
        serial="REPLACE_SHUTTER_SERIAL",
        name="Beam Shutter",
    )
    stage = PILinearStage(
        config=PIStageConfig(
            serial="REPLACE_PI_SERIAL",
            expected_controller_model="C-891.120200",
            controller_family="C-891",
            configured_stage_model="V-408.132020",
            axis="1",
            application_min_mm=-12.0,
            application_max_mm=12.0,
            configured_velocity_mm_s=None,
        )
    )
    try:
        shutter.connect()
        shutter.close()
        if not shutter.is_closed:
            raise RuntimeError("Shutter closure was not verified; PI move refused.")
        stage.connect()
        stage.prepare_for_closed_loop()
        result = stage.move_absolute_mm(target_mm)
        print(result)
    finally:
        if shutter.connected:
            shutter.close()
        stage.disconnect()
        shutter.disconnect()


def move_rotation_mount(target_deg: float) -> None:
    """Move one PRM1-Z8 to a reviewed absolute angle."""

    with RotationStage(
        serial="REPLACE_ROTATION_SERIAL",
        name="Rotation Mount",
        scale="PRM1-Z8",
    ) as stage:
        print(f"Starting angle: {stage.position:.6g} deg")
        stage.move_to(target_deg)
        print(f"Final angle: {stage.position:.6g} deg")


def shutter_once() -> None:
    """Open once and always attempt to finish closed."""

    shutter = BeamShutter(
        serial="REPLACE_SHUTTER_SERIAL",
        name="Beam Shutter",
    )
    try:
        shutter.connect()
        shutter.close()
        if not shutter.is_closed:
            raise RuntimeError("Shutter did not begin closed.")
        shutter.open()
        if not shutter.is_open:
            raise RuntimeError("Shutter did not verify open.")
    finally:
        if shutter.connected:
            shutter.close()
        shutter.disconnect()
