"""Build on the target OS: python packaging/build_release.py [--appimage-tool PATH]."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.bleterminal.BLETerminal"


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, **kwargs)


def make_icons():
    # Render the same source used by the app; no third-party icon downloads.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    folder = ROOT / "build" / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    QIcon(str(ROOT / "ble_terminal/assets/bluetooth.svg")).pixmap(1024, 1024).save(str(folder / "bluetooth.png"))
    with Image.open(folder / "bluetooth.png") as source:
        source.save(folder / "bluetooth.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
        source.save(folder / "bluetooth.icns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage-tool", type=Path)
    args = parser.parse_args()
    make_icons()
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "packaging/ble-terminal.spec")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    arch = {"AMD64": "x86_64", "arm64": "aarch64"}.get(platform.machine(), platform.machine())
    os_name = {"linux": "linux", "win32": "windows", "darwin": "macos"}[sys.platform]
    name = f"ble-terminal-{version}-{os_name}-{arch}"
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    artifacts = []
    build_info = (f"BLE Terminal {version}\nBuilt on: {platform.platform()}\n"
                  f"Architecture: {arch}\nPython: {platform.python_version()}\n"
                  f"libc: {' '.join(platform.libc_ver()) or 'not applicable'}\n")
    (output / f"{name}-BUILD.txt").write_text(build_info)
    if sys.platform == "win32":
        target = output / f"{name}.exe"
        shutil.copy2(ROOT / "dist/ble-terminal.exe", target)
        artifacts.append(target)
        run(target, "--smoke-test", timeout=60)
    elif sys.platform == "darwin":
        app = ROOT / "dist/BLE Terminal.app"
        run(app / "Contents/MacOS/ble-terminal", "--smoke-test", timeout=60)
        target = output / f"{name}.zip"
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, target)
        artifacts.append(target)
    else:
        bundle = ROOT / "dist/ble-terminal"
        run(bundle / "ble-terminal", "--smoke-test", timeout=60)
        desktop = (ROOT / "packaging/ble-terminal.desktop").read_text().replace("Icon=bluetooth", f"Icon={APP_ID}")
        (bundle / f"{APP_ID}.desktop").write_text(desktop)
        shutil.copy2(ROOT / "build/icons/bluetooth.png", bundle / f"{APP_ID}.png")
        shutil.copy2(ROOT / "README.md", bundle / "README.md")
        (bundle / "BUILD.txt").write_text(build_info)
        target = output / f"{name}.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(bundle, arcname="ble-terminal")
        artifacts.append(target)
        if args.appimage_tool:
            appdir = ROOT / "build/BLETerminal.AppDir"
            if appdir.exists():
                shutil.rmtree(appdir)
            shutil.copytree(bundle, appdir / "usr/bin")
            (appdir / f"{APP_ID}.desktop").write_text(desktop)
            shutil.copy2(ROOT / "build/icons/bluetooth.png", appdir / f"{APP_ID}.png")
            launcher = appdir / "AppRun"
            launcher.write_text('#!/bin/sh\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$HERE/usr/bin/ble-terminal" "$@"\n')
            launcher.chmod(0o755)
            target = output / f"{name}.AppImage"
            run(args.appimage_tool.resolve(), "--appimage-extract-and-run", appdir, target,
                env={**os.environ, "ARCH": arch, "APPIMAGE_EXTRACT_AND_RUN": "1"})
            run(target, "--appimage-extract-and-run", "--smoke-test", timeout=60)
            artifacts.append(target)
    checksums = output / f"{name}-SHA256SUMS.txt"
    lines = []
    for path in artifacts:
        with path.open("rb") as stream:
            lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
    checksums.write_text("".join(lines))
    print(f"Release files: {output}")


if __name__ == "__main__":
    main()
