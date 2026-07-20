"""Compatibility entry point for the rotation/intensity experiment.

``run_rotation_intensity.py`` is the maintained experiment entry point.  This
module remains only so an older command or shortcut cannot accidentally use a
second, stale hardware workflow.
"""

from __future__ import annotations

from run_rotation_intensity import main


if __name__ == "__main__":
    main()
