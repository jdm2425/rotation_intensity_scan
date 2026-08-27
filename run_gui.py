"""Launch the campaign graphical interface in safe simulation mode."""

from __future__ import annotations


def main() -> None:
    try:
        from gui.main import main as gui_main
    except ModuleNotFoundError as error:
        if error.name == "PySide6":
            raise SystemExit(
                "PySide6 is required for the campaign GUI. Install it in the "
                "project environment with:\n"
                "  .\\.venv\\Scripts\\python.exe -m pip install "
                "-r requirements-gui.txt"
            ) from error
        raise
    gui_main()


if __name__ == "__main__":
    main()
