-- Runs as the superuser on database `servewell`. Idempotent. (S12)
-- The API process runs intake (as intake_rw) and reads the ITSM as api_rw.
--
-- tickets.api_tickets: one row per accepted POST /tickets, written by intake_rw
-- before the 202, so a second replay of the same source ticket in one run is a
-- synchronous 409 (D45) and a ticket is listed before the graph writes itsm.tickets.
-- It holds ids, states and the masked subject only: no contact.
CREATE TABLE IF NOT EXISTS tickets.api_tickets (
    ticket_id         text PRIMARY KEY,
    run_id            uuid NOT NULL,
    store_id          text NOT NULL,
    submitted_by_user text NOT NULL,           -- the token's sub (P3 requester)
    client_id         text NOT NULL,
    source_ticket_id  text,                     -- eval-runner replay only (D52)
    date_opened       timestamptz NOT NULL,
    raw_key           text NOT NULL,            -- raw/tickets/incoming/<ticket_id>.json
    subject           text,                     -- masked, written after intake
    api_status        text NOT NULL DEFAULT 'accepted'
                      CHECK (api_status IN ('accepted', 'running', 'done', 'failed')),
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, ticket_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS api_tickets_one_source_per_run
    ON tickets.api_tickets (run_id, source_ticket_id) WHERE source_ticket_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS api_tickets_store_idx ON tickets.api_tickets (store_id, created_at);
REVOKE DELETE, TRUNCATE ON tickets.api_tickets FROM intake_rw, ingest_rw;

-- The ticket row keeps the source ticket for scoring (labels are keyed by it, D52).
ALTER TABLE itsm.tickets ADD COLUMN IF NOT EXISTS source_ticket_id text;

-- api_rw: P3 compares the approval card's kb_rev with the published one. Grants on
-- kb follow the schema name and are reset by every publish swap (007), so the API
-- gets a function that returns the current revision id and nothing else.
CREATE OR REPLACE FUNCTION kb_admin.current_rev() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $f$
  SELECT kb_rev FROM kb.revisions WHERE is_current LIMIT 1
$f$;
REVOKE ALL ON FUNCTION kb_admin.current_rev() FROM PUBLIC;
GRANT USAGE ON SCHEMA kb_admin TO api_rw;
GRANT EXECUTE ON FUNCTION kb_admin.current_rev() TO api_rw;

-- The ticket view shows an audit summary. api_rw reads no payload (free text).
GRANT SELECT (id, ts, run_id, ticket_id, step, actor, action, result, reason)
    ON audit.events TO api_rw;

-- Tables made before `subject` was added.
ALTER TABLE tickets.api_tickets ADD COLUMN IF NOT EXISTS subject text;
