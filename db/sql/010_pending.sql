-- Runs as the superuser on database `servewell`. Idempotent. (S10, D53)
-- One typed pending item per pause. The agent writes it through itsm-actions before
-- any interrupt; a resume names the pending_id and clears it with one atomic
-- compare-and-clear, so a reply, an approval and a timeout cannot all win.
CREATE TABLE IF NOT EXISTS itsm.pending (
    pending_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      uuid NOT NULL,
    ticket_id   text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('answer', 'store_reply', 'approval', 'l2_task')),
    step_id     text,
    approval_id uuid REFERENCES itsm.approvals (id),
    idem_key    text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    cleared_at  timestamptz,
    cleared_by  text CHECK (cleared_by IN ('answer', 'store_reply', 'approval', 'l2_task',
                                           'timeout')),
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);
-- At most one open pause per ticket run.
CREATE UNIQUE INDEX IF NOT EXISTS pending_one_open
    ON itsm.pending (run_id, ticket_id) WHERE cleared_at IS NULL;
REVOKE DELETE, TRUNCATE ON itsm.pending FROM itsm_rw;
