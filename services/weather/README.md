# Container: Weather

> **Service Name:** `weather`
> **Container Name:** `silvasonic-weather`
> **Package Name:** `silvasonic-weather`

## 1. The Problem / The Gap
*   **Context:** Bioacoustic activity is heavily dependent on weather (wind, rain, temperature). Analyzing recordings without knowing if it was storming is difficult.
*   **Completeness:** A field station should provide a holistic view of the environment.

## 2. User Benefit
*   **Correlation:** "Do bats fly tonight?" (Correlate with Temp/Wind).
*   **Logbook:** Automated weather log for the deployment site.

## 3. Core Responsibilities
Derived strictly from the *Code Truth* (inputs/logic/outputs).

*   **Inputs**:
    *   **Hardware Sensors**: BME280/BMP280 via I2C (Temperature, Humidity, Pressure).
    *   **External API**: OpenMeteo (Forecast/Wind/Precipitation) for metrics sensors can't measure.
*   **Processing**:
    *   **Polling**: Reading sensors every N minutes.
    *   **Normalization**: Converting units.
*   **Outputs**:
    *   **Database Rows**: Inserts into `weather` table.
    *   **Current Status**: Redis key for UI display.

## 4. Operational Constraints & Rules
Specific technical rules this service must obey (derived from code analysis or architectural mandates).

*   **Concurrency**: **Low**.
*   **State**: **Stateless**.
*   **Privileges**: **Hardware Access**. Requires access to `/dev/i2c-*` (Group `i2c`).
*   **Resources**: Minimal.

## 5. Configuration & Environment
*   **Environment Variables**:
    *   `LATITUDE`/`LONGITUDE`.
    *   `I2C_BUS`: Device ID.
*   **Volumes**:
    *   `/dev/i2c-1` (Device).
*   **Dependencies**:
    *   `smbus2`.

## 6. Out of Scope (Abgrenzung)
What does this container explicitly NOT do?
*   **Does NOT** record audio.
*   **Does NOT** analyze sound (BirdNET job).
*   **Does NOT** manage other containers (Controller job).
*   **Does NOT** provide a map UI (Web Interface job).
*   **Does NOT** run high-frequency polling (Environmental data is slow-moving).

## 7. Technology Stack
*   **Base Image**: `python:3.11-slim-bookworm` (Dockerfile).
*   **Key Libraries**:
    *   None currently installed (Scaffolding).
*   **Build System**: `uv` + `Dockerfile`.

## 8. Critical Analysis & Future Improvements
*   **Best Practice Check**: Hybrid approach (Local + API) fills data gaps (e.g. rain).
*   **Alternatives**: None.

## 9. Discrepancy Report (Code vs. Rules)
*Only populate if conflicts exist. If the code perfectly matches the architecture docs, state "None detected."*

*   **Conflict:** **SCAFFOLDING ONLY**: The `pyproject.toml` is empty. Core libs like `smbus2` are NOT yet installed.
