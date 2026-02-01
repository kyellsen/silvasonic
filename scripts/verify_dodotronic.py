#!/usr/bin/env python3
"""Manual hardware verification script for Silvasonic Recorder.

Target: Dodotronic Ultramic (using 'ultramic_384_evo' profile).
Runs the recorder INSIDE a Podman container, orchestrated from the Host.

Usage:
    uv run scripts/verify_dodotronic.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Configuration
IMAGE_NAME = "silvasonic-recorder"
PROFILE_NAME = "ultramic_384_evo"  # Use the real profile!
OUTPUT_REL_PATH = ".tmp/tests/recorder"


def check_dependencies() -> None:
    """Ensure podman and arecord are available."""
    missing = []
    if not shutil.which("podman"):
        missing.append("podman")
    if not shutil.which("arecord"):
        missing.append("arecord")

    if missing:
        print(f"Error: Missing host dependencies: {', '.join(missing)}")
        sys.exit(1)


def get_alsa_cards() -> list[dict[str, Any]]:
    """List available ALSA input devices on HOST."""
    res = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    cards = []
    for line in res.stdout.splitlines():
        # format: card 1: r0 [UltraMic384K_EVO 16bit r0], device 0: USB Audio [USB Audio]
        # Regex to capture: id (Group 2) and description (Group 3)
        m = re.search(r"card (\d+): (.*?) \[(.*?)\], device (\d+):", line)
        if m:
            cards.append(
                {
                    "index": int(m.group(1)),
                    "id": m.group(2),
                    "description": m.group(3),
                    "device": int(m.group(4)),
                    "name": f"{m.group(2)} ({m.group(3)})",  # Full display name
                }
            )
    return cards


def main() -> None:
    """Execute the hardware verification process."""
    print("=== Silvasonic Hardware Verification (Containerized) ===", flush=True)
    check_dependencies()

    # 1. Select Device
    cards = get_alsa_cards()
    selected_card = None

    if not cards:
        print("Error: No ALSA devices found on host.")
        sys.exit(1)

    # Auto-detection priority
    print("Scanning for Dodotronic/Ultramic devices...")
    priorities = ["dodotronic", "ultramic", "usb"]

    for priority in priorities:
        for c in cards:
            if priority in c["name"].lower():
                selected_card = c["index"]
                print(f"Auto-detected Device: {c['name']} (Index {c['index']})")
                break
        if selected_card is not None:
            break

    if selected_card is None:
        print("Error: No suitable Dodotronic or USB microphone found automatically.")
        print("Available devices:")
        for c in cards:
            print(f"  [{c['index']}] {c['name']}")
        sys.exit(1)

    # print(f"Selected ALSA Card Index: {selected_card}")

    # 2. Setup Directories
    repo_root = Path.cwd()
    output_dir = repo_root / OUTPUT_REL_PATH

    # Path to REAL profiles
    # We mount the directory containing the profiles so the manager can find them by name
    real_profile_dir = repo_root / "services/recorder/config/profiles"

    if not real_profile_dir.exists():
        print(f"Error: Profile directory not found at {real_profile_dir}")
        sys.exit(1)

    # Validating the specific profile exists
    if not (real_profile_dir / f"{PROFILE_NAME}.yml").exists():
        print(f"Error: Target profile '{PROFILE_NAME}.yml' not found in {real_profile_dir}")
        sys.exit(1)

    # Clean output
    if output_dir.exists():
        # Optional: Clean old tests or just append?
        # Let's keep it safe and just ensure dirs exist.
        pass

    # Create structure matching silvasonic/recorder/main.py expectations:
    # OUTPUT_DIR = /data/recorder / MIC_NAME / "recordings"
    # MIC_NAME defaults to "default"
    mic_name = "default"

    # We mount output_dir -> /data/recorder
    # So we need to create {output_dir}/{mic_name}/recordings/{raw|processed}
    rec_root = output_dir / mic_name / "recordings"
    (rec_root / "raw").mkdir(parents=True, exist_ok=True)
    (rec_root / "processed").mkdir(parents=True, exist_ok=True)

    # 3. Build Container
    print("\nBuilding recorder image...")
    subprocess.check_call(
        ["podman", "build", "-t", IMAGE_NAME, "-f", "services/recorder/Dockerfile", "."],
        cwd=repo_root,
    )

    # 3.5 Debug: Check devices inside container
    print("\n[DEBUG] Probing container audio devices (arecord -l)...")
    subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--device",
            "/dev/snd:/dev/snd",
            # Add keep-groups to match the main run, in case permissions depend on it
            "--group-add",
            "keep-groups",
            IMAGE_NAME,
            "arecord",
            "-l",
        ]
    )

    # 4. Run Container
    print(f"\nStarting Recorder Container with profile '{PROFILE_NAME}'...")

    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "--device",
        "/dev/snd:/dev/snd",
        "--group-add",
        "keep-groups",
        "-v",
        f"{output_dir}:/data/recorder:z",
        # Mount the REAL profile directory
        "-v",
        f"{real_profile_dir}:/etc/silvasonic/profiles:ro,z",
        "-e",
        f"MIC_PROFILE={PROFILE_NAME}",
        "-e",
        f"ALSA_DEVICE_INDEX={selected_card}",
        "-e",
        "PYTHONUNBUFFERED=1",
        IMAGE_NAME,
    ]

    print(f"Command: {' '.join(cmd)}")
    print(f"Output Directory (Host): {output_dir}")
    print("Press Ctrl+C to stop.")

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
