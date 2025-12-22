-- postgres postgres
-- CONNECT TO postgres USER postgres;

-- rds needs this https://stackoverflow.com/a/34898033
GRANT "quantdb-admin" TO CURRENT_USER;

-- postgres postgres

CREATE DATABASE :database -- quantdb
    WITH OWNER = 'quantdb-admin'
    ENCODING = 'UTF8'
    --TABLESPACE = pg_default  -- leave this out for now since rds doesn't really support it
    -- Use template0 to avoid collation conflicts, or inherit from template1
    TEMPLATE = template0
    LC_COLLATE = 'C'  -- Use C collation for maximum compatibility
    LC_CTYPE = 'C'
    CONNECTION LIMIT = -1;

REVOKE "quantdb-admin" FROM CURRENT_USER;
