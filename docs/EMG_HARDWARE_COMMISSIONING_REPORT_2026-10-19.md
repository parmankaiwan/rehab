# FlexMap EMG hardware commissioning report

Date: 2026-10-19 (Asia/Bangkok)

Scope: non-human bench commissioning of the configured ESP32/EMG acquisition path. No application schema, CV function, existing research recording, or Supabase object was changed.

## Configuration evidence

| Item | Observed configuration |
| --- | --- |
| Preferred serial port | COM9 |
| Transport | USB serial through CP210x expected |
| Baud | 115200, 8-N-1 |
| Protocol | `CSV_CHANNELS` |
| Channel count | 1 |
| Target rate | 1000 samples/second |
| ADC | ESP32 ADC1, GPIO32, 12-bit, 11 dB attenuation |
| Packet | One numeric ADC count followed by newline |
| Device timestamp | Not provided by current firmware |
| Device sequence ID | Not provided by current firmware |

The repository records that an ESP32-D0WD-V3 revision 3.1 with a CP210x bridge was detected on COM9 on 2026-09-03. That historical note is not evidence that the board was connected during this commissioning run.

## Actual device evidence

The Windows serial inventory contained only:

- COM3: Microsoft Bluetooth serial link
- COM4: Microsoft Bluetooth serial link

No USB serial device, CP210x bridge, or COM9 endpoint was present. The authenticated backend independently returned the same inventory. The configured COM9 port was absent.

Backend EMG status was `DISCONNECTED`, with zero channels, zero valid samples, zero invalid packets, no active serial reader, and recording state `IDLE`. This is the correct safe status.

## Result matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Configuration inspection | PASS | Firmware, parser, agent configuration, and serial manager agree on 115200 / one channel / `CSV_CHANNELS`. |
| Non-invasive device enumeration | PASS | Preflight and authenticated API both enumerated ports without opening them. |
| ESP32/CP210x detected now | BLOCKED | No USB serial device; configured COM9 absent. |
| Agent started | NOT TESTED | Integrated supervisor was not restarted because older local services still own ports 3000/8000. |
| Board connected | BLOCKED | Physical USB board unavailable. |
| Fresh valid samples | BLOCKED | No board; backend correctly reports zero samples. |
| Firmware build | BLOCKED | PlatformIO is not installed in the available project Python environment. |
| Firmware flash | NOT TESTED | No board and trusted firmware manifest is empty; API flashing remains disabled. |
| Protocol compatibility | BLOCKED | Source/parser alignment is verified, but no physical packets were received. |
| Channel count | BLOCKED | Configured as one; cannot validate against physical packets. |
| Measured sample rate | BLOCKED | No physical samples. Target is 1000 Hz; no measured value is claimed. |
| Device sequence consistency | NOT TESTED | Current firmware sends neither sequence IDs nor device timestamps. |
| Packet loss before ingestion | NOT TESTED | Cannot be proven with `CSV_CHANNELS`; host sequence covers parsed samples only. |
| Invalid packet count | BLOCKED | Current zero count reflects no connection, not a successful capture. |
| ADC minimum/maximum and clipping | BLOCKED | No physical samples. |
| Noise/baseline characteristics | BLOCKED | No safe bench signal or board. |
| Live waveform | BLOCKED | No physical samples; synthetic mode was not used as a substitute. |
| Manual recording workflow | BLOCKED | A real bounded bench recording cannot be created without the board. |
| Supabase configuration | PASS | Authenticated status: authoritative Supabase, private `flexmap-emg-vault`, storage state `READY`, schema `CURRENT`. |
| Real artifact upload/checksum/retrieval | BLOCKED | No physical recording was created; no synthetic upload was substituted. |
| Backend-restart persistence | BLOCKED | Requires a successfully saved physical engineering recording first. |
| Physical disconnect/reconnect | BLOCKED | Board unavailable. |
| Duplicate physical port ownership | BLOCKED | Requires the physical port; automated ownership tests pass. |
| Automatic startup/shutdown with board | BLOCKED | Requires the board and removal of older independently started local services. |
| Electrical safety for human connection | NOT TESTED | Software cannot establish electrical isolation or medical safety. |

## Automated evidence

- Full backend suite: 148 passed, 3 dependency/deprecation warnings.
- Focused EMG frontend suite: 15 passed across 7 test files.
- Focused serial/commissioning/backend suite: 33 passed.
- Preflight regression tests: configuration secrecy, Bluetooth exclusion, and USB candidate selection all passed.

These automated results validate software behavior only. They do not constitute physical acquisition evidence.

## Required next physical step

1. Keep all electrodes disconnected from people.
2. Connect the intended ESP32 using a known data-capable USB cable.
3. Confirm that Windows Device Manager shows a CP210x/USB serial port.
4. Run `scripts/check_emg_hardware.py --require-device` again.
5. If the board appears on a port other than COM9, update the local preferred port only after confirming its VID/PID/device identity.
6. Install PlatformIO and build the firmware; do not flash until GPIO32 wiring and the sensor output range are confirmed.
7. Continue with the bench capture checklist in `EMG_PHYSICAL_COMMISSIONING_CHECKLIST.md`.

## Safety conclusion

The software correctly refuses to report an EMG connection without a board and fresh samples. Physical commissioning is incomplete. No human-connected test is authorized by this report.
