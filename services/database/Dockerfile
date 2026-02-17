# ==============================================================================
# Silvasonic Database Image
# Based on TimescaleDB with PostgreSQL 17.
# ==============================================================================

FROM docker.io/timescale/timescaledb:2.19.3-pg17

LABEL org.opencontainers.image.title="silvasonic-database"
LABEL org.opencontainers.image.description="TimescaleDB instance for Silvasonic bioacoustic data"

# Custom PostgreSQL configuration (Pi 5 + NVMe optimized)
COPY services/database/postgresql.conf /etc/postgresql/postgresql.conf

# --- Custom init scripts (executed once on first start, alphabetical order) ---
# Place .sql or .sh files here:
# COPY services/database/initdb/ /docker-entrypoint-initdb.d/

EXPOSE 5432

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
