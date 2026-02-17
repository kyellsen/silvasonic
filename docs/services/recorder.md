# Recorder Service

> **Tier 2 — Application (Managed by Controller)**

## Overview

The recorder is the most critical service in the Silvasonic stack. It captures audio data from USB microphones and writes it to local NVMe storage. Multiple recorder instances may run concurrently, each managed by the Controller.

## Immutability Rules

The recorder is an **immutable Tier 2** service. This means:

- **No database access.** The recorder has no connection to TimescaleDB or any other database. This is strictly forbidden.
- **Profile Injection.** All configuration is provided via environment variables set by the Controller at container creation time.
- **No self-modification.** The recorder does not change its own state or configuration at runtime.
- **Stateless container.** The only persistent artifact is the audio data written to the bind-mounted workspace volume.

## Health Endpoint

The recorder exposes a health endpoint at `GET /healthy` on port `9500` (internal). This is used by the Compose healthcheck and the Controller to monitor recorder status.

## Lifecycle

- **Not auto-started.** The recorder uses the `managed` Compose profile and does not start with `just start`.
- **Started by Controller.** The Controller spawns recorder instances as needed, injecting the appropriate profile (device, sample rate, channel config).
- **Graceful shutdown.** The recorder handles `SIGTERM` and `SIGINT` for clean shutdown.

## Current Status (v0.1.0)

The recorder is a **scaffold** with:
- Health server on `:9500/healthy`
- Recording health monitor (placeholder, hardcoded healthy)
- Signal handling for graceful shutdown
- No actual audio capture logic yet (planned for v0.2.5)
