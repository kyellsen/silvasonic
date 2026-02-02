# 13. Hybrid YAML/DB Profile Management

Date: 2026-02-02

## Status

Accepted

## Context

Silvasonic requires precise configuration for audio hardware ("Microphone Profiles") to ensure scientific-grade recordings.
- **Requirement 1 (Stability):** We ship "known good" profiles for supported hardware (Ultramic, generic USB) that must work out-of-the-box.
- **Requirement 2 (Flexibility):** Users may bring custom hardware or experimental mics that need custom profiles without rebuilding our container images.
- **Requirement 3 (Dynamic):** A web frontend (future) needs to be able to edit or create profiles at runtime.

Previously, profiles were loaded directly from YAML files at startup. This made Requirement 3 impossible without complex file editing capabilities inside the container.

## Decision

We will implement a **Hybrid YAML-to-Database Bootstrapping** model.

1.  **Database is the Single Source of Truth:**
    - The code (Controller, API) *only* reads profiles from the `microphone_profiles` database table.
    - We treat the database as the authoritative state for the running application.

2.  **YAML Files as "Seed" Data:**
    - We retain YAML files in the repository (`services/recorder/config/profiles`).
    - On every Controller startup, a `ProfileBootstrapper`:
        - Reads the YAML files.
        - **Upserts** (Insert or Update) them into the database.
        - Marks them as `is_system=True`.

3.  **Strict Device Linking:**
    - The `devices` table will have a Foreign Key to `microphone_profiles`.
    - We move away from storing profile config loosely in a JSON column on the device.

## Consequences

### Positive
- **API Ready:** We can trivially add endpoints to purely CRUD the database table for user-defined profiles.
- **GitOps Compatible:** Changes to standard profiles in the git repo automatically propagate to deployments on update/restart.
- **Data Integrity:** Foreign keys prevent deleting a profile that is in use by a device.

### Negative
- **State Complexity:** Code must decide precedence. Currently, YAML "wins" on startup (overwriting DB changes to system profiles). This is intentional to enforce "Repo is Truth" for system profiles.
- **Startup Time:** Small penalty to parse YAMLs and sync to Postgres on every boot (negligible for expected profile counts < 100).

## References
- [Microphone Profiles Documentation](../architecture/microphone_profiles.md)
