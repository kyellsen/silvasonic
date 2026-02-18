# ADR-0009: Zero-Trust Data Sharing Policy

> **Status:** Accepted • **Date:** 2026-01-31

> **NOTE:** References to `processor`, `uploader`, or `janitor` refer to future services (planned for v0.3.0+). Currently, only `recorder` and `controller` exist.

## 1. Context & Problem
In an audio pipeline, "downstream" services (like Analyzers or Uploaders) need to access data produced by "upstream" services (Recorder). If downstream services are granted write access, a bug or misconfiguration in an experimental analyzer could involve deleting or corrupting the original master recordings. We need to protect the "Source of Truth".

## 2. Decision
**We chose:** The Consumer Principle (Read-Only Mounts).
Any service that consumes data it did not create MUST modify its container definition to mount that data as `ro` (Read-Only). For example, the Processor mounts `/recorder/recordings` as `:ro`. Deletion authority is centralized in a specific logical role (The Janitor) and denied to all others.

**Reasoning:**
This acts as a physical safety interlock. Even if the BirdNET analyzer code goes haywire and tries to `rm -rf *`, the kernel will reject the operation. This protects the raw scientific data from software faults in the post-processing pipeline.

### 2.1. Controller Exception
The **Controller** is the only service permitted to mount another service's workspace with **write access** (RW). As the orchestrator, the Controller must prepare Tier 2 workspaces (e.g., directory structure, profile injection) before spawning containers. This is an explicit, documented exception to the Consumer Principle.

## 3. Options Considered
*   **Full Shared Access (RW everywhere):**
    *   *Rejected because:* High risk of accidental data loss.
*   **Copying Data:**
    *   *Rejected because:* Inefficient for large audio files (storage duplication).

## 4. Consequences
*   **Positive:**
    *   Guaranteed integrity of Source Data.
    *   "Sandbox" safety for experimental analyzers.
*   **Negative:**
    *   Services generally cannot "mark" files by renaming them (must use Database or Sidecar files for metadata state).
    *   Requires explicit `ro` flags in `compose.yml`.
