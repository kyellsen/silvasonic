# Documentation Index

## Project Overview

- [Project Readme](project_readme.md)
- [Vision](VISION.md)
- [Milestone Roadmap](ROADMAP.md)
- [Agents](AGENTS.md)

## Architecture

- [Architecture Overview](arch/README.md)
- [Filesystem Governance](arch/filesystem_governance.md)
- [Messaging Patterns & Protocols](arch/messaging_patterns.md)
- [Port Allocation](arch/port_allocation.md)
- [Microphone Profiles](arch/microphone_profiles.md)

## Services

- [Controller](services/controller.md) · [Database](services/database.md) · [Recorder](services/recorder.md)
- [Redis](services/redis.md) · [Web-Mock](services/web_mock.md) · [Processor](services/processor.md) · [Gateway](services/gateway.md)
- [Web-Interface](services/web_interface.md) · [Icecast](services/icecast.md) · [Uploader (Archived)](services/uploader.md)
  - [UI/UX Design System](services/web_interface/02_ui_ux_design_system.md)
  - [Web-Interface Feature Specs](services/web_interface_features.md)
- [BirdNET](services/birdnet.md) · [BatDetect](services/batdetect.md) · [Weather](services/weather.md) · [Tailscale](services/tailscale.md)

## Deployment

- [Deployment Guide (Placeholder)](deployment/README.md)

## ADRs

- [Architecture Decision Records](adr/README.md)

## Development

- [Development Guide](development/README.md)
- [Commit Message Guidelines](development/commit.md) — Standardized commit message format
- [Milestone v0.1.0](development/milestone_0_1_0.md) — Concrete implementation plan for Base Setup
- [Milestone v0.2.0](development/milestone_0_2_0.md) — Concrete implementation plan for Service Infrastructure
- [Milestone v0.3.0](development/milestone_0_3_0.md) — Concrete implementation plan for Tier 2 Container Management
- [Milestone v0.4.0](development/milestone_0_4_0.md) — Audio Recording: Dual Stream, Profile Injection, Generic USB Fallback, Watchdog
- [Milestone v0.5.0](development/milestone_0_5_0.md) — Analysis & Backend Orchestration: Processor Service (Indexer + Janitor)
- [Milestone v0.6.0](development/milestone_0_6_0.md) — Processor Cloud Sync (Single-Target Upload Worker)
- [Milestone v0.8.0](development/milestone_0_8_0.md) — BirdNET (On-device Avian Inference)
- [Milestone v0.9.0](development/milestone_0_9_0.md) — Web-Interface & Field Deployment
- [Milestone v0.10.0](development/milestone_0_10_0.md) — Marketing Landing Page (Astro)
- [Milestone v1.0.0](development/milestone_1_0_0.md) — Production Release & ML Integration
- [Milestone Template](development/milestone_template.md) — Template for new milestone documents
- [Service Blueprint](development/service_blueprint.md) — Mandatory patterns for new Python services
- [Testing Guide](development/testing.md)
- [Release Checklist](development/release_checklist.md) — Step-by-step guide for tagging a release
- [Future Features & Ideas](development/idea.md)

## User Stories

- [Controller](user_stories/controller.md) · [Recorder](user_stories/recorder.md)
- [BirdNET](user_stories/birdnet.md) · [BatDetect](user_stories/batdetect.md)
- [Processor](user_stories/processor.md) · [Gateway](user_stories/gateway.md)
- [Icecast](user_stories/icecast.md) · [Uploader (Archived)](user_stories/uploader.md)
- [Web-Interface](user_stories/web_interface.md)

## Hardware

- [Hardware Specifications](hardware.md)
- [Microphone Profiles](arch/microphone_profiles.md)

## Reference

- [API Reference (Planned)](api_reference.md)
- [Glossary](glossary.md) — Canonical domain language definitions

