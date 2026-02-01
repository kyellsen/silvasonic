# Status Board Service

## Overview
The **Status Board** service provides a lightweight, real-time dashboard for monitoring the Silvasonic system. It allows developers and operators to visualize the state of the system, including microphone status, recent detections, and system health metrics.

## Responsibilities
- Display real-time status of all connected nodes.
- Show recent audio event detections.
- Visualize system health metrics (from Redis/Database).
- serve as a debugging interface during development.

## Tech Stack
- **Language**: Python 3.11
- **Framework**: FastAPI (or strictly Uvicorn/Starlette as per `web_interface`)
- **Frontend**: HTML/CSS/JS (embedded)

## Operational Constraints
- Runs as a non-privileged user.
- Connects to `database` and `redis`.
- Exposed internally; routed via Gateway.
- **Development Mode**: `DEV_MODE=true` enables hot reloading.
