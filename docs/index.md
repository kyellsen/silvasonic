{% include "../README.md" %}

# Documentation Index

## Project Overview

- [Vision](VISION.md)
- [Milestone Roadmap](ROADMAP.md)
- [Agents](AGENTS.md)
- [Documentation Structure](STRUCTURE.md)

## Architecture

- Architecture Overview
- [Filesystem Governance](arch/filesystem_governance.md)
- [Messaging Patterns & Protocols](arch/messaging_patterns.md)
- [Port Allocation](arch/port_allocation.md)
- [Microphone Profiles](arch/microphone_profiles.md)
- [Lifecycle Configuration](arch/lifecycle-configuration.md)
- [Frontend Feature Specs](arch/frontend_features.md) · [Frontend Design System](arch/frontend_design_system.md)

## Services

### Implemented
- [Controller](services/controller.md) · [Database](services/database.md) · [Recorder](services/recorder.md)
- [Processor](services/processor.md) · [BirdNET](services/birdnet.md)
- [Redis](services/redis.md) · [Web-Mock](services/web_mock.md) · [DB-Viewer](services/db_viewer.md)
- [Gateway](services/gateway.md) 

### Planned
- [Web-Interface](services/web_interface.md) · [Icecast](services/icecast.md)
- [BatDetect](services/batdetect.md) · [Weather](services/weather.md) · [Tailscale](services/tailscale.md)

## Deployment

- [Deployment Guide (Placeholder)](deployment/README.md)

## ADRs

- [ADR-0001: Use uv as Python Package and Project Manager](adr/0001-use-uv.md)
- [ADR-0002: Use pyproject.toml for Configuration and Dependencies](adr/0002-use-pyproject-toml.md)
- [ADR-0003: Frontend Architecture ("The Modern Monolith")](adr/0003-frontend-architecture.md)
- [ADR-0004: Use Podman instead of Docker](adr/0004-use-podman.md)
- [ADR-0005: Separation of Immutable Code & Mutable State ("Two-Worlds")](adr/0005-two-worlds-separation.md)
- [ADR-0006: Host Bind Mounts as Default Persistence Strategy](adr/0006-bind-mounts-over-volumes.md)
- [ADR-0007: Rootless Podman & OS Compliance](adr/0007-rootless-os-compliance.md)
- [ADR-0008: Domain-Driven Workspace Isolation](adr/0008-domain-driven-isolation.md)
- [ADR-0009: Zero-Trust Data Sharing Policy](adr/0009-zero-trust-data-sharing.md)
- [ADR-0010: Naming Conventions](adr/0010-naming-conventions.md)
- [ADR-0011: Audio Recording Strategy (Raw vs Processed)](adr/0011-audio-recording-strategy.md)
- [ADR-0012: Use Pydantic for Data Validation](adr/0012-use-pydantic.md)
- [ADR-0013: Tier 2 Container Management — Podman-Only with podman-py](adr/0013-tier2-container-management.md)
- [ADR-0014: Dual Deployment Strategy — Compose (Dev) / Quadlets (Prod)](adr/0014-dual-deployment-strategy.md)
- [ADR-0015: NVMe-Only Storage Policy](adr/0015-nvme-only-storage.md)
- [ADR-0016: Hybrid YAML/DB Profile Management](adr/0016-hybrid-yaml-db-profiles.md)
- [ADR-0017: Service State Management — Desired vs. Actual State](adr/0017-service-state-management.md)
- [ADR-0018: Worker Pull Orchestration — Self-Service Analysis via DB Polling](adr/0018-worker-pull-orchestration.md)
- [ADR-0019: Unified Service Infrastructure — SilvaService Pattern](adr/0019-unified-service-infrastructure.md)
- [ADR-0020: Resource Limits & QoS — Protecting Data Capture Integrity](adr/0020-resource-limits-qos.md)
- [ADR-0021: Frontend Design System — Tailwind CSS + DaisyUI + ECharts + Wavesurfer.js](adr/0021-frontend-design-system.md)
- [ADR-0022: Live Log Streaming — Podman Logs via Redis SSE](adr/0022-live-log-streaming.md)
- [ADR-0023: Configuration Management — YAML Seed, DB Settings, Users Table](adr/0023-configuration-management.md)
- [ADR-0024: FFmpeg Audio Engine — Externalizing the Real-Time Audio Path](adr/0024-ffmpeg-audio-engine.md)
- [ADR-0025: Recordings Table — Standard PostgreSQL Table (No Hypertable)](adr/0025-recordings-standard-table.md)
- [ADR-0026: Database Engine Selection for Edge Analytics](adr/0026-timescaledb-edge-analytics.md)
- [ADR-0027: BirdNET Inference Engine](adr/0027-birdnet-inference-engine.md)
- [ADR-0029: System Worker Orchestration](adr/0029-system-worker-orchestration.md)
- [ADR-0030: Database Runtime Resilience (Soft-Fail Loops)](adr/0030-database-resilience.md)
- [ADR-0030: Logging Cadence & Stats Extensibility](adr/0030-logging-cadence-and-stats.md)
- [ADR-0031: Runtime Tuning via DB Snapshot Refresh](adr/0031-runtime-tuning-snapshot-refresh.md)

## Development

- [Commit Message Guidelines](development/commit.md) — Standardized commit message format
- [Milestone v0.1.0](development/milestones/milestone_0_1_0.md) — Concrete implementation plan for Base Setup
- [Milestone v0.2.0](development/milestones/milestone_0_2_0.md) — Concrete implementation plan for Service Infrastructure
- [Milestone v0.3.0](development/milestones/milestone_0_3_0.md) — Concrete implementation plan for Tier 2 Container Management
- [Milestone v0.4.0](development/milestones/milestone_0_4_0.md) — Audio Recording: Dual Stream, Profile Injection, Generic USB Fallback, Watchdog
- [Milestone v0.5.0](development/milestones/milestone_0_5_0.md) — Analysis & Backend Orchestration: Processor Service (Indexer + Janitor)
- [Milestone v0.6.0](development/milestones/milestone_0_6_0.md) — Processor Cloud Sync (Single-Target Upload Worker)
- [Milestone v0.7.0](development/milestones/milestone_0_7_0.md) — Gateway (Reverse Proxy)
- [Milestone v0.7.1](development/milestones/milestone_0_7_1.md) — DB-Viewer
- [Milestone v0.8.0](development/milestones/milestone_0_8_0.md) — BirdNET (On-device Avian Inference)
- [Milestone v0.9.0](development/milestones/milestone_0_9_0.md) — Web-Interface & Field Deployment
- [Milestone v0.10.0](development/milestones/milestone_0_10_0.md) — Marketing Landing Page (Astro)
- [Milestone v1.0.0](development/milestones/milestone_1_0_0.md) — Production Release & ML Integration
- [Milestone Template](development/milestones/_template.md) — Template for new milestone documents
- [Service Blueprint](development/service_blueprint.md) — Mandatory patterns for new Python services
- [Testing Guide](development/testing.md)
- [Release Checklist](development/release_checklist.md) — Step-by-step guide for tagging a release

## User Stories

- [Controller](user_stories/controller.md) · [Recorder](user_stories/recorder.md)
- [BirdNET](user_stories/birdnet.md) · [BatDetect](user_stories/batdetect.md)
- [Processor](user_stories/processor.md) · [Gateway](user_stories/gateway.md)
- [Icecast](user_stories/icecast.md) · [Cloud Sync](user_stories/cloud_sync.md)
- [Web-Interface](user_stories/web_interface.md)

## Hardware

- [Hardware Specifications](hardware.md)
- [Microphone Profiles](arch/microphone_profiles.md)

## Reference

- [Glossary](glossary.md) — Canonical domain language definitions

