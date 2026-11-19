-- S8: the agent's masker reference (never-mask places, devices, systems and ids).
-- agent_actor reads only the columns the reference needs: no region_manager,
-- no support_phone, no ticket staging (D59, D92). Idempotent.
GRANT USAGE ON SCHEMA data TO agent_actor;
REVOKE ALL ON data.stores, data.assets, data.version_matrix FROM agent_actor;
GRANT SELECT (store_id, store_name, city, neighborhood) ON data.stores TO agent_actor;
GRANT SELECT (asset_id, asset_type, make, model, system_name) ON data.assets TO agent_actor;
GRANT SELECT (system) ON data.version_matrix TO agent_actor;
