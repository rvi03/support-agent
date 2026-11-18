-- Runs as the superuser on database `servewell`. Idempotent.
-- One login role per service, each with only the grants it needs (D25, D46).
-- Tables created later by the superuser pick up these grants through default
-- privileges, so later sub-tasks add tables without repeating grants.
-- audit and pii get no default privileges: their grants are per table (003, 004).
-- No agent-side role (intake, it-data, knowledge, itsm, agent, api) gets
-- anything on `eval`, so labels never reach the agent.

SELECT format('CREATE ROLE %I LOGIN', r)
FROM unnest(ARRAY['ingest_rw', 'intake_rw', 'it_data_ro', 'knowledge_ro', 'kb_index_rw',
                  'itsm_rw', 'agent_actor', 'api_rw', 'eval_ro', 'checker_ro']) AS r
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r) \gexec

ALTER ROLE ingest_rw    PASSWORD :'pw_ingest_rw';
ALTER ROLE intake_rw    PASSWORD :'pw_intake_rw';
ALTER ROLE it_data_ro   PASSWORD :'pw_it_data_ro';
ALTER ROLE knowledge_ro PASSWORD :'pw_knowledge_ro';
ALTER ROLE kb_index_rw  PASSWORD :'pw_kb_index_rw';
ALTER ROLE itsm_rw      PASSWORD :'pw_itsm_rw';
ALTER ROLE agent_actor  PASSWORD :'pw_agent_actor';
ALTER ROLE api_rw       PASSWORD :'pw_api_rw';
ALTER ROLE eval_ro      PASSWORD :'pw_eval_ro';
ALTER ROLE checker_ro   PASSWORD :'pw_checker_ro';

GRANT CONNECT ON DATABASE servewell TO ingest_rw, intake_rw, it_data_ro, knowledge_ro,
    kb_index_rw, itsm_rw, agent_actor, api_rw, eval_ro, checker_ro;

-- data: stores, assets, SLA, version matrix.
GRANT USAGE ON SCHEMA data TO ingest_rw, it_data_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ingest_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT USAGE ON SEQUENCES TO ingest_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO it_data_ro;

-- tickets: ingest writes staging and masked source tickets (D59); intake writes tickets.
GRANT USAGE ON SCHEMA tickets TO ingest_rw, intake_rw, it_data_ro, api_rw, checker_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA tickets GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ingest_rw, intake_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA tickets GRANT USAGE ON SEQUENCES TO ingest_rw, intake_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA tickets GRANT SELECT ON TABLES TO it_data_ro, api_rw, checker_ro;

-- kb: the indexer writes a revision; the knowledge server only reads.
GRANT USAGE ON SCHEMA kb TO kb_index_rw, knowledge_ro, checker_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA kb GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kb_index_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA kb GRANT USAGE ON SEQUENCES TO kb_index_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA kb GRANT SELECT ON TABLES TO knowledge_ro, checker_ro;

-- itsm: only the itsm-actions server writes.
GRANT USAGE ON SCHEMA itsm TO itsm_rw, api_rw, checker_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA itsm GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO itsm_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA itsm GRANT USAGE ON SEQUENCES TO itsm_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA itsm GRANT SELECT ON TABLES TO api_rw, checker_ro;

-- eval: labels and the split; ingest loads them, eval reads them, no agent role.
GRANT USAGE ON SCHEMA eval TO ingest_rw, eval_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ingest_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval GRANT USAGE ON SEQUENCES TO ingest_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval GRANT SELECT ON TABLES TO eval_ro;

-- audit and pii: schema usage only here; table grants in 003 and 004.
GRANT USAGE ON SCHEMA audit TO intake_rw, it_data_ro, knowledge_ro, itsm_rw, agent_actor,
    api_rw, checker_ro;
GRANT USAGE ON SCHEMA pii TO ingest_rw, intake_rw, agent_actor, checker_ro;
