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
*   **Constraint:** **NVMe is mandatory.** SD Cards are strictly prohibited for production data storage due to low write endurance and throughput limits.

### Experimental / Legacy
Hardware that is technically capable but not officially supported for long-term production usage.

*   **SBC:** Raspberry Pi 4 Model B (4GB/8GB)
*   **Storage:** External SSD via USB 3.0
    *   *Warning:* USB-attached storage is less reliable than PCIe NVMe and may suffer from bus contention.
    *   *Note:* SD Cards are still **not** supported for data storage.

---

## Storage Policy: "No SD Card in Production"

Silvasonic follows a strict firmware-like appliance model:

1.  **Bootstrap Only:** The SD Card is used **solely** for the initial flashing and bootstrapping process (if not booting directly from NVMe).
2.  **Removal:** Once the system is provisioned to the NVMe drive, the SD Card **MUST be removed** (or the system configured to ignore it) to ensure no logging or data writing accidentally occurs on the slow medium.
3.  **All-NVMe:** The OS, Swap, Database, and Audio Buffers must all reside on the high-speed NVMe namespace.

---

## Audio Inputs (Tested Devices)

The following USB Class Compliant interfaces have been validated for stability and quality:

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
*   **VPN / Telemetry:** The local network firewall **MUST allow Outgoing UDP traffic**.
    *   This is required for **WireGuard / Tailscale** mesh networking to establish peer-to-peer connections for fleet management.

## Power & Environment

*   **Power Supply:** Use high-quality USB-C PD supplies (Official Pi Power Supply recommended). Voltage drops can cause NVMe instability.
*   **Cooling:** **Active Cooling is recommended** for all deployments. The enclosure must provide sufficient airflow to prevent thermal throttling during daylight analysis processing.
