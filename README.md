# BLE Terminal

A native Qt desktop application for Linux (including Fedora KDE), Windows, and macOS. Scan nearby Bluetooth Low Energy
devices, select one, connect, discover its GATT channels, and send commands.
Supports UTF-8 text, hexadecimal bytes, selectable line endings, reads,
notifications, pairing, and saving traffic logs. Nordic UART channels are selected
automatically when present. The application uses your desktop's Qt theme.

## Release downloads

The GitHub release workflow builds these standalone downloads, including Python
and Qt, so users do not need to install Python:

| Platform | Download |
| --- | --- |
| Linux x86-64 | `.AppImage` and portable `.tar.gz` |
| Linux ARM64 | `.AppImage` and portable `.tar.gz` |
| Windows x86-64 | Standalone `.exe` |
| macOS Intel | `.zip` containing `BLE Terminal.app` |
| macOS Apple Silicon | `.zip` containing `BLE Terminal.app` |
| Other supported Python platforms | Source `.tar.gz` and Python wheel |

Linux downloads target modern glibc distributions (built on Ubuntu 22.04 for
x86-64 and Ubuntu 24.04 for ARM64),
including current Fedora, Ubuntu, Debian, Arch, and openSUSE. They require BlueZ,
an active Bluetooth service, and the usual desktop graphics libraries. No single
binary covers every Linux architecture, older glibc, or musl-based distributions
such as Alpine; install from source there if Qt and Bleak are available.

For AppImages, mark the file executable and open it:

```bash
chmod +x ble-terminal-*.AppImage
./ble-terminal-0.1.0-linux-x86_64.AppImage
```

If FUSE is unavailable, add `--appimage-extract-and-run`, or use the portable
tarball: extract it and run `ble-terminal/ble-terminal`. Windows users can open
the `.exe` directly. macOS users unzip and drag the app to Applications, then
allow Bluetooth when prompted. macOS requires version 13 or newer for the current
Qt dependency. Windows builds target Windows 10/11 with a BLE-capable adapter.
The generated Windows and macOS builds are unsigned; Windows SmartScreen or
macOS Gatekeeper may require explicit approval to open them.

SHA-256 checksum files accompany each native build. Actual radio behavior must
be tested with a BLE peripheral on each platform; automated checks use simulations
and launch each packaged application without accessing Bluetooth.

## Install on Fedora KDE

```bash
sudo dnf install python3 python3-pip bluez
sudo systemctl enable --now bluetooth
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/ble-terminal
```

Run these commands from this project directory. Enable Bluetooth in KDE System
Settings first. Run the application as your normal user. BlueZ is accessed over
the system D-Bus; no root access is needed for the application.

To add it to the KDE application launcher, run from the project directory:

```bash
mkdir -p ~/.local/share/applications
sed "s|^Exec=.*|Exec=\"$PWD/.venv/bin/ble-terminal\"|" packaging/ble-terminal.desktop > ~/.local/share/applications/io.github.bleterminal.BLETerminal.desktop
```

Keep this directory in place after creating the launcher. To update after source
changes, run `.venv/bin/python -m pip install .` again.
If you previously installed `ble-terminal.desktop`, remove that old launcher to
avoid duplicate entries. The new filename matches the app's Wayland desktop ID;
the application also sets a window icon and Windows taskbar identity.

## Use

1. Click **Scan for devices** and wait six seconds. Choose a device, then **Connect**.
   Select **Pair before connecting** if authentication is required; respond to
   any KDE pairing dialog.
2. Choose the writable characteristic under **Send to**. Check the device's
   protocol documentation if several channels are available. Each channel shows
   its UUID and handle; the traffic log includes its service and properties.
3. Choose a receive channel and click **Subscribe** to display notifications or
   indications. Use **Read value** for characteristics supporting explicit reads.
4. Type a command, choose text or hex and the required line ending, then press
   Enter or **Send**. Both incoming and outgoing bytes appear as text and hex.
   Select **None** for the line ending when sending binary commands that should
   have no terminator. Commands remain in the input field for editing or resending.
5. Click **Disconnect** when finished. Closing the app also disconnects.

BLE has no universal serial command protocol. A device must expose a writable
GATT characteristic and accept the command format you send. Classic Bluetooth
SPP devices are not supported. A write response acknowledges the GATT write;
application replies arrive through the device's notification/read channel.
Payloads exceeding the characteristic's write limit are rejected with an error;
commands are never automatically split into multiple writes.

If scanning fails, verify Bluetooth is enabled and the device is advertising and
not already connected elsewhere. Errors are shown in the traffic log. Devices
requiring authentication can also be paired in KDE Bluetooth settings first.

## Development

```bash
.venv/bin/python -m pip install -e .
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

The tests use simulated peripherals; real radio connectivity requires BLE hardware.
Uses [Bleak](https://bleak.readthedocs.io/en/latest/api/client.html) for GATT
operations and [BlueZ over D-Bus](https://bleak.readthedocs.io/en/latest/backends/linux.html).

## Publishing on GitHub

Upload this repository, including `.github/workflows/release.yml`. Run **Actions →
Build releases → Run workflow** to try all builds; downloads appear as workflow
artifacts. For a versioned release, set `version` in `pyproject.toml`, commit,
and push the matching tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

After all builds pass, the workflow creates a **draft GitHub Release** with the
AppImages, Linux tarballs, Windows executable, macOS apps, checksums, source
archive, and wheel attached. Review it in GitHub Releases and click **Publish
release**. The workflow uses GitHub's built-in token; no personal token is needed.

To build locally, run on the target operating system:

```bash
python -m pip install -c packaging/constraints-release.txt ".[release]"
python packaging/build_release.py
```

Output goes to `release/`. On Linux, add `--appimage-tool /path/to/appimagetool.AppImage`
to also build an AppImage using [appimagetool 1.9.1](https://github.com/AppImage/appimagetool/releases/tag/1.9.1).
Native builds use [PyInstaller](https://pyinstaller.org/en/stable/), which must run
on the target OS. Building locally on a newer Linux distribution can increase
the minimum glibc requirement; use the GitHub workflow for the release baseline.
