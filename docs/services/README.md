# Services

Overview of all Silvasonic services (implemented and planned). Authoritative documentation for implemented services resides in the service directory (`services/*/README.md`). Planned services are documented in `docs/services/`.

| Service           | Tier | Status         | Description                                       | Documentation                                 |
| ----------------- | ---- | -------------- | ------------------------------------------------- | --------------------------------------------- |
| **Controller**    | 1    | ✅ Implemented  | Central orchestration, USB detection, Tier 2 mgmt | [README](../../services/controller/README.md) |
| **Database**      | 1    | ✅ Implemented  | TimescaleDB/PostgreSQL, central state management  | [README](../../services/database/README.md)   |
| **Recorder**      | 2    | ✅ Scaffold     | Audio capture from USB microphones to NVMe        | [README](../../services/recorder/README.md)   |
| **Redis**         | 1    | 📋 Planned v0.2 | Status bus, heartbeat TTL keys, Pub/Sub nudge     | [Spec](redis.md)                              |
| **Processor**     | 1    | 📋 Planned v0.5 | Indexing, Janitor, retention management           | [Spec](processor.md)                          |
| **Uploader**      | 2    | 📋 Planned v0.6 | Data exfiltration, FLAC compression, sync         | [Spec](uploader.md)                           |
| **Gateway**       | 1    | 📋 Planned v0.7 | Caddy reverse proxy, HTTPS, auth                  | [Spec](gateway.md)                            |
| **Web-Interface** | 1    | 📋 Planned v0.8 | Local management console, status dashboard        | [Spec](web_interface.md)                      |
| **Icecast**       | 1    | 📋 Planned v0.9 | Live audio streaming server (Opus mount points)   | [Spec](icecast.md)                            |
| **BirdNET**       | 2    | 📋 Planned v1.1 | On-device avian species classification            | [Spec](birdnet.md)                            |
| **Weather**       | 2    | 📋 Planned v1.2 | Environmental data correlation                    | [Spec](weather.md)                            |
| **BatDetect**     | 2    | 📋 Planned v1.3 | On-device bat species classification              | [Spec](batdetect.md)                          |
| **Tailscale**     | 1    | 📋 Planned v1.5 | Secure remote access, VPN mesh                    | [Spec](tailscale.md)                          |
