# Services

Übersicht der implementierten Silvasonic-Services. Die vollständige Dokumentation befindet sich jeweils im Service-Verzeichnis (`services/*/README.md`).

| Service        | Tier | Beschreibung                                        | Dokumentation                                 |
| -------------- | ---- | --------------------------------------------------- | --------------------------------------------- |
| **Controller** | 1    | Zentrale Orchestrierung, USB-Erkennung, Tier-2-Mgmt | [README](../../services/controller/README.md) |
| **Database**   | 1    | TimescaleDB/PostgreSQL, zentraler Speicher          | [README](../../services/database/README.md)   |
| **Recorder**   | 2    | Audio-Aufnahme von USB-Mikrofonen auf NVMe          | [README](../../services/recorder/README.md)   |
