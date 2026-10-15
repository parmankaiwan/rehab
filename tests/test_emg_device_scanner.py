from types import SimpleNamespace

from backend.emg.device_scanner import classify_port, scan_serial_devices


def port(device, description='', hwid='', vid=None, pid=None, **values):
    defaults = dict(device=device, name=device, description=description, hwid=hwid, vid=vid, pid=pid, serial_number=None, manufacturer=None, product=None, interface=None, location=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_vid_pid_and_usb_hwid_are_usb():
    assert classify_port(port('COM7', vid=0x303A, pid=0x1001))[0]
    assert classify_port(port('COM5', hwid='USB VID_10C4&PID_EA60'))[0]


def test_bluetooth_builtin_and_virtual_are_hidden_by_default():
    ports = [
        port('COM1', 'Communications Port'),
        port('COM3', 'Bluetooth Serial Port', 'BTHENUM'),
        port('COM9', 'Virtual COM Port'),
    ]
    assert scan_serial_devices(ports=ports) == []
    assert {item['port_type'] for item in scan_serial_devices(True, ports)} == {'BUILT_IN', 'BLUETOOTH', 'VIRTUAL'}


def test_multiple_usb_devices_are_structured_and_deduplicated():
    ports = [
        port('COM5', 'CP210x USB UART', vid=0x10C4, pid=0xEA60, manufacturer='Silicon Labs'),
        port('com5', 'duplicate', vid=0x10C4, pid=0xEA60),
        port('COM7', 'ESP32 USB JTAG', vid=0x303A, pid=0x1001, serial_number='ABC'),
        port('COM10', 'FTDI', hwid='USB VID_0403&PID_6001'),
    ]
    result = scan_serial_devices(ports=ports)
    assert [item['port'] for item in result] == ['COM10', 'COM5', 'COM7']
    assert result[1]['vid'] == '10C4'
    assert result[1]['pid'] == 'EA60'
    assert result[2]['serial_number'] == 'ABC'
    assert all(item['is_usb'] and item['is_present'] for item in result)


def test_each_scan_uses_current_enumeration_without_stale_cache():
    connected = [port('COM7', vid=0x303A, pid=0x1001)]
    assert [item['port'] for item in scan_serial_devices(ports=connected)] == ['COM7']
    assert scan_serial_devices(ports=[]) == []
