"""Hardware-free tests for the one-command GUI launcher."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import start_gui


class GuiLauncherTests(unittest.TestCase):
    def test_virtual_environment_interpreter_is_platform_specific(self) -> None:
        root = Path("project") / ".venv"
        self.assertEqual(
            start_gui._venv_python(root, platform_name="nt"),
            root / "Scripts" / "python.exe",
        )
        self.assertEqual(
            start_gui._venv_python(root, platform_name="posix"),
            root / "bin" / "python",
        )

    def test_requirement_selection_keeps_hardware_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            gui = repository / "requirements-gui.txt"
            hardware = repository / "requirements-hardware.txt"
            gui.touch()
            hardware.touch()

            self.assertEqual(
                start_gui._requirement_files(repository, include_hardware=False),
                [gui],
            )
            self.assertEqual(
                start_gui._requirement_files(repository, include_hardware=True),
                [gui, hardware],
            )

    def test_preflight_installs_checks_and_imports_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            gui = repository / "requirements-gui.txt"
            hardware = repository / "requirements-hardware.txt"
            gui.touch()
            hardware.touch()
            python = Path("test-python")
            commands: list[list[str]] = []

            def remember(command: list[str], **_: object) -> None:
                commands.append(list(command))

            with patch.object(start_gui, "_run_checked", side_effect=remember):
                start_gui._install_and_check_requirements(
                    python,
                    repository,
                    include_hardware=True,
                )

            self.assertEqual(len(commands), 3)
            self.assertIn(str(gui), commands[0])
            self.assertIn(str(hardware), commands[0])
            self.assertEqual(commands[1][-2:], ["pip", "check"])
            self.assertEqual(commands[2][-2:], ["-c", "import gui.main"])


if __name__ == "__main__":
    unittest.main()
