# Icecast

> **Status:** Planned (v0.9.0) · **Tier:** 1 · **Instances:** Single

Lightweight streaming server that receives live Opus audio from Recorder instances and serves it to the Web-Interface and external clients via HTTP. Enables real-time soundscape monitoring without accessing stored recordings.

---

## 1. The Problem / The Gap

*   **No Live Monitoring:** Without a streaming server, users must download recorded WAV files to listen to the soundscape — no real-time option exists.
*   **Multi-Microphone Routing:** Each Recorder pushes a separate audio stream. Something must aggregate these streams and expose them as selectable endpoints (mount points) for the Web-Interface.

## 2. User Benefit

*   **Live Listen:** Monitor the soundscape in real-time from the Web-Interface — hear what each microphone captures right now.
*   **External Access:** Share live audio streams via HTTP URLs (e.g., for citizen science or educational purposes).

## 3. Core Responsibilities

### Inputs

*   Opus audio streams from Recorder instances via HTTP source connections (one per microphone).

### Processing

*   Stream relay — no transcoding, no buffering beyond minimal latency.
*   Mount point management — one mount point per Recorder instance (e.g., `/mic-ultramic.opus`).

### Outputs

*   HTTP audio streams accessible via mount point URLs.
*   Listener metadata (client count, bitrate) available via Icecast admin API.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                        |
| ---------------- | ------------------------------------------------------------------- |
| **Immutable**    | No (managed by Compose/Quadlet, standard Icecast config)            |
| **DB Access**    | No — Icecast is independent of PostgreSQL                           |
| **Concurrency**  | Multi-threaded (Icecast default, one thread per source + listeners) |
| **State**        | Stateless — no persistent data, ephemeral stream relay              |
| **Privileges**   | Rootless (ADR-0007)                                                 |
| **Resources**    | Low — minimal CPU (relay only, no transcoding)                      |
| **QoS Priority** | `oom_score_adj=0` (default) — Tier 1 infrastructure                 |

> [!NOTE]
> The live stream is **best-effort**. If Icecast is unavailable or a Recorder cannot connect, recording continues unaffected — Data Capture Integrity is never compromised (ADR-0011).

## 5. Configuration & Environment

| Variable / Mount          | Description                | Default / Example |
| ------------------------- | -------------------------- | ----------------- |
| `SILVASONIC_ICECAST_PORT` | Host-exposed listener port | `8080`            |
| Icecast config XML        | Server configuration       | Mounted at build  |

### Example `icecast.xml` Structure (MVP)

```xml
<icecast>
    <location>Earth</location>
    <admin>admin@silvasonic.local</admin>
    <limits>
        <clients>100</clients>
        <sources>10</sources>
    </limits>
    <authentication>
        <!-- Read-only access for listeners defaults to public -->
        <source-password>silvasonic-source-secret</source-password>
        <admin-password>silvasonic-admin-secret</admin-password>
    </authentication>
    <listen-socket>
        <port>8080</port>
    </listen-socket>
    <mount type="normal">
        <!-- Recorder instances push here: /mic-ultramic.opus -->
        <mount-name>/mic-*.opus</mount-name>
        <public>1</public>
    </mount>
</icecast>
```

## 6. Technology Stack

*   **Image:** `linuxserver/icecast` (actively maintained, rootless compatible, PUID/PGID support).
*   **Codec:** Opus (received from Recorder, relayed as-is).

## 7. Open Questions & Future Ideas

*   MediaMTX with WebRTC as alternative for lower latency (sub-second vs. ~3s with Icecast).
*   Authentication for external listeners (API key or Tailscale ACL).
*   Metadata injection: Icecast supports in-stream metadata (species names from real-time analysis).

## 8. Out of Scope

*   **Does NOT** record or store audio (Recorder writes to NVMe).
*   **Does NOT** transcode audio (Recorder encodes Opus before sending).
*   **Does NOT** perform analysis (BirdNET / BatDetect's job).

## 9. References

*   [ADR-0011](../adr/0011-audio-recording-strategy.md) — Triple Stream Architecture (§5)
*   [Glossary: Icecast, Live Stream, Mount Point, Opus, Triple Stream Architecture](../glossary.md)
*   [ROADMAP.md](../../ROADMAP.md) — milestone (v0.9.0)
