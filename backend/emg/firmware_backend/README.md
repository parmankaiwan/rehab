# FlexMap EMG firmware backend

This directory contains the source and tooling for the verified FlexMap ESP32 EMG firmware.

Private full-flash backups belong in `backups/` and are excluded from Git because they may contain device credentials. Generated binaries and build output are excluded as well.

Detected device (2026-09-03): ESP32-D0WD-V3 revision 3.1, 4 MB flash, connected through a Silicon Labs CP210x bridge on COM9.

Verified acquisition configuration: one analog EMG channel on ADC1 GPIO32.

Do not flash a generated image until the physical EMG sensor input pins, channel count, and electrical input range are confirmed.

## Configure and build

1. Enter the verified ADC1 GPIO pins in `include/board_config.h`.
2. Build with `py -m platformio run -d backend/emg/firmware_backend`.
3. Disconnect the EMG backend from COM9 before uploading.
4. Upload with `py -m platformio run -d backend/emg/firmware_backend -t upload`.
5. In FlexMap, select COM9, 115200 baud, one channel, and `CSV_CHANNELS`.

The compile-time pin checks prevent a guessed wiring configuration from being written to a physical device.
