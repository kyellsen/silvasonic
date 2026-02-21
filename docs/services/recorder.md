# Recorder Service

> The most critical service — captures audio from USB microphones and writes WAV files to local NVMe storage.

## Redis Heartbeat

The Recorder publishes periodic heartbeats to Redis via the `SilvaService` base class (see [ADR-0019](../adr/0019-unified-service-infrastructure.md)). This is a fire-and-forget operation in an isolated `asyncio.Task` — the recording loop has **zero coupling** to Redis. If Redis is unavailable, heartbeats are silently skipped.

## Full Documentation

Die vollständige Dokumentation befindet sich im Service-Verzeichnis:

- **[Recorder README](../../services/recorder/README.md)** — Primary specification
