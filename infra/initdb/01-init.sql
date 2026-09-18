-- Runs once, on first creation of the data volume.
CREATE EXTENSION IF NOT EXISTS vector;

-- Test database, so the suite never touches development data.
CREATE DATABASE radar_test OWNER radar;
\connect radar_test
CREATE EXTENSION IF NOT EXISTS vector;
