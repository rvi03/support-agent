-- Runs as the superuser on database `postgres`. Idempotent.
-- Creates the three databases and the owner roles of the two platform ones.
-- Passwords come in as psql variables from `make up` (never stored here).

SELECT 'CREATE ROLE langfuse LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'langfuse') \gexec
ALTER ROLE langfuse PASSWORD :'pw_langfuse';

SELECT 'CREATE ROLE keycloak LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'keycloak') \gexec
ALTER ROLE keycloak PASSWORD :'pw_keycloak';

SELECT 'CREATE DATABASE servewell'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'servewell') \gexec
SELECT 'CREATE DATABASE langfuse OWNER langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse') \gexec
SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak') \gexec

-- Only listed roles may connect to each database (granted in 002 for servewell).
REVOKE CONNECT, TEMPORARY ON DATABASE servewell FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE langfuse FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT ON DATABASE langfuse TO langfuse;
GRANT CONNECT ON DATABASE keycloak TO keycloak;
