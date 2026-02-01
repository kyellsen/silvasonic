# Glossary

> **STATUS:** NORMATIVE
> **SCOPE:** System-wide
> **AUTHORITY:** This document defines the standard vocabulary for the Silvasonic project. Agents and Developers must adhere to these definitions to ensure consistency.

## Architecture

### Two-Worlds Principle
The strict architectural separation between **Repository** (Immutable Code) and **Workspace** (Mutable State).

### Controller
The central orchestration service responsible for detecting hardware devices and managing the lifecycle of dynamic containers (`recorder`, `birdnet`) based on configuration.

### Janitor
The cleanup process within the `processor` service responsible for enforcing the Data Retention Policy by deleting old files based on disk usage thresholds.

### Traffic Light Pattern
The standard schema for service status reporting via Redis, indicating health (Green/Yellow) or offline status (Red) with an accompanying payload.

## Data & Artifacts

### Raw Artifact (`file_raw`)
The bit-perfect copy of the audio stream captured by the hardware, preserved strictly for archival purposes and never modified.

### Processed Artifact (`file_processed`)
The standardized version of an audio recording with a normalized sample rate, used as the input for analysis, visualization, and consumption.

### Device Binding
The mechanism of persistently identifying a physical microphone device to ensure consistent mapping, independent of physical connection ports or order.

## Services

### Recorder
Service responsible for buffering audio in RAM and writing dual-stream artifacts (Raw & Processed) to storage.

### Monitor
System watchdog that subscribes to status updates and sends notifications upon service failure or critical system states.

### Gateway
Reverse proxy handling internal routing, HTTPS termination, and authentication.

### Processor
Local data handler responsible for indexing files, generating visualizations, and running maintenance tasks.

### Uploader
Service responsible for compressing artifacts and synchronizing them to remote storage.
