-- Runs as the superuser on database `servewell`. Idempotent.
-- audit.events is append-only: INSERT is the only grant, and a trigger raises
-- on UPDATE, DELETE or TRUNCATE for every role, the owner included (D9, CP2.2).

CREATE TABLE IF NOT EXISTS audit.events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts             timestamptz NOT NULL DEFAULT clock_timestamp(),
    run_id         uuid,
    ticket_id      text,
    step           text NOT NULL,
    actor          text NOT NULL,
    action         text NOT NULL,
    reason         text,
    source         text,
    result         text NOT NULL,
    kb_rev         text,
    step_id        text,
    action_id      text,
    tier           text,
    autonomy_state text,
    approval_id    text,
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS events_ticket_idx ON audit.events (run_id, ticket_id, ts);

CREATE OR REPLACE FUNCTION audit.refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only: % refused', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

DROP TRIGGER IF EXISTS events_no_update_delete ON audit.events;
CREATE TRIGGER events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.refuse_change();

DROP TRIGGER IF EXISTS events_no_truncate ON audit.events;
CREATE TRIGGER events_no_truncate
    BEFORE TRUNCATE ON audit.events
    FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_change();

REVOKE ALL ON audit.events FROM PUBLIC;
REVOKE ALL ON audit.events FROM intake_rw, it_data_ro, knowledge_ro, itsm_rw, agent_actor,
    api_rw, checker_ro, ingest_rw, kb_index_rw, eval_ro;
GRANT INSERT ON audit.events TO intake_rw, it_data_ro, knowledge_ro, itsm_rw, agent_actor, api_rw;
-- `INSERT ... RETURNING id` needs SELECT on the returned column: the writers may
-- read back ids only, never an event's content (write_event, S4 fix).
GRANT SELECT (id) ON audit.events TO intake_rw, it_data_ro, knowledge_ro, itsm_rw, agent_actor,
    api_rw;
GRANT SELECT ON audit.events TO checker_ro;
