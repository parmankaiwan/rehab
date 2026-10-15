from __future__ import annotations

from typing import Any, Iterable

USB_MARKERS = ('USB', 'VID_', 'PID_')
BLUETOOTH_MARKERS = ('BLUETOOTH', 'BTHENUM', 'BTHMODEM')
VIRTUAL_MARKERS = ('VIRTUAL', 'COM0COM', 'VSP', 'ELTIMA', 'SOCAT')
BUILT_IN_MARKERS = ('COMMUNICATIONS PORT', 'STANDARD SERIAL')


def _text(port: Any) -> str:
    fields = ('hwid', 'description', 'name', 'manufacturer', 'product', 'interface')
    return ' '.join(str(getattr(port, field, '') or '') for field in fields).upper()


def classify_port(port: Any) -> tuple[bool, str]:
    text = _text(port)
    if any(marker in text for marker in BLUETOOTH_MARKERS):
        return False, 'BLUETOOTH'
    if any(marker in text for marker in VIRTUAL_MARKERS):
        return False, 'VIRTUAL'
    has_identity = getattr(port, 'vid', None) is not None and getattr(port, 'pid', None) is not None
    has_usb_hwid = any(marker in text for marker in USB_MARKERS)
    if has_identity or has_usb_hwid:
        return True, 'USB_SERIAL'
    if any(marker in text for marker in BUILT_IN_MARKERS):
        return False, 'BUILT_IN'
    return False, 'OTHER'


def _hex(value: Any) -> str | None:
    return f'{value:04X}' if isinstance(value, int) else None


def scan_serial_devices(include_non_usb: bool = False, ports: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    if ports is None:
        from serial.tools import list_ports

        ports = list_ports.comports()
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for port in ports:
        device = str(getattr(port, 'device', '') or '').strip()
        identity = device.casefold()
        if not device or identity in seen:
            continue
        seen.add(identity)
        is_usb, port_type = classify_port(port)
        if not is_usb and not include_non_usb:
            continue
        vid, pid = _hex(getattr(port, 'vid', None)), _hex(getattr(port, 'pid', None))
        found.append({
            'port': device,
            'name': getattr(port, 'name', None),
            'description': getattr(port, 'description', None),
            'manufacturer': getattr(port, 'manufacturer', None),
            'product': getattr(port, 'product', None),
            'interface': getattr(port, 'interface', None),
            'location': getattr(port, 'location', None),
            'serial_number': getattr(port, 'serial_number', None),
            'hardware_id': getattr(port, 'hwid', None),
            'hwid': getattr(port, 'hwid', None),
            'vid': vid,
            'pid': pid,
            'usb_vid': vid,
            'usb_pid': pid,
            'is_usb': is_usb,
            'is_present': True,
            'port_type': port_type,
        })
    return sorted(found, key=lambda item: item['port'].casefold())
