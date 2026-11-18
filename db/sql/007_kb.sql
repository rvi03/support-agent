-- Runs as the superuser on database `servewell`. Idempotent. (S6)
-- The KB index lives in two schemas with the same tables (rag-design.md section 5):
--   kb          the published revision; knowledge_ro and checker_ro read it.
--   kb_staging  the build area; only kb_index_rw writes it.
-- `make index` fills kb_staging, then calls kb_admin.publish(), which swaps the two
-- schemas in one transaction and re-applies the grants. kb_index_rw owns nothing and
-- runs no DDL: the swap runs as the owner through SECURITY DEFINER.
-- The vector width is fixed here (768, D64); the indexer refuses another EMBED_DIM.

CREATE SCHEMA IF NOT EXISTS kb_staging;
CREATE SCHEMA IF NOT EXISTS kb_admin;
REVOKE ALL ON SCHEMA kb_admin FROM PUBLIC;

DO $ddl$
DECLARE s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['kb', 'kb_staging'] LOOP
    EXECUTE format($t$
      CREATE TABLE IF NOT EXISTS %1$I.revisions (
        kb_rev           text PRIMARY KEY,
        created_at       timestamptz NOT NULL DEFAULT now(),
        source_hashes    jsonb NOT NULL,
        pipeline_version text NOT NULL,
        rule_versions    jsonb NOT NULL,
        report           jsonb NOT NULL,
        is_current       boolean NOT NULL DEFAULT false
      );
      CREATE UNIQUE INDEX IF NOT EXISTS revisions_one_current
        ON %1$I.revisions (is_current) WHERE is_current;

      CREATE TABLE IF NOT EXISTS %1$I.documents (
        kb_rev          text NOT NULL,
        doc_id          text NOT NULL,
        doc_type        text NOT NULL CHECK (doc_type IN ('runbook', 'sop', 'faq', 'spec')),
        title           text NOT NULL,
        categories      text[] NOT NULL,
        device_family   text[] NOT NULL,
        covered_systems jsonb NOT NULL,
        version_issues  jsonb NOT NULL,
        related         text[] NOT NULL,
        revision        text,
        last_updated    text,
        truncated       boolean NOT NULL,
        walkable        boolean,
        content_hash    text NOT NULL,
        masked_text     text NOT NULL,
        PRIMARY KEY (kb_rev, doc_id)
      );

      CREATE TABLE IF NOT EXISTS %1$I.sections (
        kb_rev            text NOT NULL,
        section_id        text NOT NULL,
        parent_section_id text,
        doc_id            text NOT NULL,
        doc_type          text NOT NULL,
        device_family     text[] NOT NULL,
        categories        text[] NOT NULL,
        path              text NOT NULL,
        ord               int NOT NULL,
        masked_text       text NOT NULL,
        index_text        text NOT NULL,
        bm25_tokens       text[] NOT NULL,
        token_count       int NOT NULL,
        conflict_ids      text[] NOT NULL DEFAULT '{}',
        embedding         vector(768) NOT NULL,
        PRIMARY KEY (kb_rev, section_id)
      );
      CREATE INDEX IF NOT EXISTS sections_bm25 ON %1$I.sections
        USING bm25 (bm25_tokens) WITH (text_config = 'simple', k1 = 1.5, b = 0.75);
      CREATE INDEX IF NOT EXISTS sections_hnsw ON %1$I.sections
        USING hnsw (embedding vector_cosine_ops);
      CREATE INDEX IF NOT EXISTS sections_doc ON %1$I.sections (kb_rev, doc_id, ord);

      CREATE TABLE IF NOT EXISTS %1$I.conflicts (
        kb_rev      text NOT NULL,
        conflict_id text NOT NULL,
        topic       text NOT NULL,
        docs        text[] NOT NULL,
        claims      jsonb NOT NULL,
        affects     jsonb NOT NULL,
        resolution  text NOT NULL CHECK (resolution IN ('flag_and_handoff', 'sop_wins')),
        PRIMARY KEY (kb_rev, conflict_id)
      );

      CREATE TABLE IF NOT EXISTS %1$I.redactions (
        kb_rev     text NOT NULL,
        doc_id     text NOT NULL,
        section_id text,
        "offset"   int NOT NULL,
        rule_id    text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
      );

      -- Group A runbooks parsed into rule-tagged steps (rag-design.md 6.2). S7 reads
      -- them to bind run_fix to a step; S9 fills them.
      CREATE TABLE IF NOT EXISTS %1$I.runbook_steps (
        kb_rev       text NOT NULL,
        doc_id       text NOT NULL,
        step_id      text NOT NULL,
        ord          int NOT NULL,
        stage        text NOT NULL CHECK (stage IN ('immediate', 'diagnosis', 'resolution')),
        scope        jsonb NOT NULL DEFAULT '{}'::jsonb,
        team         text NOT NULL CHECK (team IN ('store', 'it')),
        text         text NOT NULL,
        safety_lines text[] NOT NULL DEFAULT '{}',
        tags         jsonb NOT NULL DEFAULT '{}'::jsonb,
        generic      boolean NOT NULL DEFAULT false,
        action_id    text,
        section_id   text,
        PRIMARY KEY (kb_rev, doc_id, step_id)
      );

      CREATE TABLE IF NOT EXISTS %1$I.gaps (
        kb_rev text NOT NULL,
        doc_id text NOT NULL,
        kind   text NOT NULL CHECK (kind IN ('missing_link', 'truncated', 'version_not_covered',
                                             'not_walkable', 'unmapped_it_step')),
        detail text NOT NULL
      );
    $t$, s);
  END LOOP;
END
$ddl$;

-- Grants follow the schema name, not the tables, so they are re-applied after each swap.
CREATE OR REPLACE FUNCTION kb_admin.apply_grants() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $f$
BEGIN
  REVOKE ALL ON ALL TABLES IN SCHEMA kb, kb_staging
    FROM kb_index_rw, knowledge_ro, checker_ro, eval_ro, itsm_rw;
  GRANT USAGE ON SCHEMA kb, kb_staging TO kb_index_rw;
  -- itsm_rw (S7) reads the revision and the parsed steps to bind run_fix.
  GRANT SELECT ON ALL TABLES IN SCHEMA kb TO kb_index_rw, knowledge_ro, checker_ro, eval_ro,
    itsm_rw;
  GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA kb_staging
    TO kb_index_rw;
  REVOKE ALL ON SCHEMA kb_staging FROM knowledge_ro, checker_ro, eval_ro, itsm_rw;
  GRANT USAGE ON SCHEMA kb TO knowledge_ro, checker_ro, eval_ro, itsm_rw;
END
$f$;

-- Swap kb_staging in as kb. The caller checked the build; this checks it once more.
CREATE OR REPLACE FUNCTION kb_admin.publish(new_rev text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $f$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM kb_staging.revisions WHERE kb_rev = new_rev AND is_current;
  IF n <> 1 THEN
    RAISE EXCEPTION 'kb_staging has no current revision %', new_rev;
  END IF;
  SELECT count(*) INTO n FROM kb_staging.sections WHERE kb_rev = new_rev;
  IF n = 0 THEN
    RAISE EXCEPTION 'kb_staging revision % has no sections', new_rev;
  END IF;
  SELECT count(*) INTO n FROM kb_staging.sections WHERE kb_rev <> new_rev;
  IF n > 0 THEN
    RAISE EXCEPTION 'kb_staging holds rows of another revision';
  END IF;
  ALTER SCHEMA kb RENAME TO kb_swap;
  ALTER SCHEMA kb_staging RENAME TO kb;
  ALTER SCHEMA kb_swap RENAME TO kb_staging;
  PERFORM kb_admin.apply_grants();
END
$f$;

REVOKE ALL ON FUNCTION kb_admin.apply_grants() FROM PUBLIC;
REVOKE ALL ON FUNCTION kb_admin.publish(text) FROM PUBLIC;
GRANT USAGE ON SCHEMA kb_admin TO kb_index_rw;
GRANT EXECUTE ON FUNCTION kb_admin.publish(text) TO kb_index_rw;

-- 002 gave kb_index_rw write defaults on kb; the published schema is read-only to it.
ALTER DEFAULT PRIVILEGES IN SCHEMA kb REVOKE INSERT, UPDATE, DELETE ON TABLES FROM kb_index_rw;
SELECT kb_admin.apply_grants();

-- An earlier draft let the indexer read data.assets and data.version_matrix; it needs neither.
REVOKE SELECT ON data.assets, data.version_matrix FROM kb_index_rw;
REVOKE USAGE ON SCHEMA data FROM kb_index_rw;

-- The K4 replay and ablation (eval) read the sanitized KB (above) and the masked
-- source tickets; never raw text, never pii.
GRANT USAGE ON SCHEMA tickets TO eval_ro;
GRANT SELECT ON tickets.source_tickets TO eval_ro;
