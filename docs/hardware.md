# Hardware Specifications

> **STATUS:** STANDARD
> **SCOPE:** Physical Layer & Provisioning

This document defines the certified hardware platforms and peripherals for the Silvasonic recording station.

## Compute & Storage Classifications

### Recommended Specification (Production Target)

The standard deployment target for optimal performance and reliability.

*   **SBC:** Raspberry Pi 5
*   **RAM:** 8 GB
*   **Storage:** 256 GB M.2 NVMe SSD (Gen 2/3) via PCIe HAT
*   **Cooling:** Active Cooler (Mandatory)
*   **Power:** Official 27W USB-C Power Supply

### Minimum Specification

Capable of running the core recording stack, though some analysis features may require tuning.

*   **SBC:** Raspberry Pi 5
*   **RAM:** 4 GB
    *   *Note:* Running concurrent heavy inference models (e.g., BirdNET + BatDetect) may be memory-constrained.
*   **Storage:** 128 GB M.2 NVMe SSD
*   **Constraint:** **NVMe is mandatory.** SD Cards are strictly prohibited for production data storage due to low write endurance and throughput limits. See [ADR-0015](adr/0015-nvme-only-storage.md).

### Experimental / Legacy

Hardware that is technically capable but **not officially tested or supported** for long-term production usage.

*   **SBC:** Raspberry Pi 4 Model B (4GB/8GB)
*   **Storage:** External SSD via USB 3.0
    *   *Warning:* USB-attached storage is less reliable than PCIe NVMe and may suffer from bus contention.
    *   *Constraint:* USB Boot is supported for legacy Pi 4, but **SD Cards remain prohibited** (see [ADR-0015](adr/0015-nvme-only-storage.md)).

---

## Storage Policy: "NVMe Only"

Silvasonic follows a strict storage policy to maximize data integrity and write endurance. See [ADR-0015](adr/0015-nvme-only-storage.md) for the full rationale.

1.  **Provisioning (SD Card Allowed):** An SD card may be used **temporarily** to update the bootloader or flash the OS onto the NVMe drive.
2.  **Production (Remove SD):** Once the system is provisioned, the SD Card **MUST be removed**. The system must boot and run entirely from the NVMe SSD.

---

## Audio Inputs (Tested Devices)

The following USB Class Compliant interfaces have been validated for stability and quality.
For technical details on how these devices are configured, see [Microphone Profiles](arch/microphone_profiles.md).

### Ultrasonic (Bat Monitoring)

*   **Dodotronic Ultramic 384 EVO**
    *   *Sample Rate:* 384 kHz
    *   *Type:* Integrated USB Ultrasonic Microphone

### Audible (Birds & Ambience)

*   **RØDE NT-USB**
    *   *Sample Rate:* 48 kHz
    *   *Type:* Studio-quality Cardioid Condenser
*   **Generic Interfaces:** Most Class Compliant USB interfaces (e.g., Focusrite Scarlett, Behringer U-Phoria) work but require manual configuration.

---

## Network Requirements

*   **Connection:** Gigabit Ethernet (Strongly Preferred) or Wi-Fi (Supported).
*   **VPN / Telemetry:** The local network firewall **MUST allow outgoing UDP traffic**.
    *   This is required for **Tailscale** (uses WireGuard internally) mesh networking to establish peer-to-peer connections for fleet management.

## Power & Environment

*   **Power Supply:** Use high-quality USB-C PD supplies (Official Pi Power Supply recommended). Voltage drops can cause NVMe instability.
*   **Cooling:** **Active Cooling is recommended** for all deployments. The enclosure must provide sufficient airflow to prevent thermal throttling during daylight analysis processing.
