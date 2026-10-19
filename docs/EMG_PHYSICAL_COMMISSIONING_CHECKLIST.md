# FlexMap physical EMG commissioning checklist

This checklist is for bench engineering verification. It is not an electrical-safety approval and must not be used to authorize human-connected testing.

## Confirmed software configuration

- Board target: original ESP32 development board (`esp32dev`).
- Sensor signal input: ADC1 GPIO32.
- Channels: one.
- ADC configuration: 12-bit, 11 dB attenuation, raw range 0–4095 counts.
- Serial: 115200 baud, 8-N-1 over USB/CP210x.
- Packet protocol: `CSV_CHANNELS`; one numeric ADC value followed by a newline.
- Target sampling rate: 1000 samples/second.
- Wi-Fi: not used by the firmware.
- Preferred configured port: COM9. A COM number is not a persistent device identity.

The current packet format has no device sequence ID or device timestamp. FlexMap can measure host receive rate and detect invalid lines, but it cannot prove pre-ingestion packet loss or device-clock accuracy with this firmware. Host-generated sequence numbers must not be described as device sequence continuity.

## Before connecting

- [ ] No electrodes or leads are connected to a person.
- [ ] Sensor model and analogue output range are documented.
- [ ] ESP32 input is wired to GPIO32 and common ground as designed.
- [ ] The sensor output cannot exceed the ESP32 ADC input range.
- [ ] The power source and all USB/computer connections are documented.
- [ ] A data-capable USB cable is used.
- [ ] A responsible electrical-safety reviewer is identified before any human test.

## Non-invasive device preflight

Run:

```powershell
& '..\CV part\.venv\Scripts\python.exe' scripts\check_emg_hardware.py --require-device
```

- [ ] A USB serial device is detected.
- [ ] VID/PID and serial number are recorded when Windows provides them.
- [ ] The selected device is the intended ESP32, not a Bluetooth COM port.
- [ ] No other serial monitor, uploader, or FlexMap agent owns the port.

## Firmware and protocol

- [ ] Review `backend/emg/firmware_backend/include/board_config.h` against the physical wiring.
- [ ] Build the firmware successfully with PlatformIO.
- [ ] Do not flash until board identity, pin, channel count, and safe input range are confirmed.
- [ ] After flashing, verify that every emitted line is one numeric ADC value.
- [ ] Verify five consecutive valid packets before calling the stream connected.

## Bench acquisition

- [ ] Use a safe known bench signal or disconnected-input baseline; do not attach a person.
- [ ] Capture at least 60 seconds for timing validation.
- [ ] Record target and measured sample rate separately.
- [ ] Record valid samples, invalid packets, ADC minimum/maximum, clipping ratio, unique values, and baseline noise.
- [ ] Record that device-sequence loss and device-clock drift are unavailable with `CSV_CHANNELS`.
- [ ] Disconnect and reconnect the USB device once; confirm status and serial-handle recovery.
- [ ] Confirm a second process cannot open the same port.

## Live and recording workflow

- [ ] `/master/live/emg` shows fresh real samples and the measured host receive rate.
- [ ] Disconnecting the board changes the state away from `RUNNING`.
- [ ] Mock mode, if used separately, is visibly identified and never counted as physical validation.
- [ ] Create a bounded recording with an engineering-test label.
- [ ] Confirm raw sample count, duration, timestamps, quality report, and raw checksum.
- [ ] Do not mark the recording as human research data or training eligible.

## Private vault persistence

- [ ] Save through the authenticated EMG workflow.
- [ ] Confirm metadata and raw artifact exist in the private EMG vault.
- [ ] Compare the local and stored SHA-256 checksums.
- [ ] Restart only FastAPI, reopen the same recording, and compare ID, sample count, duration, and checksum.
- [ ] Confirm unauthorized artifact access remains blocked.

## Shutdown

- [ ] Exit through the FlexMap supervisor.
- [ ] Confirm streaming stops and the serial port is released.
- [ ] Confirm no recording began automatically.
- [ ] Confirm existing local and Supabase records remain unchanged.
- [ ] Relaunch and verify the board can reconnect cleanly.
