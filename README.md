# Silvasonic

**Autonomous Bioacoustic Recording Station for Raspberry Pi 5**

Silvasonic is a professional-grade, containerized recording system designed for long-term bioacoustic monitoring in the field. It transforms a Raspberry Pi 5 into a resilient recording station capable of capturing the entire soundscape—from avian vocalizations to ultrasonic bat calls.

The system prioritizes **Data Capture Integrity** above all else. It is designed to run autonomously for years, buffering data locally on high-speed NVMe storage and synchronizing with central servers (e.g., Nextcloud) via a "Store & Forward" architecture.

**Target Audience:** Researchers, conservationists, and bioacoustic enthusiasts requiring robust, unsupervised data collection.

> **Status:** v0.1.0 (Initial Development / MVP)

---

🤖 **Are you an AI Agent?**
Please consult **[AGENTS.md](AGENTS.md)** immediately for strict architectural constraints, language policies, and file system rules.

---

## Core Philosophy

1.  **Record First, Analyze Later:** The primary directive is to never miss a sound. Analysis (BirdNET) is secondary to raw data preservation.
2.  **Appliance Architecture:** Designed as a firmware-like appliance. Boots directly from NVMe. No SD cards used in production.
3.  **Fleet Ready:** Built for scale. Supports "Flash & Go" provisioning and centralized fleet management via Ansible and VPN.

## Documentation Structure

* **Project Documentation:** See the `docs/` directory for architecture decisions, hardware BOM, and glossaries.
* **Service Documentation:** Each service contains its own `README.md` (e.g., `services/recorder/README.md`) detailing inputs, outputs, and configuration.

## Tech Stack

Silvasonic is a modern Python monolith split into micro-services, managed via a Monorepo.

* **Hardware Target:** Raspberry Pi 5 (RaspiOS Lite) + NVMe SSD.
* **Runtime:** Podman (Rootless Containers) & Podman Compose.
* **Build System:** hatchling.
* **Language:** Python 3.11+ (managed by `uv`).
* **Frontend:** FastAPI (Jinja2) + HTMX + Alpine.js. Styled with Tailwind CSS & DaisyUI.
* **Visualization:** Wavesurfer.js (Spectrograms) & Plotly.js (Analytics).
* **UX Design:** IDE-inspired "Workspace" layout with Bento-Grid Dashboard. Dark-mode default, fully responsive.
* **Documentation:** MkDocs Material (Developer) & Astro (Product Page).

## Services Architecture

The system is composed of the following containerized services:

* **controller**: Hardware/Container manager. Dynamically detects USB microphones and manages service lifecycles.
* **recorder**: Critical path. Buffers audio in RAM and writes dual-stream RAW WAV files (384kHz & 48kHz) to NVMe to decouple recording from processing.
* **processor**: Local data handler. Indexes files, generates spectrograms, and manages storage retention (Janitor).
* **uploader**: Handles data exfiltration. Compresses raw data (FLAC 384kHz) and syncs to remote storage using rclone.
* **web-interface**: Local management console. Provides status monitoring, configuration, and data exploration.
* **database**: Central state management (TimescaleDB / PostgreSQL).
* **redis**: Message broker for live state, pub/sub events, and job queues.
* **gateway**: Caddy Reverse Proxy handling HTTPS and authentication.
* **birdnet**: (Optional) On-device inference for avian species classification.
* **weather**: Correlates acoustic data with environmental measurements.
* **tailscale**: Provides secure, zero-config remote access and VPN mesh networking.

## Deployment & Fleet Management

Silvasonic supports two deployment models:

1.  **Single Node:** Manual provisioning via local installer scripts.
2.  **Fleet Mode:** "Zero-Touch" provisioning using a bootstrap image. The device connects to a VPN management network upon boot and pulls its configuration via **Ansible**.

## Developer Tools & Libraries

We rely on a standardized set of modern Python tools:

* **Core:** `uv`, `hatchling`, `pydantic`, `structlog`
* **Data & Async:** `asyncpg`, `sqlalchemy`, `numpy`, `pandas`, `polars`
* **System:** `psutil`, `soundfile`, `pyYAML`
* **Quality & Test:** `ruff`, `mypy`, `pytest`, `playwright`, `pre-commit`

## Development Setup

We use a unified `Makefile` interface to abstract the scripts located in `scripts/`.

| Command | Underlying Script | Description |
| :--- | :--- | :--- |
| **make setup** | `scripts/init.sh` | Initializes the environment, creates folders, and installs `uv` dependencies. |
| **make run** | `scripts/run.sh` | Builds and starts the full stack via Podman Compose. |
| **make check** | `scripts/check.sh` | Runs the full CI suite: Formatting check, Linting, and Tests. |
| **make fix** | `scripts/fix.sh` | Automatically fixes formatting (Ruff) and auto-fixable lint errors. |
| **make clean** | `scripts/clean.sh` | Removes caches, logs, temporary artifacts, and the `.tmp/` directory. |

### Prerequisites

* Linux (e.g., Debian or Fedora).
* `uv` installed.
* `podman` & `podman-compose` installed.

## License

This project is licensed under the **CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International).