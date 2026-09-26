-- Runs against POSTGRES_DB on first initialization only (empty data directory).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

-- Apache AGE is used per session: LOAD the library and put ag_catalog on the
-- search_path. These SET/LOAD statements affect only this init session; the
-- application repeats them on every connection (common/database/connection.py),
-- which is the approach the official AGE setup documentation prescribes.
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
