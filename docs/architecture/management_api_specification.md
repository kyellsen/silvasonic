# Silvasonic Management API Specification

> **STATUS:** PROPOSED
> **SCOPE:** Frontend <-> Backend Interface

This document defines the REST API endpoints required to manage the device lifecycle and microphone profiles from the Silvasonic Web Interface.

## Core Concepts

### Responsibility Split
*   **`devices` Table:** Represents the **Inventory**. It tracks *what* hardware is plugged in, its physical properties (Serial, Model), and its administrative state (`enrollment_status`).
*   **`microphone_profiles` Table:** Represents the **Configuration Catalog**. It defines *how* a recorder should behave for a given class of device.
*   **Controller:** The orchestrator that reads these tables. It only starts a recorder if a Device is `online`, `enabled`, AND `enrolled` with a valid `profile_slug`.

## 1. Device Management (`/api/v1/devices`)

### List Inventory
`GET /devices`
*   **Filters:** `?enrollment_status=pending`, `?status=online`, `?enabled=true`
*   **Response:** List of devices with full details (including linked `profile_slug`).
*   **Use Case:** Dashboard showing "Active Recorders" vs "New Devices Detected (Pending)".

### Get Device Details
`GET /devices/{serial_number}`

### Update Device State (Enrollment)
`PATCH /devices/{serial_number}`
*   **Payload (Enroll):**
    ```json
    {
      "enrollment_status": "enrolled",
      "profile_slug": "ultramic_384_evo",
      "logical_name": "Garden_North_01"
    }
    ```
    *Effect:* Controller picks this up on next reconcile loop and starts the recorder.

*   **Payload (Ignore):**
    ```json
    {
      "enrollment_status": "ignored"
    }
    ```
    *Effect:* Controller suppresses logs for this device, never starts it.

*   **Payload (Reset/Unenroll):**
    ```json
    {
      "enrollment_status": "pending",
      "profile_slug": null
    }
    ```
    *Effect:* Controller stops the running recorder immediately.

*   **Payload (Emergency Stop):**
    ```json
    {
      "enabled": false
    }
    ```
    *Effect:* Immediate stop, regardless of enrollment status.

## 2. Profile Management (`/api/v1/profiles`)

### List Profiles
`GET /profiles`
*   **Response:** List of all available profiles.
*   **Use Case:** Populating the "Select Profile" dropdown in the Enrollment Modal.

### Create Custom Profile
`POST /profiles`
*   **Payload:**
    ```json
    {
      "slug": "custom-mic-v1",
      "name": "My Custom Microphone",
      "match_pattern": "USB Audio Device.*",
      "config": { ...full_recorder_config... }
    }
    ```
*   **Validation:** Must prevent overwriting `is_system=True` profiles via this endpoint (unless forced).

### Delete Profile
`DELETE /profiles/{slug}`
*   **Constraints:**
    - Cannot delete `is_system=True` profiles (they would come back on restart anyway).
    - Cannot delete if linked to any `Device` (Foreign Key constraint check).

## 3. Service Control (`/api/v1/containers`)

### Control Container
`POST /api/v1/containers/{container_id}/{action}`
*   **Actions:** `restart`, `stop`, `start`
*   **Use Case:** Debugging specific recorders that seem stuck or unresponsive.

## 4. System (`/api/v1/system`)

### Reload Configuration
`POST /api/v1/system/reload`
*   **Effect:** Sends `reload_config` broadcast via Redis. Controller will re-scan hardware and re-sync profiles.
*   **Use Case:** After editing a YAML profile manually on disk.

### System Storage (Future)
`GET /api/v1/system/storage`
*   **Response:** Disk usage of the main data volume.
*   **Requirement:** Needs `workspace` volume mount in Status Board container.
