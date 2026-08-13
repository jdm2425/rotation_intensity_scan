# Portable PI, shutter, and rotation-mount drivers

This folder is intended to be copied into another Python project. It contains
only:

- A PI C-891 single-axis linear-stage driver.
- A Thorlabs MFF shutter driver.
- A Thorlabs PRM1-Z8 rotation-mount driver.
- Their minimal common base classes.
- Non-executing usage examples.

Copy the complete `transfer_hardware_drivers` directory. Run examples from
inside that directory, or add it to the new project's Python import path:

```python
from hardware_drivers import BeamShutter, PILinearStage, PIStageConfig, RotationStage
```

## Installation

Create a virtual environment, then install:

```powershell
python -m pip install -r requirements.txt
```

Vendor software is also required:

- Thorlabs Kinesis for the MFF shutter and PRM1-Z8.
- The 64-bit PI Software Suite/GCS DLL for the C-891 controller.

Close Kinesis-owning applications and PIMikroMove before Python connects.

## Safety rules

- Replace every placeholder serial number before use.
- Review PI application limits and every target position.
- `PIStageConfig` does not home, reference, phase-find, assign a stage database
  entry, redefine position, or write persistent parameters.
- PI motion is refused unless the live controller reports the axis referenced,
  motor enabled, and servo enabled.
- PI targets are checked against both configured application limits and live
  `TMN?`/`TMX?` limits.
- Close and positively verify the upstream shutter before any insertion-stage
  move.
- The verified MFF mapping is fixed: state `0` is open and state `1` is closed.
- Finish hardware-owning code in `finally` blocks or context managers.
- Never call `home()` merely to test a rotation mount.

## PI stage

Read-only connection and inspection:

```python
from hardware_drivers import PILinearStage, PIStageConfig

config = PIStageConfig(
    serial="YOUR_PI_SERIAL",
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
```

For motion, first establish the shutter interlock, then explicitly call
`prepare_for_closed_loop()` and `move_absolute_mm(target)`. See
`move_pi_with_closed_shutter()` in `example_usage.py`.

## Shutter

```python
from hardware_drivers import BeamShutter

shutter = BeamShutter(serial="YOUR_SERIAL", name="Beam Shutter")
try:
    shutter.connect()
    shutter.close()
    if not shutter.is_closed:
        raise RuntimeError("Shutter closure was not verified.")
    shutter.open()
finally:
    if shutter.connected:
        shutter.close()
    shutter.disconnect()
```

## Rotation mount

```python
from hardware_drivers import RotationStage

with RotationStage(
    serial="YOUR_SERIAL",
    name="Rotation Mount",
    scale="PRM1-Z8",
) as stage:
    print(stage.position)
    stage.move_to(10.0)
```

`move_to()` and `move_by()` block until motion completes or times out. `home()`
exists but must only be used after a deliberate hardware review.

## Example module

`example_usage.py` defines four functions but deliberately has no automatic
entry point:

- `inspect_pi_stage()`
- `move_pi_with_closed_shutter(target_mm)`
- `move_rotation_mount(target_deg)`
- `shutter_once()`

Calling any of the latter three can move physical hardware or expose the beam.
