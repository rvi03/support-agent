-- Runs as the superuser on database `servewell`. Idempotent.
-- pii.vault holds the real contact of each ticket (design.md, pii.vault).
-- Only agent_actor (the reply sender) and checker_ro (the K11 exact match) can
-- read it (P9); ingest and intake can only add rows. S4 may add columns.

CREATE TABLE IF NOT EXISTS pii.vault (
    ticket_id  text PRIMARY KEY,
    full_name  text,
    phone      text,
    mask_map   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON pii.vault FROM PUBLIC;
REVOKE ALL ON pii.vault FROM intake_rw, it_data_ro, knowledge_ro, itsm_rw, agent_actor,
    api_rw, checker_ro, ingest_rw, kb_index_rw, eval_ro;
GRANT SELECT ON pii.vault TO agent_actor, checker_ro;
GRANT INSERT ON pii.vault TO ingest_rw, intake_rw;

-- D52: the replay path copies a seeded source ticket's contact to the new
-- ticket inside the database, so no contact moves through a process.
-- SECURITY DEFINER runs as the owner (the superuser); a fixed search_path
-- stops a caller from shadowing objects. Only intake_rw may execute it.
CREATE OR REPLACE FUNCTION pii.copy_source_contact(source_ticket_id text, ticket_id text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    copied integer;
BEGIN
    INSERT INTO pii.vault (ticket_id, full_name, phone, mask_map)
    SELECT copy_source_contact.ticket_id, v.full_name, v.phone, v.mask_map
    FROM pii.vault AS v
    WHERE v.ticket_id = copy_source_contact.source_ticket_id;
    GET DIAGNOSTICS copied = ROW_COUNT;
    IF copied = 0 THEN
        RAISE EXCEPTION 'no vault row for source ticket %', source_ticket_id
            USING ERRCODE = 'no_data_found';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION pii.copy_source_contact(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pii.copy_source_contact(text, text) TO intake_rw;
