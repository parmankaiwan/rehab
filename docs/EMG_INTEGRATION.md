# FlexMap integrated EMG

## Current architecture

EMG hardware or mock source → background raw acquisition worker → bounded main FastAPI buffer → ticket-authenticated batched WebSocket → main Next.js canvas.

Normal services are the main backend on port 8000 and main frontend on port 3000. Ports 8100 and 3100 are not required.

## Raw protocols

`VALUE_ONLY`, `TIMESTAMP_VALUE`, `CSV_CHANNELS`, `TIMESTAMP_CSV_CHANNELS`, and `SEQUENCE_TIMESTAMP_CSV` are accepted. USB serial is discovered with pyserial; no COM port is hard-coded. One reader can be active. Mock mode is available without hardware.

## Dataset organization

Raw recordings are stored under `data/dataset_vault/rehab/<rehab_slug>/emg/recordings/<EMG-ID>/`. Each module has separate dataset and training manifests. Mock samples and new samples are not training eligible by default. `emg_raw.csv` is canonical and is never filtered or overwritten.

## Research boundary

Raw EMG amplitude is not a direct measurement of muscle strength. CV does not infer activation. This subsystem performs read, display, record, and organization only. It performs no filtering, RMS, normalization, activation classification, diagnosis, sensor fusion, rehabilitation scoring, or stimulation/FES control.

## Future architecture

CV + EMG → explicit timestamp synchronization → future sensor fusion → future research application. Shared `subject_id`, `session_id`, `rehab_type`, trial, and monotonic timestamps prepare the schema; fusion is not implemented.