# silvasonic-weather

> **Status:** Planned (v1.2.0) · **Tier:** 2 (Application, Managed by Controller) · **Instances:** Single

**TO-BE:** The Weather service polls local or remote environmental sensors to correlate acoustic activity with weather data (Temp, Humidity, Rain, Wind).

---

## The Problem / The Gap

*   **Acoustic Correlation:** Wildlife activity is heavily influenced by weather. Analyzing a drop in bird calls requires knowing if it was raining at the time.

## User Benefit

*   **Rich Datasets:** Automatically logs environmental context alongside audio for comprehensive scientific studies.

---

## Core Responsibilities

*   **Sensor Polling:** Connects to physical sensors (via I2C/SPI on the Raspberry Pi) or polls localized weather APIs (Open-Meteo).
*   **Database Insertion:** Writes time-series data into the `weather` hypertable in TimescaleDB.

---

## Operational Constraints & Rules

| Aspect           | Value / Rule                                                                                    |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| **Immutable**    | Yes.                                                                                            |
| **DB Access**    | **Yes** — Inserts into `weather`.                                                               |
| **Concurrency**  | Low — simple periodic polling tasks.                                                            |
| **State**        | Stateless.                                                                                      |
| **Privileges**   | Standard (rootless) unless querying I2C sensors directly, which may require `privileged: true`. |
| **QoS Priority** | `oom_score_adj=500` (Expendable).                                                               |
