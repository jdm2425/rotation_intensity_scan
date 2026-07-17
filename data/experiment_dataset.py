"""
experiment_dataset.py

Represents a complete experiment loaded into memory.

The ExperimentDataset is the common interface used by analysis,
plotting and future GUI components. It contains the experiment
metadata together with every Measurement acquired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from analysis.measurement import Measurement


@dataclass(slots=True)
class ExperimentDataset:
    """
    Complete experiment.

    Parameters
    ----------
    root
        Directory containing the experiment.

    experiment_name
        Human readable experiment name.

    created
        Creation timestamp.

    config
        Saved experiment configuration.

    hardware
        Hardware metadata.

    metadata
        Additional metadata.

    measurements
        List of Measurement objects.
    """

    root: Path

    experiment_name: str

    created: str

    config: dict[str, Any] = field(default_factory=dict)

    hardware: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    measurements: list[Measurement] = field(
        default_factory=list
    )

    # ------------------------------------------------------------------

    def __len__(self) -> int:

        return len(self.measurements)

    # ------------------------------------------------------------------

    def __iter__(self) -> Iterable[Measurement]:

        return iter(self.measurements)

    # ------------------------------------------------------------------

    def __getitem__(
        self,
        index: int,
    ) -> Measurement:

        return self.measurements[index]

    # ------------------------------------------------------------------

    def add(
        self,
        measurement: Measurement,
    ) -> None:

        self.measurements.append(measurement)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def sample_angles(self):

        return [
            m.sample_angle_deg
            for m in self.measurements
        ]

    @property
    def waveplate_angles(self):

        return [
            m.waveplate_angle_deg
            for m in self.measurements
        ]

    @property
    def powers(self):

        return [
            m.power_mw
            for m in self.measurements
        ]

    @property
    def fluences(self):

        return [
            m.fluence_mj_cm2
            for m in self.measurements
        ]

    @property
    def intensities(self):

        return [
            m.intensity_w_cm2
            for m in self.measurements
        ]

    @property
    def peak_counts(self):

        return [
            m.peak_counts
            for m in self.measurements
        ]

    @property
    def integrated_counts(self):

        return [
            m.integrated_counts
            for m in self.measurements
        ]

    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:

        return {

            "experiment": self.experiment_name,

            "created": self.created,

            "measurements": len(self),

            "directory": str(self.root),

        }

    # ------------------------------------------------------------------

    def __repr__(self):

        return (
            f"<ExperimentDataset("
            f"name='{self.experiment_name}', "
            f"measurements={len(self.measurements)})>"
        )