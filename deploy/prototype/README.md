# Prototype Station

> **Status:** AS-IS — the playbook and the measurement script exist and pass their checks; neither has run on a device yet.

Installs one git ref of this repository on a Raspberry Pi and measures what it costs the device. It serves the hardware measurements of [v0.8.1](../../docs/development/milestones/milestone_0_8_1.md) and [v0.9.0](../../docs/development/milestones/milestone_0_9_0.md). It is not the installation procedure of a released station; that is [v0.14.0](../../docs/development/milestones/milestone_0_14_0.md).

## Before You Start

*   **Card:** flash *Raspberry Pi OS Lite (64-bit)*, the Debian 13 release, with Raspberry Pi Imager. In its settings give the device a hostname, a user, your SSH public key and the network.
*   **Control machine:** this checkout, Ansible, and SSH access to the station with that key.
*   **Inventory:** copy `inventory.example.yml` to `inventory.yml` and enter the station's address and user.

## Install a Ref

```bash
ansible-playbook -i inventory.yml station.yml -e silvasonic_ref=884a607
```

The ref is pushed from this checkout straight to the station, so it need not exist on GitHub. The playbook then follows the README's quick start: `just setup`, `just build` on the device, `just start`. Building takes the longest; its output goes to `~/silvasonic-build.log` on the station.

`just setup` prints the Gateway password once. The station keeps it in `~/silvasonic-setup.log`, readable by the station user only.

To measure another ref, run the playbook again with that ref. It stops the running stack, checks the ref out, and builds and starts again. Recordings in `~/silvasonic-data` stay.

## Measure

On the station, from the checkout so that the script finds `.env`:

```bash
cd ~/silvasonic && ~/measure_station.py --duration 1800 --label recording-only
```

The script prints a summary and writes every sample to a JSON file in the current directory. `--help` lists its options, and its module docstring says what each number means.

Measure each ref twice: recording only, and recording with BirdNET analysing.

## What It Leaves Out

*   Quadlets, updates and rollback: the stack runs under `podman-compose`, as in development.
*   Anything that needs `sudo` after the first run. The packages, the `audio` group and lingering are set once; the group change reboots the station.
