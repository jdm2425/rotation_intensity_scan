#!/usr/bin/env python3
"""Prepare the project environment and launch the campaign GUI.

This file intentionally uses only the Python standard library so that it can
create the virtual environment before any project dependencies are available.
It never imports a hardware driver or connects to a device during preflight.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


MINIMUM_PYTHON = (3, 11)


class LauncherError(RuntimeError):
    """An actionable launcher failure that should be shown without a traceback."""


def _venv_python(venv_directory: Path, *, platform_name: str | None = None) -> Path:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        return venv_directory / "Scripts" / "python.exe"
    return venv_directory / "bin" / "python"


def _run_checked(command: Sequence[str], *, cwd: Path, purpose: str) -> None:
    try:
        completed = subprocess.run(list(command), cwd=cwd, check=False)
    except OSError as error:
        raise LauncherError(f"Could not {purpose}: {error}") from error
    if completed.returncode != 0:
        rendered = subprocess.list2cmdline(list(command))
        raise LauncherError(
            f"Could not {purpose} (exit code {completed.returncode}).\n"
            f"Command: {rendered}"
        )


def _capture_checked(command: Sequence[str], *, cwd: Path, purpose: str) -> str:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise LauncherError(f"Could not {purpose}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f"\n{detail}" if detail else ""
        raise LauncherError(f"Could not {purpose}.{suffix}")
    return completed.stdout.strip()


def _check_python_version(python: Path, *, cwd: Path) -> None:
    version_text = _capture_checked(
        [
            str(python),
            "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:3])))",
        ],
        cwd=cwd,
        purpose=f"run the project interpreter at {python}",
    )
    try:
        version = tuple(int(part) for part in version_text.split("."))
    except ValueError as error:
        raise LauncherError(
            "Could not understand Python version reported by "
            f"{python}: {version_text!r}"
        ) from error
    if version < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise LauncherError(
            f"Python {required} or newer is required; {python} is Python "
            f"{version_text}."
        )


def _ensure_environment(repository: Path) -> Path:
    if sys.version_info[:2] < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        current = ".".join(map(str, sys.version_info[:3]))
        raise LauncherError(
            f"Python {required} or newer is required to set up this project; "
            f"the current interpreter is Python {current}."
        )

    venv_directory = repository / ".venv"
    python = _venv_python(venv_directory)
    if not python.is_file():
        action = "Repairing" if venv_directory.exists() else "Creating"
        print(f"{action} virtual environment: {venv_directory}", flush=True)
        _run_checked(
            [sys.executable, "-m", "venv", str(venv_directory)],
            cwd=repository,
            purpose="create the project virtual environment",
        )
    if not python.is_file():
        raise LauncherError(
            f"Virtual-environment creation completed, but {python} was not created."
        )
    _check_python_version(python, cwd=repository)

    try:
        _capture_checked(
            [str(python), "-m", "pip", "--version"],
            cwd=repository,
            purpose="check pip",
        )
    except LauncherError:
        print("Installing pip in the virtual environment...", flush=True)
        _run_checked(
            [str(python), "-m", "ensurepip", "--upgrade"],
            cwd=repository,
            purpose="install pip in the virtual environment",
        )
    return python


def _requirement_files(repository: Path, *, include_hardware: bool) -> list[Path]:
    files = [repository / "requirements-gui.txt"]
    if include_hardware:
        files.append(repository / "requirements-hardware.txt")
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise LauncherError(
            "Required dependency file is missing: "
            + ", ".join(str(path) for path in missing)
        )
    return files


def _install_and_check_requirements(
    python: Path,
    repository: Path,
    *,
    include_hardware: bool,
) -> None:
    requirement_files = _requirement_files(
        repository, include_hardware=include_hardware
    )
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    for requirement_file in requirement_files:
        command.extend(["--requirement", str(requirement_file)])

    scope = "GUI and hardware" if include_hardware else "GUI"
    print(f"Checking {scope} Python requirements...", flush=True)
    _run_checked(
        command,
        cwd=repository,
        purpose=f"satisfy the {scope.lower()} requirements",
    )
    _run_checked(
        [str(python), "-m", "pip", "check"],
        cwd=repository,
        purpose="verify the installed Python packages",
    )

    # Importing gui.main checks the complete GUI import graph without creating a
    # QApplication, constructing the main window, or loading a hardware driver.
    _run_checked(
        [str(python), "-c", "import gui.main"],
        cwd=repository,
        purpose="verify that the campaign GUI imports cleanly",
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create/reuse .venv, install missing requirements, verify the "
            "environment, and launch the campaign GUI."
        )
    )
    parser.add_argument(
        "--gui-only",
        action="store_true",
        help=(
            "install only hardware-free GUI dependencies (physical hardware "
            "connections will not be available)"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="prepare and verify the environment without launching the GUI",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _argument_parser().parse_args(arguments)
    repository = Path(__file__).resolve().parent
    run_gui = repository / "run_gui.py"
    if not run_gui.is_file():
        raise LauncherError(f"GUI entry point is missing: {run_gui}")

    include_hardware = os.name == "nt" and not options.gui_only
    if os.name != "nt" and not options.gui_only:
        print(
            "Non-Windows system detected: installing the hardware-free GUI "
            "requirements only. The physical stack includes Windows-only drivers.",
            flush=True,
        )

    python = _ensure_environment(repository)
    _install_and_check_requirements(
        python,
        repository,
        include_hardware=include_hardware,
    )
    print(f"Environment ready: {python}", flush=True)
    print("No shell activation is needed; the GUI uses this interpreter directly.")

    if include_hardware:
        print(
            "Hardware Python packages are installed. Vendor software and USB/COM "
            "drivers (Kinesis, SeaBreeze, PI, and Ophir StarLab) remain vendor "
            "installations and are validated only when the operator connects a device."
        )

    if options.check_only:
        print("Preflight completed; GUI launch skipped (--check-only).")
        return 0

    print("Launching the campaign GUI (no hardware is connected automatically)...")
    try:
        completed = subprocess.run([str(python), str(run_gui)], cwd=repository)
    except OSError as error:
        raise LauncherError(f"Could not launch the campaign GUI: {error}") from error
    return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LauncherError as error:
        print(f"\nLauncher error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
