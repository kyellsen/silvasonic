# Weather

> **Status:** Planned (v1.2.0) · **Tier:** 2 · **Instances:** Single

Environmental data service that downloads weather observations from external APIs and local sensors, stores them in the database, and enables correlation of acoustic activity with environmental conditions.

---

## 1. The Problem / The Gap

*   **No Environmental Context:** Without weather data, acoustic recordings exist in isolation. It is impossible to correlate species activity with temperature, humidity, wind speed, or barometric pressure.
*   **Manual Data Integration:** Researchers must manually download weather data from third-party sources and align timestamps — a tedious and error-prone process.

## 2. User Benefit

*   **Automated Enrichment:** Weather data is automatically fetched and stored alongside recordings, enabling queries like "Show all BirdNET detections during rain events."
*   **Behavioral Insights:** Correlate dawn chorus timing with sunrise, bat activity with moonphase, or silence periods with approaching storms.

## 3. Core Responsibilities

### Inputs

*   **External APIs:** Periodic polling of weather data providers (e.g., OpenMeteo, DWD Open Data) for the station's geographic coordinates.
*   **Local Sensors (Future):** Reads from BME680 (temperature, humidity, pressure, VOC) or SPS30 (particulate matter) via I²C/SPI if hardware is connected (see [Future Ideas](../development/idea.md)).

### Processing

*   **Data Normalization:** Converts provider-specific formats to the canonical `weather` table schema.
*   **Deduplication:** Ensures no duplicate observations for the same timestamp and source.
*   **TimescaleDB Partitioning:** Inserts into the `weather` hypertable with time-based partitioning.

### Outputs

*   **Database Rows:** INSERTs into `weather` table (TimescaleDB hypertable).
*   **Redis Heartbeats:** Via `SilvaService` base class (ADR-0019).

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                               |
| ---------------- | ---------------------------------------------------------- |
| **Immutable**    | Yes — config at startup, restart to reconfigure (ADR-0019) |
| **DB Access**    | Yes — writes `weather` table, reads `system_config`        |
| **Concurrency**  | Async event loop, periodic fetch (e.g., every 5–15 min)    |
| **State**        | Stateless — last-fetched timestamp derived from DB         |
| **Privileges**   | Rootless (ADR-0007)                                        |
| **Resources**    | Low — infrequent HTTP requests, minimal CPU                |
| **QoS Priority** | `oom_score_adj=500` — expendable analysis service          |

## 5. Configuration & Environment

| Variable / Mount        | Description              | Default / Example                                                                   |
| ----------------------- | ------------------------ | ----------------------------------------------------------------------------------- |
| Health port             | Internal health endpoint | `9500`                                                                              |
| `WEATHER_PROVIDER`      | API provider             | `openmeteo`                                                                         |
| `WEATHER_LATITUDE`      | Station latitude         | `51.9607`                                                                           |
| `WEATHER_LONGITUDE`     | Station longitude        | `7.6261`                                                                            |
| `WEATHER_POLL_INTERVAL` | Seconds between fetches  | `900` (15 min)                                                                      |
| `WEATHER_VARIABLES`     | OpenMeteo Hourly Vars    | `temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,precipitation` |

## 6. Technology Stack

*   **HTTP Client:** `httpx` (async)
*   **Data Provider:** OpenMeteo Free API (no API key required)
*   **Database:** `sqlalchemy` (2.0+ async), `asyncpg`
*   **Future Sensors:** `smbus2` or `adafruit-circuitpython-bme680` for I²C sensors

## 7. Open Questions & Future Ideas

*   Multiple weather providers for fallback / cross-validation.
*   Local sensor support: BME680 for hyperlocal microclimate data (see [Future Ideas](../development/idea.md)).
*   Lightning detection: AS3935 sensor for storm proximity correlation.
*   Astronomy data: Moon phase and sun position from Suncalc for nocturnal activity analysis.

## 8. Out of Scope

*   **Does NOT** analyze audio (BirdNET / BatDetect's job).
*   **Does NOT** record audio (Recorder's job).
*   **Does NOT** provide a UI (Web-Interface's job).
*   **Does NOT** perform weather forecasting — only stores observations.

## 9. References

*   [Database Schema (DDL)](../../services/database/init/01-init-schema.sql) — authoritative definition of the `weather` table hypertable schema.
*   [ADR-0019](../adr/0019-unified-service-infrastructure.md) — Immutable Container, SilvaService
*   [ADR-0020](../adr/0020-resource-limits-qos.md) — QoS priority for analysis services
*   [Future Features & Ideas](../development/idea.md) — Sensor recommendations
*   [Glossary: Weather Observation](../glossary.md)
*   [ROADMAP.md](../../ROADMAP.md) — milestone (v1.2.0)
