# Microphone Profiles

> **STATUS:** TODO
> **SCOPE:** Audio Hardware Configuration

> [!NOTE]
> This document is a placeholder. The specification for microphone profiles — including schema definition, YAML bootstrapping format, and per-device configuration — will be documented here.

## Overview

The `microphone_profiles` table stores hardware-specific configuration for each supported microphone type. Profiles are referenced by the `devices` table and injected into Recorder containers at launch time (Profile Injection).

For the database schema, see:
- SQL: `services/database/init/01-init-schema.sql`
- SQLAlchemy Model: `packages/core/src/silvasonic/core/database/models/profiles.py`

## TODO

- [ ] Define the canonical YAML format for system-bootstrapped profiles
- [ ] Document all fields (`slug`, `name`, `description`, `match_pattern`, `config`)
- [ ] Provide example profiles for tested hardware (Dodotronic Ultramic 384 EVO, RØDE NT-USB)
- [ ] Document how the Controller matches USB devices to profiles via `match_pattern`
