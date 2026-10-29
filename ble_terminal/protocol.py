"""Encoding helpers independent of the GUI and Bluetooth hardware."""

ENDINGS = {"None": b"", "LF (\\n)": b"\n", "CR (\\r)": b"\r", "CRLF (\\r\\n)": b"\r\n"}
NUS_WRITE = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_NOTIFY = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


def encode_command(text: str, hexadecimal: bool, ending: str) -> bytes:
    try:
        payload = bytes.fromhex(text) if hexadecimal else text.encode("utf-8")
    except ValueError as exc:
        raise ValueError("Enter complete hexadecimal bytes, for example: 01 FF 0A") from exc
    payload += ENDINGS[ending]
    if not payload:
        raise ValueError("Enter a command before sending.")
    return payload


def format_payload(data: bytes) -> str:
    return f"{data.decode('utf-8', errors='backslashreplace')!r}  |  {data.hex(' ').upper()}"
