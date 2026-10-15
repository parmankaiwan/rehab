# Serial protocol

- Transport: USB serial through CP210x
- Baud: 115200, 8-N-1
- Sampling target: 1000 samples/second
- ADC representation: unsigned 12-bit counts, 0 through 4095
- Line format: `channel_1` followed by newline
- Backend protocol: `CSV_CHANNELS` with one configured channel
- Wi-Fi: disabled/not used

The firmware emits numeric data only. This matches `backend/emg/parser.py` and avoids status text being counted as invalid EMG packets.
