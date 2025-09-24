-- postgres postgres
-- CONNECT TO postgres USER postgres;
GRANT "quantdb-test-admin" TO CURRENT_USER;

-- postgres postgres

DROP DATABASE IF EXISTS :test_database;

-- rds needs this https://stackoverflow.com/a/34898033

-- postgres postgres

CREATE DATABASE :test_database -- quantdb
    WITH OWNER = 'quantdb-test-admin'
    ENCODING = 'UTF8'
    --TABLESPACE = pg_default  -- leave this out for now since rds doesn't really support it
    -- Use template0 to avoid collation conflicts, or inherit from template1
    TEMPLATE = template0
    LC_COLLATE = 'C'  -- Use C collation for maximum compatibility
    LC_CTYPE = 'C'
    CONNECTION LIMIT = -1;

REVOKE "quantdb-test-admin" FROM CURRENT_USER;
