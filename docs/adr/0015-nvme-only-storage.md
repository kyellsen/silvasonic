# ADR-0015: NVMe-Only Storage Policy

> **Status:** Accepted • **Date:** 2026-02-18

## 1. Context & Problem

Silvasonic is designed to run autonomously for years on unattended edge devices (Raspberry Pi 5). The storage medium directly impacts data integrity, write endurance, and throughput — all of which are critical for continuous audio recording.

SD Cards, while convenient for initial provisioning, are fundamentally unsuitable for production workloads:

*   **Low write endurance:** Consumer SD cards degrade rapidly under sustained write loads (audio buffers, database WAL, swap).
*   **Throughput limits:** SD card I/O is insufficient for concurrent dual-stream recording (Raw + Processed) and database operations.
*   **Silent corruption:** SD cards are prone to filesystem corruption after unexpected power loss — the single most common failure mode for field stations.

## 2. Decision

**We chose:** A strict "NVMe Only" storage policy for all production deployments.

**Reasoning:**

1.  **NVMe is mandatory.** All production Silvasonic stations MUST use an M.2 NVMe SSD (Gen 2 or Gen 3) connected via a PCIe HAT on the Raspberry Pi 5.
2.  **SD Cards are prohibited in production.** An SD card may be used **temporarily** during initial provisioning (bootloader update, OS flashing onto NVMe). Once provisioned, the SD card **MUST be physically removed**. The system boots and runs entirely from the NVMe SSD.
3.  **Unified storage namespace.** The OS, swap partition, database (TimescaleDB), and audio recording buffers all reside on the NVMe drive.
4.  **USB-attached storage (legacy).** External SSDs via USB 3.0 are tolerated for experimental Raspberry Pi 4 setups, but are **not officially supported** for production due to bus contention and lower reliability compared to PCIe NVMe.

## 3. Options Considered

*   **SD Card as primary storage:** Rejected. Fundamentally incompatible with the write endurance and throughput requirements of continuous bioacoustic recording. Silent corruption risk is unacceptable for a system designed to run autonomously for years.
*   **SD Card for OS + NVMe for data:** Rejected. Split-storage introduces complexity (mount management, boot reliability) and the SD card remains a single point of failure for the OS partition.
*   **NVMe only (chosen):** Single high-speed, high-endurance storage device for everything. Simple, reliable, and aligned with the "Resilience over Features" design principle.

## 4. Consequences

*   **Positive:**
    *   Maximum write endurance — NVMe SSDs are rated for thousands of TBW (Terabytes Written), orders of magnitude above SD cards.
    *   High throughput for concurrent dual-stream recording and database operations.
    *   No split-storage complexity — single filesystem, single backup target, single failure domain.
    *   Eliminates the most common field failure mode (SD card corruption after power loss).
*   **Negative:**
    *   Higher per-unit cost compared to SD-card-only setups.
    *   Requires a PCIe HAT (additional hardware component).
    *   Initial provisioning requires a temporary SD card or USB boot media to flash the NVMe.
