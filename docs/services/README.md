# Services

Overview of Silvasonic services (implemented and planned). Full documentation for implemented services resides in each service directory (`services/*/README.md`). Planned services are documented in `docs/services/`.

| Service        | Tier | Description                                       | Documentation         |
| -------------- | ---- | ------------------------------------------------- | --------------------- |
| **Controller** | 1    | Central orchestration, USB detection, Tier 2 mgmt | [Spec](controller.md) |
| **Database**   | 1    | TimescaleDB/PostgreSQL, central state management  | [Spec](database.md)   |
| **Gateway**    | 1    | (Planned) Caddy reverse proxy, HTTPS, auth        | [Spec](gateway.md)    |
| **Processor**  | 1    | (Planned) Indexing, Janitor, retention management | [Spec](processor.md)  |
| **Recorder**   | 2    | Audio capture from USB microphones to NVMe        | [Spec](recorder.md)   |
| **BirdNET**    | 2    | (Planned) On-device avian species classification  | [Spec](birdnet.md)    |
| **BatDetect**  | 2    | (Planned) On-device bat species classification    | [Spec](batdetect.md)  |
| **Tailscale**  | 1    | (Planned) Secure remote access, VPN mesh          | [Spec](tailscale.md)  |
