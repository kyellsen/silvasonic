# Testing Guide

> **TODO** — Diese Seite dokumentiert die Test-Strategie und -Infrastruktur.

## Test-Marker

| Marker        | Beschreibung                                          |
| ------------- | ----------------------------------------------------- |
| `unit`        | Schnelle, isolierte Tests ohne externe Abhängigkeiten |
| `integration` | Tests mit externen Services (DB via Testcontainers)   |
| `smoke`       | Health-Checks auf laufende Container                  |
| `e2e`         | Browser-Tests via Playwright                          |

## Tests ausführen

```bash
make test-unit       # Unit-Tests
make test-int        # Integrationstests
make test-smoke      # Smoke-Tests (Stack muss laufen)
make test-all        # Unit + Integration
```

## Coverage

_Noch zu dokumentieren._
