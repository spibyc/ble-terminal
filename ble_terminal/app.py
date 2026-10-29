import sys
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView,
)

from .backend import BluetoothBackend
from .protocol import ENDINGS, NUS_NOTIFY, NUS_WRITE, encode_command, format_payload
from .icons import application_icon, configure_application


class TerminalWindow(QMainWindow):
    def __init__(self, backend=None):
        super().__init__()
        self.setWindowIcon(application_icon())
        self.backend = backend or BluetoothBackend()
        self.settings = QSettings("BLETerminal", "BLETerminal")
        self.connected = False
        self.busy = False
        self.closing = False
        self.allow_close = False
        self.rows = {}
        self.pending_payload = b""
        self.setWindowTitle("BLE Terminal")
        self.resize(1120, 760)
        self.setMinimumSize(850, 580)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        heading = QLabel("BLE Terminal")
        heading.setStyleSheet("font-size: 26px; font-weight: 600;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Discover nearby devices, connect, and exchange Bluetooth Low Energy commands."))
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        devices = QGroupBox("Nearby devices")
        left = QVBoxLayout(devices)
        self.scan_button = QPushButton("Scan for devices")
        self.scan_button.clicked.connect(self.scan)
        left.addWidget(self.scan_button)
        self.device_table = QTableWidget(0, 3)
        self.device_table.setHorizontalHeaderLabels(["Device", "Address", "RSSI"])
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.device_table.verticalHeader().hide()
        self.device_table.itemSelectionChanged.connect(self.update_controls)
        left.addWidget(self.device_table)
        self.pair = QCheckBox("Pair before connecting")
        self.pair.setToolTip("Use when a device requires authentication. KDE may ask for a PIN or confirmation.")
        if sys.platform == "darwin":
            self.pair.setToolTip("macOS handles pairing automatically when a protected characteristic is accessed.")
        left.addWidget(self.pair)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        left.addWidget(self.connect_button)
        splitter.addWidget(devices)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(10, 0, 0, 0)
        channels = QGroupBox("Device channels")
        form = QFormLayout(channels)
        self.write_channel = QComboBox()
        self.write_channel.setMinimumWidth(200)
        self.write_channel.currentIndexChanged.connect(self.update_write_modes)
        self.write_mode = QComboBox()
        form.addRow("Send to", self.write_channel)
        form.addRow("Write mode", self.write_mode)
        self.notify_channel = QComboBox()
        self.subscribe_button = QPushButton("Subscribe")
        self.subscribe_button.clicked.connect(self.toggle_notifications)
        self.notify_channel.currentIndexChanged.connect(self.update_controls)
        notify_row = QHBoxLayout()
        notify_row.addWidget(self.notify_channel, 1)
        notify_row.addWidget(self.subscribe_button)
        form.addRow("Receive from", notify_row)
        self.read_channel = QComboBox()
        self.read_button = QPushButton("Read")
        self.read_button.clicked.connect(lambda: self.perform("read", self.read_channel.currentData()["handle"]))
        read_row = QHBoxLayout()
        read_row.addWidget(self.read_channel, 1)
        read_row.addWidget(self.read_button)
        form.addRow("Read value", read_row)
        right.addWidget(channels)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Traffic · UTF-8 and hex"))
        toolbar.addStretch()
        save = QPushButton("Save log…")
        save.clicked.connect(self.save_log)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.console.clear())
        toolbar.addWidget(save)
        toolbar.addWidget(clear)
        right.addLayout(toolbar)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(10000)
        self.console.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        right.addWidget(self.console, 1)
        self.command = QLineEdit()
        self.command.setPlaceholderText("Enter a command, then press Enter to send")
        self.command.returnPressed.connect(self.send)
        right.addWidget(self.command)
        send_row = QHBoxLayout()
        self.encoding = QComboBox()
        self.encoding.addItems(["UTF-8 text", "Hex bytes"])
        self.ending = QComboBox()
        self.ending.addItems(list(ENDINGS))
        self.ending.setCurrentText(self.settings.value("ending", "LF (\\n)"))
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send)
        send_row.addWidget(self.encoding)
        send_row.addWidget(QLabel("Line ending"))
        send_row.addWidget(self.ending)
        send_row.addStretch()
        send_row.addWidget(self.send_button)
        right.addLayout(send_row)
        splitter.addWidget(right_widget)
        splitter.setSizes([380, 700])
        self.setCentralWidget(root)
        self.backend.device_found.connect(self.device_found)
        self.backend.services_found.connect(self.services_found)
        self.backend.connection_changed.connect(self.connection_changed)
        self.backend.received.connect(lambda uuid, data: self.log("RX", f"[{uuid}] {format_payload(data)}"))
        self.backend.finished.connect(self.finished)
        self.log("INFO", "Scan to begin. Select the device's command characteristic after connecting.")
        self.update_controls()

    def log(self, kind, message):
        self.console.appendPlainText(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f"  {kind:4}  {message}")

    def perform(self, action, *args):
        self.busy = True
        self.statusBar().showMessage({"scan": "Scanning for 6 seconds…", "connect": "Connecting… approve any pairing prompt in KDE.",
                                      "disconnect": "Disconnecting…"}.get(action, "Working…"))
        self.update_controls()
        self.backend.submit(action, *args)

    def scan(self):
        self.rows.clear()
        self.device_table.setRowCount(0)
        self.perform("scan")

    def device_found(self, address, name, rssi):
        if address not in self.rows:
            self.rows[address] = self.device_table.rowCount()
            self.device_table.insertRow(self.rows[address])
        row = self.rows[address]
        for col, value in enumerate([name, address, f"{rssi} dBm"]):
            self.device_table.setItem(row, col, QTableWidgetItem(value))

    def toggle_connection(self):
        if self.connected:
            self.perform("disconnect")
        elif self.device_table.currentRow() >= 0:
            address = self.device_table.item(self.device_table.currentRow(), 1).text()
            self.log("INFO", f"Connecting to {address}")
            self.perform("connect", address, self.pair.isChecked())

    def connection_changed(self, connected):
        self.connected = connected
        if not connected:
            for combo in (self.write_channel, self.notify_channel, self.read_channel):
                combo.clear()
        self.log("INFO", "Connected" if connected else "Disconnected")
        self.update_controls()

    def services_found(self, rows):
        for row in rows:
            label = f"{row['description']} · {row['uuid']} · #{row['handle']}"
            props = row["properties"]
            self.log("GATT", f"{label} ({', '.join(props)}) — service {row['service']}")
            for combo, eligible in ((self.write_channel, "write" in props or "write-without-response" in props),
                                    (self.notify_channel, "notify" in props or "indicate" in props),
                                    (self.read_channel, "read" in props)):
                if eligible:
                    combo.addItem(label, row)
                    combo.setItemData(combo.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        for combo, uuid in ((self.write_channel, NUS_WRITE), (self.notify_channel, NUS_NOTIFY)):
            for index in range(combo.count()):
                if combo.itemData(index)["uuid"].lower() == uuid:
                    combo.setCurrentIndex(index)
        self.update_controls()
        self.log("INFO", "Select a receive channel and click Subscribe to see replies.")

    def update_write_modes(self):
        self.write_mode.clear()
        row = self.write_channel.currentData()
        if row:
            if "write" in row["properties"]:
                self.write_mode.addItem("With response", True)
            if "write-without-response" in row["properties"]:
                self.write_mode.addItem("Without response", False)
        self.update_controls()

    def update_controls(self):
        if not hasattr(self, "send_button"):
            return
        ready = self.connected and not self.busy and not self.closing
        idle = not self.busy and not self.closing
        self.scan_button.setEnabled(idle and not self.connected)
        self.device_table.setEnabled(idle and not self.connected)
        self.pair.setEnabled(idle and not self.connected and sys.platform != "darwin")
        self.connect_button.setText("Disconnect" if self.connected else "Connect")
        self.connect_button.setEnabled(idle and (self.connected or bool(self.device_table.selectedItems())))
        for widget in (self.write_channel, self.write_mode, self.notify_channel, self.read_channel):
            widget.setEnabled(ready and widget.count() > 0)
        self.send_button.setEnabled(ready and self.write_channel.count() > 0)
        self.command.setEnabled(ready and self.write_channel.count() > 0)
        self.read_button.setEnabled(ready and self.read_channel.count() > 0)
        self.subscribe_button.setEnabled(ready and self.notify_channel.count() > 0)
        row = self.notify_channel.currentData()
        subscribed = row and row["handle"] in self.backend.subscriptions
        self.subscribe_button.setText("Unsubscribe" if subscribed else "Subscribe")

    def toggle_notifications(self):
        handle = self.notify_channel.currentData()["handle"]
        self.perform("notify", handle, handle not in self.backend.subscriptions)

    def send(self):
        if not self.send_button.isEnabled():
            return
        try:
            payload = encode_command(self.command.text(), self.encoding.currentIndex() == 1, self.ending.currentText())
        except ValueError as exc:
            self.log("ERROR", str(exc))
            return
        self.pending_payload = payload
        self.settings.setValue("ending", self.ending.currentText())
        self.perform("send", self.write_channel.currentData()["handle"], payload, self.write_mode.currentData())

    def finished(self, action, error):
        self.busy = False
        if error:
            self.log("ERROR", error)
            self.statusBar().showMessage(error)
        else:
            if action == "send":
                self.log("TX", format_payload(self.pending_payload))
            elif action == "scan":
                self.log("INFO", f"Scan complete: {len(self.rows)} device(s).")
            elif action == "notify":
                self.log("INFO", "Notification subscription updated.")
            self.statusBar().showMessage("Connected" if self.connected else "Ready")
        self.update_controls()
        if action == "send":
            self.command.setFocus()

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save traffic log", "ble-terminal.log", "Log files (*.log);;All files (*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(self.console.toPlainText() + "\n")
            except OSError as exc:
                QMessageBox.warning(self, "Could not save log", str(exc))

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.update_controls()
        self.statusBar().showMessage("Closing Bluetooth connection…")
        self.shutdown_future = self.backend.shutdown()
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.timeout.connect(self.check_shutdown)
        self.shutdown_timer.start(100)

    def check_shutdown(self):
        if self.shutdown_future.done():
            self.shutdown_timer.stop()
            try:
                self.shutdown_future.result()
            except Exception as exc:
                self.log("ERROR", f"Disconnect during shutdown: {exc}")
            self.backend.stop()
            self.allow_close = True
            self.close()


def main():
    app = QApplication(sys.argv)
    configure_application(app)
    window = TerminalWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(200, window.close)
    sys.exit(app.exec())
