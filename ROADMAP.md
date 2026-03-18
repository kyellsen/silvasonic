# Silvasonic — Roadmap

> **Status:** v0.3.0 — Tier 2 Container Management

---

## Milestone Roadmap

| Version    | Milestone                                                                                                                                                                                                                                                                 | Status        |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **v0.1.0** | Requirements Engineering & Specification — Complete specification of all features, tech stack, architecture, and service logic up to v1.0.0 (MVP) in `.md` files with clear roadmap. Repo structure, core pkg, DB, CI pipeline, ADRs, Podman as implementation foundation | ✅ Done        |
| **v0.2.0** | Service Infrastructure — Redis container, `SilvaService` base class, `core.service`, `core.redis`, `core.heartbeat`. All services inherit unified lifecycle. Heartbeats go live (ADR-0019). Web-Mock dev UI                                                               | ✅ Done        |
| **v0.3.0** | Controller manages Recorder lifecycle (start/stop via `podman-py`, reconciliation loop, Profile Injection)                                                                                                                                                                | ✅ Done        |
| v0.4.0     | Recorder writes .wav files (Dual Stream), Generic USB Fallback Profile, 3-Tier Auto-Onboarding (Score 100/50/0)                                                                                                                                                                | ⏳ Planned     |
| v0.5.0     | Processor service (Ingestion, Indexing, Janitor — immutable Tier 1)                                                                                                                                                                                                       | ⏳ Planned     |
| v0.6.0     | Uploader (immutable Tier 2, Controller-managed, FLAC compression, remote sync)                                                                                                                                                                                            | ⏳ Planned     |
| v0.7.0     | Gateway (Caddy reverse proxy, HTTPS termination, internal routing)                                                                                                                                                                                                        | ⏳ Planned     |
| v0.8.0     | Web-Interface — Real-time status dashboard (Read+Subscribe), service control via DB + nudge                                                                                                                                                                               | ⏳ Planned     |
| v0.9.0     | Icecast — Live Opus audio stream from Recorder to Web-Interface                                                                                                                                                                                                           | ⏳ Planned     |
| v1.0.0     | MVP — Production-ready field deployment (Podman Quadlets, Ansible)                                                                                                                                                                                                        | ⏳ Planned     |
| v1.1.0     | BirdNET — On-device avian species classification                                                                                                                                                                                                                          | ⏳ Planned     |
| v1.2.0     | Weather — Environmental data correlation                                                                                                                                                                                                                                  | ⏳ Planned     |
| v1.3.0     | BatDetect — On-device bat species classification                                                                                                                                                                                                                          | ⏳ Planned     |
| v1.5.0     | Tailscale — Secure remote access, VPN mesh networking                                                                                                                                                                                                                     | ⏳ Planned     |

---

## Detailed Implementation Plans

For concrete, phase-level implementation tasks see:

- **[Milestone v0.1.0](docs/development/milestone_0_1_0.md)** — Phases & tasks for Requirements Engineering & Specification
- **[Milestone v0.2.0](docs/development/milestone_0_2_0.md)** — Phases & tasks for Service Infrastructure
- **[Milestone v0.3.0](docs/development/milestone_0_3_0.md)** — Phases & tasks for Tier 2 Container Management
- **[Milestone v0.4.0](docs/development/milestone_0_4_0.md)** — Phases & tasks for Audio Recording (Dual Stream)

---

## See Also

- **[VISION.md](VISION.md)** — Core philosophy, architecture, design principles
- **[README.md](README.md)** — Project overview, quick start
- **[docs/index.md](docs/index.md)** — Full technical documentation
