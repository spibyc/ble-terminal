"""All BLE operations live on one persistent asyncio loop off the UI thread."""

import asyncio
from concurrent.futures import Future
from threading import Event, Thread

from bleak import BleakClient, BleakScanner
from PySide6.QtCore import QObject, Signal


class BluetoothBackend(QObject):
    device_found = Signal(str, str, int)
    services_found = Signal(object)
    received = Signal(str, bytes)
    connection_changed = Signal(bool)
    finished = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.client = None
        self.devices = {}
        self.scanner = None
        self.subscriptions = set()
        self._ready = Event()
        self._thread = Thread(target=self._run, daemon=True, name="bluetooth")
        self._thread.start()
        self._ready.wait()

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()
        self.loop.close()

    def submit(self, action: str, *args) -> Future:
        async def guarded():
            error = ""
            try:
                await getattr(self, "_" + action)(*args)
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            self.finished.emit(action, error)

        return asyncio.run_coroutine_threadsafe(guarded(), self.loop)

    async def _scan(self):
        self.devices.clear()

        def discovered(device, advertisement):
            self.devices[device.address] = device
            self.device_found.emit(device.address, advertisement.local_name or device.name or "Unnamed device", advertisement.rssi)

        async with BleakScanner(detection_callback=discovered):
            await asyncio.sleep(6)

    def _disconnected(self, client):
        if self.client is client:
            self.subscriptions.clear()
            self.connection_changed.emit(False)

    async def _connect(self, address: str, pair: bool):
        await self._disconnect()
        self.client = BleakClient(self.devices[address], disconnected_callback=self._disconnected, pair=pair, timeout=30)
        try:
            await self.client.connect()
            rows = []
            for service in self.client.services:
                for char in service.characteristics:
                    rows.append({"handle": char.handle, "uuid": char.uuid, "description": char.description,
                                 "service": service.uuid, "properties": list(char.properties)})
            self.connection_changed.emit(True)
            self.services_found.emit(rows)
        except BaseException:
            await self._disconnect()
            raise

    async def _disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.subscriptions.clear()
        self.connection_changed.emit(False)

    def _connected_client(self):
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("The device is disconnected. Connect again before continuing.")
        return self.client

    async def _send(self, handle: int, payload: bytes, response: bool):
        client = self._connected_client()
        char = client.services.get_characteristic(handle)
        limit = 512 if response else char.max_write_without_response_size
        if len(payload) > limit:
            raise ValueError(f"This write supports at most {limit} bytes; command is {len(payload)} bytes. Shorten the command.")
        await client.write_gatt_char(char, payload, response=response)

    async def _notify(self, handle: int, enabled: bool):
        client = self._connected_client()
        if enabled:
            await client.start_notify(handle, lambda sender, data: self.received.emit(sender.uuid, bytes(data)))
            self.subscriptions.add(handle)
        else:
            await client.stop_notify(handle)
            self.subscriptions.discard(handle)

    async def _read(self, handle: int):
        client = self._connected_client()
        data = await client.read_gatt_char(handle)
        self.received.emit(client.services.get_characteristic(handle).uuid, bytes(data))

    async def _shutdown(self):
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._disconnect()
        await self.loop.shutdown_asyncgens()

    def shutdown(self) -> Future:
        return asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)
