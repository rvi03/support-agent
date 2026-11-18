-- Runs as the superuser on database `servewell`. Idempotent.
-- Every schema and table is owned by the superuser, so no service role can
-- ALTER, DROP or TRUNCATE anything, or disable a trigger.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_textsearch;

CREATE SCHEMA IF NOT EXISTS data;     -- stores, assets, SLA matrix, version matrix (S3)
CREATE SCHEMA IF NOT EXISTS tickets;  -- staging, masked source tickets, intake tickets (S3, S4)
CREATE SCHEMA IF NOT EXISTS kb;       -- KB revisions, sections, runbook steps (S6, S9)
CREATE SCHEMA IF NOT EXISTS itsm;     -- local ITSM tables (S7)
CREATE SCHEMA IF NOT EXISTS audit;    -- append-only audit log (003)
CREATE SCHEMA IF NOT EXISTS pii;      -- contact vault (004, S4)
CREATE SCHEMA IF NOT EXISTS eval;     -- labels and split; no agent role reads it (S3)

-- Nobody but the owner creates objects anywhere.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
