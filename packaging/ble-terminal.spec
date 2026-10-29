# Run through packaging/build_release.py, which generates platform icons first.
import sys
import tomllib
from pathlib import Path

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
icon = str(root / "build" / "icons" / ("bluetooth.icns" if sys.platform == "darwin" else "bluetooth.ico"))
a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root)],
    datas=[(str(root / "ble_terminal" / "assets"), "ble_terminal/assets")],
    hiddenimports=[],
    hookspath=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
options = dict(name="ble-terminal", debug=False, strip=False, upx=False,
               console=False, icon=icon if sys.platform != "linux" else None)
if sys.platform == "win32":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ble-terminal")
    if sys.platform == "darwin":
        app = BUNDLE(collection, name="BLE Terminal.app", icon=icon,
                     bundle_identifier="io.github.bleterminal.BLETerminal",
                     version=version, info_plist={
                         "CFBundleShortVersionString": version,
                         "NSBluetoothAlwaysUsageDescription": "BLE Terminal uses Bluetooth to discover devices and exchange commands with the device you choose.",
                         "NSHighResolutionCapable": True,
                     })
