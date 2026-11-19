-- Runs as the superuser on database `servewell`. Idempotent. (S11, build step 7)
-- The SLA timer runs in the agent process as agent_actor. It reads only what it
-- needs to find tickets past escalate-by and their open pause: no text, no names.
-- Every write still goes through itsm-actions (the pending compare-and-clear, D53).
GRANT USAGE ON SCHEMA itsm TO agent_actor;
REVOKE ALL ON itsm.tickets, itsm.pending FROM agent_actor;
GRANT SELECT (run_id, ticket_id, status, route, assignee_queue, escalate_by, clock_offset)
    ON itsm.tickets TO agent_actor;
GRANT SELECT (pending_id, run_id, ticket_id, kind, cleared_at) ON itsm.pending TO agent_actor;
