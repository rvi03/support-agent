-- Runs as the superuser on database `servewell`. Idempotent.
-- S3 source data: the raw-file manifest, the cleaned CSV tables, train ticket
-- staging and the masked source-ticket table, labels and the eval split.
-- Grants come from the default privileges in 002, except where noted.

-- Manifest of every file uploaded to servewell/raw (D4).
CREATE TABLE IF NOT EXISTS data.raw_files (
    path        text PRIMARY KEY,           -- object key, raw/<source path>
    sha256      text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    bytes       bigint NOT NULL CHECK (bytes >= 0),
    uploaded_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS data.stores (
    store_id       text PRIMARY KEY,
    store_name     text NOT NULL,
    city           text NOT NULL,
    neighborhood   text NOT NULL,
    store_type     text NOT NULL,
    region_manager text NOT NULL,
    support_phone  text NOT NULL
);

CREATE TABLE IF NOT EXISTS data.version_matrix (
    system       text NOT NULL,
    version      text NOT NULL,
    release_date date NOT NULL,
    known_bugs   text,                      -- "None known" -> NULL (rule c)
    patch_status text NOT NULL CHECK (patch_status IN ('Yes', 'No', 'Partial')),  -- rule b
    patch_fix    text,
    notes        text,
    PRIMARY KEY (system, version)
);

CREATE TABLE IF NOT EXISTS data.assets (
    asset_id          text PRIMARY KEY,
    store_id          text NOT NULL REFERENCES data.stores (store_id),
    asset_type        text NOT NULL,
    make              text NOT NULL,
    model             text NOT NULL,
    system_version    text NOT NULL,        -- as given
    system_name       text NOT NULL,        -- rule a: split from system_version
    version           text NOT NULL,
    serial_number     text NOT NULL UNIQUE,
    install_date      date NOT NULL,
    last_service_date date NOT NULL,
    warranty_expiry   date NOT NULL,
    FOREIGN KEY (system_name, version) REFERENCES data.version_matrix (system, version)
);
CREATE INDEX IF NOT EXISTS assets_store_idx ON data.assets (store_id);

CREATE TABLE IF NOT EXISTS data.sla_matrix (
    priority                  text NOT NULL,
    category                  text NOT NULL,
    first_response_minutes    integer NOT NULL CHECK (first_response_minutes > 0),
    resolution_target_minutes integer NOT NULL CHECK (resolution_target_minutes > 0),
    escalation_to_l2_minutes  integer NOT NULL CHECK (escalation_to_l2_minutes > 0),
    PRIMARY KEY (priority, category)
);

-- Train tickets with unmasked text, intake-schema fields only: no `status`,
-- no `resolution_notes` (CP3.3). Only ingest_rw and intake_rw may touch it (D59).
CREATE TABLE IF NOT EXISTS tickets.source_staging (
    ticket_id       text PRIMARY KEY,
    store_id        text NOT NULL,
    store_name      text,
    submitted_by    text,
    contact_phone   text,
    date_opened     timestamptz NOT NULL,
    priority        text,
    category        text,
    subcategory     text,
    subject         text NOT NULL,
    description     text NOT NULL,
    asset_id        text,
    system_version  text,
    tags            jsonb NOT NULL DEFAULT '[]'::jsonb,
    escalation_flag boolean,
    related_tickets jsonb NOT NULL DEFAULT '[]'::jsonb,
    ticket_history  jsonb NOT NULL DEFAULT '[]'::jsonb
);
-- 002 gives every new tickets.* table SELECT to these reader roles; staging must not.
REVOKE ALL ON tickets.source_staging FROM PUBLIC, it_data_ro, api_rw, checker_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON tickets.source_staging TO ingest_rw, intake_rw;

-- Masked train tickets, written by the S4 seed hook; read by the history tools.
-- The contact fields live only in pii.vault.
CREATE TABLE IF NOT EXISTS tickets.source_tickets (
    ticket_id       text PRIMARY KEY,
    store_id        text NOT NULL,
    store_name      text,
    date_opened     timestamptz NOT NULL,
    priority        text,
    category        text,
    subcategory     text,
    subject         text NOT NULL,
    description     text NOT NULL,
    asset_id        text,
    system_version  text,
    tags            jsonb NOT NULL DEFAULT '[]'::jsonb,
    escalation_flag boolean,
    related_tickets jsonb NOT NULL DEFAULT '[]'::jsonb,
    ticket_history  jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS source_tickets_store_idx
    ON tickets.source_tickets (store_id, date_opened);
CREATE INDEX IF NOT EXISTS source_tickets_asset_idx
    ON tickets.source_tickets (asset_id, date_opened);

-- eval: no agent role has any grant on this schema (002).
CREATE TABLE IF NOT EXISTS eval.ticket_index (
    ticket_id       text PRIMARY KEY,
    store_id        text NOT NULL,
    date_opened     timestamptz NOT NULL,
    priority        text NOT NULL,
    category        text NOT NULL,
    subcategory     text NOT NULL,
    status          text NOT NULL,
    chaos_type      text,                   -- NULL for normal tickets
    escalation_flag boolean NOT NULL,
    filename        text NOT NULL           -- rule d: tickets/train/<id>.json
);

CREATE TABLE IF NOT EXISTS eval.labels (
    ticket_id                  text PRIMARY KEY,
    correct_routing            text NOT NULL,
    should_escalate            boolean NOT NULL,
    escalation_reason          text,
    expected_agent_action      text NOT NULL,
    relevant_kb_docs           jsonb NOT NULL,
    correct_resolution_summary text NOT NULL,
    chaos_correct_behavior     text NOT NULL,
    evaluator_notes            text NOT NULL
);

-- The committed split (eval/split.json, D39), one row per ticket.
CREATE TABLE IF NOT EXISTS eval.split (
    ticket_id text PRIMARY KEY,
    half      text NOT NULL CHECK (half IN ('tune', 'heldout')),
    cohort    text NOT NULL CHECK (cohort IN ('labelled', 'tricky'))
);
