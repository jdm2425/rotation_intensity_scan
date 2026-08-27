"""Qt application entry point for the campaign GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import CampaignMainWindow


def main() -> None:
    application = QApplication(sys.argv)
    application.setApplicationName("Rotation + Intensity Campaign")
    application.setOrganizationName("Imperial College London")
    window = CampaignMainWindow()
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
