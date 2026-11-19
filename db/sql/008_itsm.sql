-- Runs as the superuser on database `servewell`. Idempotent. (S7)
-- The local ITSM written by the itsm-actions server (role itsm_rw).
-- Every row carries run_id (D45). Every write carries an idempotency key
-- `<run_id>:<ticket_id>:<node>:<step>`; itsm.idempotency keeps the first reply
-- per key, so a repeated key returns it and writes nothing new.
-- Grants come from the default privileges in 002 (itsm_rw writes; api_rw and
-- checker_ro read), narrowed below so the history tables are append-only.

CREATE TABLE IF NOT EXISTS itsm.idempotency (
    idem_key    text PRIMARY KEY,
    run_id      uuid NOT NULL,
    ticket_id   text NOT NULL,
    tool        text NOT NULL,
    args_sha256 text NOT NULL,
    response    jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS itsm.tickets (
    run_id            uuid NOT NULL,
    ticket_id         text NOT NULL,
    store_id          text NOT NULL,           -- from the bound call context, never the body
    asset_id          text,
    submitted_by_user text,                    -- requester user id (P3)
    date_opened       timestamptz NOT NULL,
    clock_offset      interval NOT NULL DEFAULT '0',  -- replay time minus wall time (D48)
    route             text,
    category          text,
    real_category     text,
    priority          text,
    status            text NOT NULL DEFAULT 'new',
    assignee_queue    text,
    runbook_id        text,
    kb_rev            text,
    first_response_by timestamptz,
    escalate_by       timestamptz,
    resolve_by        timestamptz,
    create_sha256     text NOT NULL,           -- create_ticket payload, for the conflict check
    idem_key          text NOT NULL UNIQUE,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS itsm.ticket_comments (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id     uuid NOT NULL,
    ticket_id  text NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('note', 'l1_pack', 'l2_note', 'system')),
    body       text NOT NULL,
    idem_key   text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);

-- The only table that may hold real contact values (reply sender, P9).
CREATE TABLE IF NOT EXISTS itsm.store_messages (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id     uuid NOT NULL,
    ticket_id  text NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('step', 'framing_template', 'redirect', 'clarify',
                                             'status_template', 'summary')),
    section_id text,
    body       text NOT NULL,
    idem_key   text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS itsm.approvals (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        uuid NOT NULL,
    ticket_id     text NOT NULL,
    asset_id      text NOT NULL,
    section_id    text NOT NULL,
    quote         text NOT NULL,
    action_id     text NOT NULL,
    kb_rev        text NOT NULL,
    approver_role text NOT NULL CHECK (approver_role IN ('l2_engineer', 'vendor_approver')),
    requested_by  text NOT NULL,
    decided_by    text,
    decision      text CHECK (decision IN ('approved', 'rejected')),
    reason        text,
    requested_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    decided_at    timestamptz,
    expires_at    timestamptz NOT NULL,       -- wall clock + APPROVAL_TTL_MIN (D48)
    used_at       timestamptz,                -- single use: set with the actions insert
    idem_key      text NOT NULL UNIQUE,
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS itsm.actions (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                uuid NOT NULL,
    ticket_id             text NOT NULL,
    asset_id              text NOT NULL,
    device_model          text NOT NULL,
    section_id            text NOT NULL,
    quote                 text NOT NULL,
    action_id             text NOT NULL,
    kb_rev                text NOT NULL,
    registry_version      text NOT NULL,
    tier                  text NOT NULL CHECK (tier IN ('read_only', 'reversible', 'destructive')),
    autonomy_state_at_run text NOT NULL CHECK (autonomy_state_at_run IN ('supervised', 'autonomous')),
    approval_id           uuid REFERENCES itsm.approvals (id),
    outcome               text NOT NULL CHECK (outcome IN ('fixed', 'no_change', 'failed')),
    result                text NOT NULL,
    eval_mode             boolean NOT NULL,
    idem_key              text NOT NULL UNIQUE,
    created_at            timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);
-- One approval runs at most one action, whatever the idempotency key (Codex F1).
CREATE UNIQUE INDEX IF NOT EXISTS actions_one_per_approval
    ON itsm.actions (approval_id) WHERE approval_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS itsm.l2_tasks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     uuid NOT NULL,
    ticket_id  text NOT NULL,
    section_id text,
    reason     text NOT NULL CHECK (reason IN ('l2_only', 'secret', 'destructive_store_step',
                                               'unmapped', 'guard')),
    note       text NOT NULL,
    result     text CHECK (result IN ('done', 'failed')),
    result_note text,
    done_by    text,
    done_at    timestamptz,
    idem_key   text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, ticket_id) REFERENCES itsm.tickets (run_id, ticket_id)
);

-- S8a: approvals, actions, messages and L2 tasks bind to a runbook section and the
-- quoted runbook words, not to parsed steps. Upgrade tables made before S8a.
DO $mig$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['store_messages', 'approvals', 'actions', 'l2_tasks'] LOOP
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'itsm' AND table_name = t AND column_name = 'step_id') THEN
      EXECUTE format('ALTER TABLE itsm.%I RENAME COLUMN step_id TO section_id', t);
    END IF;
  END LOOP;
  ALTER TABLE itsm.l2_tasks ALTER COLUMN section_id DROP NOT NULL;
  ALTER TABLE itsm.approvals ADD COLUMN IF NOT EXISTS quote text NOT NULL DEFAULT '';
  ALTER TABLE itsm.approvals ALTER COLUMN quote DROP DEFAULT;
  ALTER TABLE itsm.actions ADD COLUMN IF NOT EXISTS quote text NOT NULL DEFAULT '';
  ALTER TABLE itsm.actions ALTER COLUMN quote DROP DEFAULT;
END
$mig$;

-- Autonomy per (action, device model) (D37); only code promotes (P5).
CREATE TABLE IF NOT EXISTS itsm.action_autonomy (
    action_id     text NOT NULL,
    device_model  text NOT NULL,
    state         text NOT NULL DEFAULT 'supervised' CHECK (state IN ('supervised', 'autonomous')),
    runs_in_a_row int NOT NULL DEFAULT 0 CHECK (runs_in_a_row >= 0),
    changed_at    timestamptz NOT NULL DEFAULT now(),
    why           text NOT NULL DEFAULT 'initial',
    PRIMARY KEY (action_id, device_model)
);

CREATE TABLE IF NOT EXISTS itsm.action_autonomy_history (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action_id    text NOT NULL,
    device_model text NOT NULL,
    run_id       uuid,
    ticket_id    text,
    event        text NOT NULL CHECK (event IN ('run', 'reject', 'admin_demote')),
    approved     boolean,
    success      boolean,
    state_before text NOT NULL,
    state_after  text NOT NULL,
    runs_before  int NOT NULL,
    runs_after   int NOT NULL,
    eval_mode    boolean NOT NULL,
    why          text NOT NULL,
    at           timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- History and sent text are append-only for the writer.
REVOKE UPDATE, DELETE, TRUNCATE ON itsm.ticket_comments, itsm.store_messages, itsm.actions,
    itsm.action_autonomy_history FROM itsm_rw;
REVOKE DELETE, TRUNCATE ON itsm.tickets, itsm.approvals, itsm.l2_tasks, itsm.idempotency,
    itsm.action_autonomy FROM itsm_rw;

-- The server checks the asset's store and device family itself (P8), and reads the
-- ticket's runbook sections (kb.sections, granted in 007) to check a quote.
GRANT USAGE ON SCHEMA data TO itsm_rw;
GRANT SELECT ON data.assets TO itsm_rw;
