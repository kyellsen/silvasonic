# Microphone Profiles & Device Enrollment

> **STATUS:** IMPLEMENTED (v0.2.0)
> **SCOPE:** Controller, Database, Hardware Detection

Silvasonic employs a **Strict Hardware Enrollment** strategy. Audio devices are not simply "used if found"; they must be positively identified and matched to a validated **Microphone Profile**.

## The Profile Concept

A `MicrophoneProfile` is a configuration blueprint that tells the system:
1.  **Identity:** How to recognize the hardware (Regex Pattern on ALSA description).
2.  **Capabilities:** Sample rates, channel counts, and formats.
3.  **Behavior:** How the recorder service should capture audio (e.g., chunk size, encoder settings).

### Database as Source of Truth

As of v0.2.0, profiles are stored in the `microphone_profiles` database table.
- **Slug (PK):** Unique identifier (e.g., `ultramic_384_evo`).
- **Config (JSON):** The full configuration object passed to the Recorder service.

## "YAML-First" Bootstrapping

To maintain "Infrastructure as Code" principles while allowing dynamic runtime capabilities, Silvasonic uses a hyrbid **YAML + DB** approach.

1.  **Repo as Authority:** Default profiles live in `services/recorder/config/profiles/*.yml`.
2.  **Bootstrapping:** On every Controller startup, the `ProfileBootstrapper` scans these files and **upserts** them into the database.
3.  **Runtime:** The Controller reads *only* from the database.

This ensures that:
- Code updates to standard profiles are automatically applied.
- User-defined profiles (added via future API) are preserved in the DB.

## Device Enrollment Workflow

When a new USB Audio Device is plugged in:

1.  **Detection:** Hardware Scanner sees new device serial/ID.
2.  **Profile Matching:**
    - Controller checks the `microphone_profiles` table for a matching `match_pattern`.
    - **Match Found:** Device is auto-enrolled (`enrollment_status='enrolled'`) and assigned the `profile_slug`.
    - **No Match:** Device is created as `pending`. Administrator must manually assign a profile or approve it.
3.  **Orchestration:**
    - If `enrolled`, the Controller spawns a dedicated Recorder container using the assigned profile's configuration.

## Managing Profiles

### Adding a Custom Profile
Currently, the "Best Practice" path is:
1.  Add a new YAML file to `/etc/silvasonic/profiles` (mounted volume).
2.  Restart the Controller to bootstrap it.

*(Future API endpoints will allow direct DB insertion without restarts).*

### Default Profiles location
In the container: `/etc/silvasonic/profiles/`
In the repo: `services/recorder/config/profiles/`
