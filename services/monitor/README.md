# Container: Monitor

> **Service Name:** `monitor`
> **Container Name:** `silvasonic-monitor`
> **Package Name:** `silvasonic-monitor`

## 1. The Problem / The Gap
*   **Watchdog:** If the `controller` crashes, who restarts it? Need an independent "Dead Man's Switch" or external observer.
*   **System Stats:** Need to collect CPU/RAM/Disk stats independent of the main app logic.

## 2. User Benefit
*   **Reliability:** Ensures the system recovers from catastrophic failures.
*   **Visibility:** Provides "Life Pulse" even if the Dashboard is down (e.g. via LEDs or hardware signals).

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Health Checks**: HTTP GET requests to other services (e.g. `/health`).
    *   **System Metrics**: `psutil` readings (CPU, Temp, Disk).
*   **Processing**:
    *   **Threshold Checking**: Is CPU > 95% for 5 mins? Is Disk < 1GB?
    *   **Liveness Verification**: Logic to determine if a hard reboot is required.
*   **Outputs**:
    *   **Alerts**: Logs/Redis Events.
    *   **Hardware Control**: (Optional) Toggling LEDs or Hardware Watchdog timer.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Low**. Simple loop.
*   **State**: **Stateless**.
*   **Privileges**: **Rootless** (mostly), might need access to `/proc` or host hardware.
*   **Resources**: Minimal.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `CHECK_INTERVAL`: Seconds.
*   **Volumes**:
    *   `/proc` (Read Only) for host metrics (if allowed in rootless).
*   **Dependencies**:
    *   `psutil`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** manage containers (Controller job).
*   **Does NOT** store data (Database job).
*   **Does NOT** process audio (Recorder job).
*   **Does NOT** provide a user interface (Web Interface job).
*   **Does NOT** interact with external cloud services directly.

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   None currently installed (Scaffolding).
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Independent monitoring layer.
*   **Alternatives**: Telegraf/Prometheus Node Exporter (Standard but might be overkill for an appliance; custom script allows specific application logic logic).

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** **SCAFFOLDING ONLY**: The `pyproject.toml` is empty. Core libs like `psutil` are NOT yet installed.
