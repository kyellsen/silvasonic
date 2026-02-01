-- Enable TimescaleDB extension
-- This must run as a superuser (which the init container usually is)
CREATE EXTENSION IF NOT EXISTS timescaledb;
