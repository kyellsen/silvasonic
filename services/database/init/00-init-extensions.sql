-- 00-init-extensions.sql
-- Responsibility: Enable required extensions and set up initial permissions.
-- This runs as Superuser during the very first container initialization.

-- 1. Enable TimescaleDB (Core requirement)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Ensure public schema exists (Standard Postgres behavior, but explicit is safer)
CREATE SCHEMA IF NOT EXISTS public;

-- 3. Optimization Note (Documentation)
-- The actual tables are NOT created here. They are managed by Alembic/SQLAlchemy
-- in the 'controller' or 'migration' service to allow for versioned schema evolution.
