import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from ble_terminal.app import TerminalWindow
from ble_terminal.backend import BluetoothBackend
from ble_terminal.protocol import encode_command, NUS_NOTIFY, NUS_WRITE
from ble_terminal.icons import APP_ID, application_icon, configure_application


class EncodingTests(unittest.TestCase):
    def test_text_encoding_and_terminator(self):
        self.assertEqual(encode_command("café", False, "CRLF (\\r\\n)"), b"caf\xc3\xa9\r\n")

    def test_binary_preserves_bytes(self):
        self.assertEqual(encode_command("00 FF 0a", True, "None"), b"\x00\xff\x0a")

    def test_bad_or_empty_commands(self):
        for value in ("F", "GG", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_command(value, True, "None")


class BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Use the test event loop so no worker thread is needed in these tests.
        self.backend = BluetoothBackend.__new__(BluetoothBackend)
        super(BluetoothBackend, self.backend).__init__()
        self.backend.client = None
        self.backend.devices = {"AA:BB": SimpleNamespace(address="AA:BB")}
        self.backend.subscriptions = set()
        self.char = SimpleNamespace(handle=7, uuid=NUS_WRITE, description="UART", properties=["write"],
                                    max_write_without_response_size=20)
        service = SimpleNamespace(uuid="service", characteristics=[self.char])

        class Services(list):
            def get_characteristic(inner, handle):
                return self.char

        self.client = SimpleNamespace(is_connected=True, services=Services([service]), connect=AsyncMock(),
                                      disconnect=AsyncMock(), write_gatt_char=AsyncMock(),
                                      start_notify=AsyncMock(), stop_notify=AsyncMock(),
                                      read_gatt_char=AsyncMock(return_value=bytearray(b"OK")))

    async def test_connect_discovers_channels_and_disconnects(self):
        rows = []
        self.backend.services_found.connect(rows.extend)
        with patch("ble_terminal.backend.BleakClient", return_value=self.client) as factory:
            await self.backend._connect("AA:BB", True)
        self.assertTrue(factory.call_args.kwargs["pair"])
        self.assertEqual(rows[0]["handle"], 7)
        await self.backend._disconnect()
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.backend.client)

    async def test_failed_connection_is_cleaned_up(self):
        self.client.connect.side_effect = RuntimeError("Out of range")
        with patch("ble_terminal.backend.BleakClient", return_value=self.client):
            with self.assertRaisesRegex(RuntimeError, "Out of range"):
                await self.backend._connect("AA:BB", False)
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.backend.client)

    async def test_write_limits_and_disconnected_write(self):
        self.backend.client = self.client
        await self.backend._send(7, b"AT\n", True)
        self.client.write_gatt_char.assert_awaited_once_with(self.char, b"AT\n", response=True)
        with self.assertRaisesRegex(ValueError, "20 bytes"):
            await self.backend._send(7, b"a" * 21, False)
        with self.assertRaisesRegex(ValueError, "512 bytes"):
            await self.backend._send(7, b"a" * 513, True)
        self.client.is_connected = False
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            await self.backend._send(7, b"AT", True)

    async def test_notification_and_read_round_trip(self):
        self.backend.client = self.client
        received = []
        self.backend.received.connect(lambda uuid, data: received.append((uuid, data)))
        await self.backend._notify(7, True)
        self.assertIn(7, self.backend.subscriptions)
        callback = self.client.start_notify.call_args.args[1]
        callback(self.char, bytearray(b"reply"))
        await self.backend._read(7)
        self.assertEqual(received, [(NUS_WRITE, b"reply"), (NUS_WRITE, b"OK")])
        await self.backend._notify(7, False)
        self.assertNotIn(7, self.backend.subscriptions)

    async def test_scanning_discovers_device_and_exits_context(self):
        backend = self.backend
        seen = []
        backend.device_found.connect(lambda *args: seen.append(args))

        class Scanner:
            def __init__(self, detection_callback):
                self.callback = detection_callback

            async def __aenter__(self):
                self.callback(SimpleNamespace(address="CC", name=None), SimpleNamespace(local_name="Sensor", rssi=-50))

            async def __aexit__(self, *args):
                seen.append("closed")

        with patch("ble_terminal.backend.BleakScanner", Scanner), patch("ble_terminal.backend.asyncio.sleep", AsyncMock()):
            await backend._scan()
        self.assertEqual(seen, [("CC", "Sensor", -50), "closed"])
        self.assertEqual(list(backend.devices), ["CC"])


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)
        cls.settings_dir = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls.settings_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings_dir.cleanup()

    def setUp(self):
        self.backend = BluetoothBackend()
        self.window = TerminalWindow(self.backend)

    def tearDown(self):
        if self.backend._thread.is_alive():
            self.backend.shutdown().result(timeout=3)
            self.backend.stop()
        self.window.allow_close = True
        self.window.close()

    def test_discovery_selection_and_uart_commands(self):
        window = self.window
        self.assertFalse(window.send_button.isEnabled())
        self.assertFalse(window.connect_button.isEnabled())
        window.device_found("AA:BB", "UART Sensor", -45)
        window.device_table.selectRow(0)
        self.assertTrue(window.connect_button.isEnabled())
        window.connection_changed(True)
        window.services_found([
            {"handle": 2, "uuid": "other", "description": "Other", "service": "test", "properties": ["write"]},
            {"handle": 7, "uuid": NUS_WRITE, "description": "UART TX", "service": "test", "properties": ["write-without-response"]},
            {"handle": 8, "uuid": NUS_NOTIFY, "description": "UART RX", "service": "test", "properties": ["notify", "read"]},
        ])
        self.assertEqual(window.write_channel.currentData()["handle"], 7)
        self.assertEqual(window.notify_channel.currentData()["handle"], 8)
        self.assertTrue(window.send_button.isEnabled())
        self.assertFalse(window.scan_button.isEnabled())
        window.command.setText("AT")
        window.ending.setCurrentText("CRLF (\\r\\n)")
        with patch.object(self.backend, "submit") as submit:
            window.send()
        submit.assert_called_once_with("send", 7, b"AT\r\n", False)
        window.finished("send", "")
        self.assertIn("41 54 0D 0A", window.console.toPlainText())
        window.connection_changed(False)
        self.assertFalse(window.send_button.isEnabled())
        self.assertEqual(window.write_channel.count(), 0)

    def test_errors_are_visible_and_controls_recover(self):
        window = self.window
        with patch.object(self.backend, "submit"):
            window.scan()
        self.assertFalse(window.scan_button.isEnabled())
        window.finished("scan", "Bluetooth adapter is powered off")
        self.assertTrue(window.scan_button.isEnabled())
        self.assertIn("powered off", window.console.toPlainText())

    def test_application_and_window_have_bluetooth_icon(self):
        self.assertEqual(self.app.desktopFileName(), APP_ID)
        for icon in (application_icon(), self.app.windowIcon(), self.window.windowIcon()):
            self.assertFalse(icon.isNull())
            self.assertFalse(icon.pixmap(32, 32).isNull())

    def test_window_close_finishes_worker(self):
        self.window.close()
        for _ in range(100):
            self.app.processEvents()
            if self.window.shutdown_future.done():
                break
            self.backend._thread.join(timeout=0.01)
        self.window.check_shutdown()
        self.assertTrue(self.window.allow_close)
        self.assertFalse(self.backend._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
