# Testing Guide

> **TODO** — This page documents the testing strategy and infrastructure.

## Test Markers

| Marker        | Description                                          |
| ------------- | ---------------------------------------------------- |
| `unit`        | Fast, isolated tests without external dependencies   |
| `integration` | Tests with external services (DB via Testcontainers) |
| `smoke`       | Health checks against running containers             |
| `e2e`         | Browser tests via Playwright                         |

## Running Tests

```bash
just test-unit       # Unit tests
just test-int        # Integration tests
just test-smoke      # Smoke tests (stack must be running)
just test-all        # Unit + Integration
```

## Coverage

_To be documented._
