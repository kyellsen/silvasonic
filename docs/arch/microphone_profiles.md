# Microphone Profiles

> **Status:** Normative (Mandatory) · **Scope:** Audio Hardware Configuration

## Overview

The `microphone_profiles` table stores hardware-specific configuration for each supported microphone type. Profiles are referenced by the `devices` table and injected into Recorder containers at launch time (Profile Injection).

For the database schema, see:
- SQLAlchemy Model: [`profiles.py`](../../packages/core/src/silvasonic/core/database/models/profiles.py)
- Device FK: [`system.py`](../../packages/core/src/silvasonic/core/database/models/system.py) — `devices.profile_slug → microphone_profiles.slug`

---

## YAML Profile Format

System profiles are maintained as YAML files in `services/controller/config/profiles/` and seeded into the database by the Controller's `ProfileBootstrapper` on every startup (see [ADR-0016](../adr/0016-hybrid-yaml-db-profiles.md)).

```yaml
---
schema_version: "1.0"
slug: ultramic_384_evo               # Unique identifier (primary key)
name: Dodotronic Ultramic 384 EVO    # Human-readable name
description: High-performance ultrasonic microphone for bioacoustics.
manufacturer: Dodotronic
model: Ultramic 384 EVO

audio:
  sample_rate: 384000                # Hardware native sample rate (Hz)
  channels: 1                        # Number of audio channels
  format: S16LE                      # Sample format (S16LE, S24LE, S32LE)
  match:                             # ← MatchCriteria for auto-detection
    usb_vendor_id: "2578"            # USB Vendor ID (stable, never changes)
    usb_product_id: "0001"           # USB Product ID
    alsa_name_contains: "ultramic"   # Case-insensitive ALSA card name substring

processing:
  gain_db: 12.0                      # Software gain in dB
  chunk_size: 8192                   # Buffer chunk size in frames
  highpass_filter_hz: 1000.0         # High-pass filter cutoff (Hz)

stream:
  raw_enabled: true                  # Archive full native sample rate
  processed_enabled: true            # Downsample to 48kHz for analysis
  live_stream_enabled: false         # Icecast Opus stream (v0.9.0) — set true when available
  segment_duration_s: 15             # Profile-specific override; system default is 10s
```

---

## Match Criteria

The `match` block inside `audio` defines how the Controller matches a physically connected USB device to this profile. This replaces the legacy `match_pattern` text field.

### Matching Fields

| Field                | Source                    | Stability                   | Purpose                                   |
| -------------------- | ------------------------- | --------------------------- | ----------------------------------------- |
| `usb_vendor_id`      | `sysfs` → `idVendor`   | ✅ Registered, never changes | Primary identification                    |
| `usb_product_id`     | `sysfs` → `idProduct`  | ✅ Registered, never changes | Together with vendor = unique device type |
| `alsa_name_contains` | `/proc/asound/cards`      | ⚠️ May vary between kernels  | Fallback / secondary confirmation         |

### Matching Algorithm

The Controller evaluates all profiles against a newly detected USB device and assigns a **match score**:

| Score   | Condition                                            | Action                                                              |
| ------- | ---------------------------------------------------- | ------------------------------------------------------------------- |
| **100** | `usb_vendor_id` AND `usb_product_id` both match      | Auto-Enrollment (if `auto_enrollment` is `true` in `system_config`) |
| **50**  | Only `alsa_name_contains` matches (case-insensitive) | Suggestion — user confirms in Web-Interface                         |
| **0**   | No match                                             | Device stays `pending` — user selects profile manually              |

If multiple profiles match with the same score, the device remains `pending` (ambiguous match — user decides).

### Finding USB Vendor/Product IDs

To create a profile for new hardware, connect the microphone and run:

```bash
# On the host (or inside Controller container)
lsusb
# Example output: Bus 001 Device 005: ID 2578:0001 Dodotronic Ultramic 384 EVO

# Or via sysfs (direct read, no external dependencies):
python3 -c "
from pathlib import Path
import os
for card in sorted(Path('/sys/class/sound').glob('card*')):
    real = card.resolve()
    cur = real
    while cur != cur.parent:
        sub = cur / 'subsystem'
        if sub.is_symlink() and Path(os.readlink(sub)).name == 'usb':
            uevent = (cur / 'uevent').read_text()
            if 'DEVTYPE=usb_device' in uevent:
                vid = (cur / 'idVendor').read_text().strip()
                pid = (cur / 'idProduct').read_text().strip()
                prod = (cur / 'product').read_text().strip() if (cur / 'product').exists() else '?'
                print(f'{vid}:{pid} — {prod}')
                break
        cur = cur.parent
"
```

---

## Profile Lifecycle

| Phase                       | Actor                              | How                                                                             |
| --------------------------- | ---------------------------------- | ------------------------------------------------------------------------------- |
| **System Profile creation** | Developer                          | Adds YAML file to `services/controller/config/profiles/`                        |
| **Seed into DB**            | Controller (ProfileBootstrapper)   | Inserts on startup (`is_system=true`). Skips if slug already exists — user profiles are never overwritten |
| **User Profile creation**   | User (Web-Interface)               | CRUD via Web-Interface → DB (`is_system=false`). Never overwritten by seed      |
| **Profile assignment**      | Controller (auto) or User (manual) | Device enrollment via `devices.profile_slug` FK                                 |
| **Profile injection**       | Controller                         | Env vars `SILVASONIC_RECORDER_DEVICE`, `SILVASONIC_RECORDER_PROFILE_SLUG`, `SILVASONIC_RECORDER_CONFIG_JSON` at `containers.run()`  |

---

## Tested Hardware

| Microphone                  | Profile Slug       | USB VID:PID | Native Sample Rate | Status           |
| --------------------------- | ------------------ | ----------- | ------------------ | ---------------- |
| Dodotronic Ultramic 384 EVO | `ultramic_384_evo` | `2578:0001` | 384 kHz            | ✅ Profile exists |

> **Note:** Additional profiles (e.g., RØDE NT-USB, generic USB) will be added as hardware is tested.

---

## Pydantic Schema

The `MatchCriteria` model is defined in [`devices.py`](../../packages/core/src/silvasonic/core/schemas/devices.py):

```python
class MatchCriteria(BaseModel):
    """How to match a USB device to this profile."""
    usb_vendor_id: str | None = None
    usb_product_id: str | None = None
    alsa_name_contains: str | None = None
```

This is nested inside `AudioConfig.match` and stored as part of the profile's `config` JSONB column.

---

## References

- [ADR-0016: Hybrid YAML/DB Profile Management](../adr/0016-hybrid-yaml-db-profiles.md) — Seed vs. runtime, bootstrapper
- [ADR-0011: Audio Recording Strategy](../adr/0011-audio-recording-strategy.md) — Dual Stream Architecture
- [Controller README §Profile Matching](../../services/controller/README.md) — Matching algorithm, auto-enrollment
- [Glossary — Microphone Profile](../glossary.md) — Canonical definition
