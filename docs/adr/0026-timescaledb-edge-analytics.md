# ADR-0026: Database Engine Selection for Edge Analytics

> **Status:** Accepted • **Date:** 2026-04-02

## 1. Context & Problem

The Silvasonic project (`VISION.md`) requires a local, autonomous setup functioning over long periods (up to 10 years) on edge hardware (Raspberry Pi 5 + NVMe). The application architecture utilizes concurrent microservices (Controller, Processor, Uploader, Web-Interface, Inferences) accessing a central database. 

Projections show that over 10 years, using 3 microphones continuously processing 10-second segments, data accumulation will hit massive volumes (up to 300 - 400 million rows, specifically in the `detections` table). Crucially, the "Local-First" philosophy requires the local Web Interface to display long-term trend statistics (e.g., 10-year species occurrence vs. temperature) instantaneously, without relying on cloud infrastructure. 

The problem is determining which database engine can handle high concurrent writes (`FOR UPDATE SKIP LOCKED` per ADR-0018) while answering 10-year statistical queries without exhausting the limited RAM (4-8 GB) or creating severe I/O thrashing on the Raspberry Pi.

## 2. Decision

**We chose:** TimescaleDB (PostgreSQL 17 + Timescale Extension).

**Reasoning:**
While TimescaleDB introduces a slightly higher baseline memory footprint (~300-450 MB) and occasional CPU spikes from background workers, it perfectly mitigates the fatal risks associated with long-term data accumulation on restricted hardware:
*   **Continuous Aggregates:** TimescaleDB natively calculates and updates materialized views in the background (e.g., daily aggregates of detections). A 10-year statistical query by the Web UI reads a few thousand pre-calculated rows in milliseconds instead of causing a 300-million row full-table scan that would evict the entire page cache and crash the system.
*   **Data Retention & Compression:** Timescale natively compresses older chunks, saving critical NVMe storage space over the 10-year physical deployment, while providing easy policies to drop extreme high-resolution data once aggregated.
*   **Concurrency:** Inheriting PostgreSQL capabilities, we maintain safe atomic queuing operations (`FOR UPDATE SKIP LOCKED`) needed by the Tier-2 workers.

Attempting to recreate TimescaleDB's background aggregation and retention logic via custom Python scripts or `pg_cron` inside Vanilla PostgreSQL would violate the KISS principle severely. 

## 3. Options Considered

*   **Option A: Vanilla PostgreSQL 17**: Rejected. While it uses slightly less base RAM (~150-250MB) and possesses all necessary concurrency features, running 10-year statistical aggregates over hundreds of millions of rows on a Raspberry Pi 5 would lead to severe cache-thrashing, memory exhaustion, and CPU bottlenecks, endangering the primary directive ("Data Capture Integrity"). Implementing manual background aggregations to prevent this would be complex and fragile.
*   **Option B: SQLite (In-Memory / File-based)**: Rejected. The current architecture strictly relies on high concurrency and the Worker Pull pattern (`ADR-0018`). SQLite's file-based locking mechanism (`SQLITE_BUSY`) and lack of robust multi-process row-level locking makes it entirely incompatible with our multi-container (Tier 1 & Tier 2) microservice setup. An In-Memory database like Redis also fails because "Store & Forward" strictly requires metadata persistence against frequent power losses in remote environments. 

## 4. Consequences

*   **Positive:** 
    *   The local Web Interface (v0.9.0) will handle 10-year data queries instantly.
    *   No custom Python aggregation workers are required; we leverage robust, native C-extensions.
    *   The system aligns seamlessly with "Local Autonomy" and "Store & Forward".
*   **Negative:** 
    *   Marginally higher baseline memory footprint on the host device.
    *   Minor constraints on SQL schema design (e.g., Hypertables do not support incoming Foreign Keys, successfully mitigated via ADR-0025).
