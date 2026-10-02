"""Portable campaign-project files used by the GUI.

A project file contains only JSON-compatible values and paths relative to the
project file.  Raw run data, calibration artefacts, and manually saved live
spectra therefore remain together when the project directory is moved to a
different computer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any


PROJECT_FORMAT_VERSION = 1
PROJECT_SUFFIX = ".risproject"


@dataclass(slots=True)
class CampaignProject:
    """One portable, multi-session campaign project."""

    path: Path
    name: str
    created: str
    updated: str
    runs_directory_value: str
    calibrations_directory_value: str
    live_spectra_directory_value: str
    scan_settings: dict[str, Any] = field(default_factory=dict)
    active_calibration_value: str | None = None
    run_directories: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, path: str | Path, *, name: str | None = None) -> "CampaignProject":
        """Create a project file and its sibling managed-data directories."""

        project_path = _normalise_project_path(path)
        if project_path.exists():
            raise FileExistsError(
                f"Campaign project already exists; open it instead: {project_path}"
            )
        now = datetime.now().isoformat()
        data_root = f"{project_path.stem}_data"
        project = cls(
            path=project_path,
            name=str(name or project_path.stem).strip() or project_path.stem,
            created=now,
            updated=now,
            runs_directory_value=(Path(data_root) / "runs").as_posix(),
            calibrations_directory_value=(
                Path(data_root) / "calibrations"
            ).as_posix(),
            live_spectra_directory_value=(
                Path(data_root) / "live_spectra"
            ).as_posix(),
        )
        project.ensure_directories()
        project.save()
        return project

    @classmethod
    def load(cls, path: str | Path) -> "CampaignProject":
        """Load and validate an existing project file."""

        project_path = Path(path).expanduser().resolve()
        if not project_path.is_file():
            raise FileNotFoundError(f"Campaign project does not exist: {project_path}")
        with project_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"Campaign project must contain a JSON object: {project_path}")
        version = data.get("format_version")
        if version != PROJECT_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported campaign-project format {version!r} in {project_path}; "
                f"expected {PROJECT_FORMAT_VERSION}."
            )
        paths = data.get("paths")
        if not isinstance(paths, dict):
            raise ValueError(f"Campaign project has no valid paths section: {project_path}")
        project = cls(
            path=project_path,
            name=str(data.get("name", project_path.stem)),
            created=str(data.get("created", "")),
            updated=str(data.get("updated", "")),
            runs_directory_value=_require_relative(paths.get("runs"), "runs"),
            calibrations_directory_value=_require_relative(
                paths.get("calibrations"), "calibrations"
            ),
            live_spectra_directory_value=_require_relative(
                paths.get("live_spectra"), "live_spectra"
            ),
            scan_settings=_require_dictionary(data.get("scan_settings", {})),
            active_calibration_value=_optional_relative(
                data.get("active_calibration"), "active_calibration"
            ),
            run_directories=[
                _require_relative(value, "run_directories entry")
                for value in _require_list(data.get("run_directories", []))
            ],
        )
        # Resolve every stored path now so a malicious or accidentally edited
        # project cannot escape its portable project directory.
        project._managed_path(project.runs_directory_value)
        project._managed_path(project.calibrations_directory_value)
        project._managed_path(project.live_spectra_directory_value)
        if project.active_calibration_value:
            calibration_path = project._managed_path(project.active_calibration_value)
            if not calibration_path.is_file():
                raise FileNotFoundError(
                    "Campaign project's active calibration is missing: "
                    f"{calibration_path}"
                )
        for run in project.run_directories:
            project._managed_path(run)
        project.ensure_directories()
        if project.discover_runs():
            project.save()
        return project

    @property
    def root(self) -> Path:
        return self.path.parent

    @property
    def runs_directory(self) -> Path:
        return self._managed_path(self.runs_directory_value)

    @property
    def calibrations_directory(self) -> Path:
        return self._managed_path(self.calibrations_directory_value)

    @property
    def live_spectra_directory(self) -> Path:
        return self._managed_path(self.live_spectra_directory_value)

    @property
    def active_calibration(self) -> Path | None:
        if self.active_calibration_value is None:
            return None
        return self._managed_path(self.active_calibration_value)

    @property
    def latest_run(self) -> Path | None:
        if not self.run_directories:
            return None
        return self._managed_path(self.run_directories[-1])

    def ensure_directories(self) -> None:
        """Create managed directories without touching any existing run data."""

        self.root.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.runs_directory,
            self.calibrations_directory,
            self.live_spectra_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def set_scan_settings(self, settings: dict[str, Any]) -> None:
        """Replace the saved GUI form state after JSON validation."""

        json.dumps(settings, ensure_ascii=False, allow_nan=False)
        self.scan_settings = dict(settings)

    def record_calibration(self, calibration_path: str | Path) -> None:
        """Set the active calibration, requiring it to live inside the project."""

        path = Path(calibration_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Calibration file does not exist: {path}")
        try:
            path.relative_to(self.calibrations_directory.resolve())
        except ValueError as error:
            raise ValueError(
                f"Campaign calibration must be stored inside "
                f"{self.calibrations_directory}: {path}"
            ) from error
        self.active_calibration_value = self._relative_managed_path(path)

    def record_run(self, run_directory: str | Path) -> None:
        """Append a newly created run directory once, using a portable path."""

        path = Path(run_directory).expanduser().resolve()
        try:
            path.relative_to(self.runs_directory.resolve())
        except ValueError as error:
            raise ValueError(
                f"Campaign run must be stored inside {self.runs_directory}: {path}"
            ) from error
        relative = self._relative_managed_path(path)
        if relative not in self.run_directories:
            self.run_directories.append(relative)

    def discover_runs(self) -> int:
        """Recover run directories created before a project update or crash."""

        discovered = 0
        known = set(self.run_directories)
        for path in sorted(self.runs_directory.iterdir()):
            if not path.is_dir() or not (path / "measurements.csv").is_file():
                continue
            relative = self._relative_managed_path(path)
            if relative not in known:
                self.run_directories.append(relative)
                known.add(relative)
                discovered += 1
        self.run_directories.sort(
            key=lambda value: (
                self._managed_path(value).stat().st_mtime
                if self._managed_path(value).exists()
                else 0.0
            )
        )
        return discovered

    def save(self) -> None:
        """Atomically save the project manifest."""

        self.ensure_directories()
        self.updated = datetime.now().isoformat()
        data = {
            "format_version": PROJECT_FORMAT_VERSION,
            "name": self.name,
            "created": self.created,
            "updated": self.updated,
            "paths": {
                "runs": self.runs_directory_value,
                "calibrations": self.calibrations_directory_value,
                "live_spectra": self.live_spectra_directory_value,
            },
            "scan_settings": self.scan_settings,
            "active_calibration": self.active_calibration_value,
            "run_directories": self.run_directories,
        }
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(self.path)

    def _managed_path(self, relative_value: str) -> Path:
        relative = Path(relative_value)
        if relative.is_absolute():
            raise ValueError(
                f"Campaign-project paths must be relative, not {relative_value!r}."
            )
        resolved = (self.root / relative).resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError as error:
            raise ValueError(
                f"Campaign-project path escapes the project directory: {relative_value!r}"
            ) from error
        return resolved

    def _relative_managed_path(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError as error:
            raise ValueError(
                f"Managed campaign data must be inside {self.root}: {path}"
            ) from error
        return relative.as_posix()


def _normalise_project_path(path: str | Path) -> Path:
    project_path = Path(path).expanduser()
    if project_path.suffix.lower() != PROJECT_SUFFIX:
        project_path = project_path.with_suffix(PROJECT_SUFFIX)
    return project_path.resolve()


def _require_relative(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Campaign-project {field_name} path must not be empty.")
    if Path(text).is_absolute():
        raise ValueError(f"Campaign-project {field_name} path must be relative.")
    return Path(text).as_posix()


def _optional_relative(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    return _require_relative(value, field_name)


def _require_dictionary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Campaign-project scan_settings must be a JSON object.")
    return dict(value)


def _require_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Campaign-project run_directories must be a JSON list.")
    return list(value)
