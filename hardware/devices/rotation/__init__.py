"""
Rotation stage hardware.

This package provides the common rotation stage interface used
throughout the project.

Experiment code should import RotationStage rather than importing
the implementation module directly.
"""

from .base import BaseRotationStage
from .rotation_stage import RotationStage

__all__ = [
    "BaseRotationStage",
    "RotationStage",
]