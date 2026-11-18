-- Runs as the superuser on database `servewell`. Idempotent.
-- S4: intake builds its known-names list (submitters, L1 staff, region
-- managers) and its never-mask list (makes, models, systems, store names,
-- cities, neighbourhoods, store and asset ids) from the data at startup, so it
-- reads these reference tables. It still gets nothing on eval or pii reads.

GRANT USAGE ON SCHEMA data TO intake_rw;
GRANT SELECT ON data.stores, data.assets, data.version_matrix TO intake_rw;
