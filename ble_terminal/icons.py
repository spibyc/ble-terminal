"""Desktop identity and an icon that also works without a system icon theme."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

APP_ID = "io.github.bleterminal.BLETerminal"


def application_icon():
    fallback = QIcon(str(Path(__file__).with_name("assets") / "bluetooth.svg"))
    return QIcon.fromTheme("bluetooth", fallback)


def configure_application(app):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app.setApplicationName("BLE Terminal")
    app.setOrganizationName("BLETerminal")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(application_icon())
