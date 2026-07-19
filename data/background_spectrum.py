"""Persistent background-spectrum model used by saved experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hardware.devices.spectrometer.spectrum import Spectrum


@dataclass(slots=True)
class BackgroundSpectrum:
    """One named background acquisition associated with an experiment."""

    name: str

    spectrum: Spectrum

    metadata: dict[str, Any] = field(default_factory=dict)

    source_path: Path | None = None
