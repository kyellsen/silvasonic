# Services Database Dockerfile
# Base: TimescaleDB (Postgres 17)
FROM timescale/timescaledb:latest-pg17

# Fix: Add missing locales for Alpine
USER root
RUN apk add --no-cache musl-locales


LABEL maintainer="Silvasonic Project"
LABEL service="database"
LABEL description="TimescaleDB optimized for NVMe"

# 1. Install Init Scripts
# Files in /docker-entrypoint-initdb.d/ are run in alphabetical order
# ONLY on the first volume initialization.
COPY init/00-init-extensions.sql /docker-entrypoint-initdb.d/
COPY init/01-init-schema.sql /docker-entrypoint-initdb.d/

# 2. Install Configuration
# We copy our custom config to a location we can reference
COPY config/postgresql.conf /etc/postgresql/postgresql.conf

# Fix permissions for Podman Rootless (Socket Permission Denied)
RUN mkdir -p /var/run/postgresql && \
    chown -R postgres:postgres /var/run/postgresql && \
    chmod 2777 /var/run/postgresql

# 3. Override Command to use our config file
# The base image entrypoint handles the postgres startup, we just append args
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
