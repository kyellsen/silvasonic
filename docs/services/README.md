# Services

Overview of implemented Silvasonic services. Full documentation resides in each service directory (`services/*/README.md`).

| Service        | Tier | Description                                       | Documentation                                 |
| -------------- | ---- | ------------------------------------------------- | --------------------------------------------- |
| **Controller** | 1    | Central orchestration, USB detection, Tier 2 mgmt | [README](../../services/controller/README.md) |
| **Database**   | 1    | TimescaleDB/PostgreSQL, central state management  | [README](../../services/database/README.md)   |
| **Recorder**   | 2    | Audio capture from USB microphones to NVMe        | [README](../../services/recorder/README.md)   |
