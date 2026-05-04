-- postgres postgres
-- Local version of test_database.sql for localhost PostgreSQL (collation C)
-- CONNECT TO postgres USER postgres;
GRANT "quantdb-test-admin" TO CURRENT_USER;

-- postgres postgres

DROP DATABASE IF EXISTS :test_database;

-- postgres postgres

CREATE DATABASE :test_database -- quantdb
    WITH OWNER = 'quantdb-test-admin'
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    CONNECTION LIMIT = -1;

REVOKE "quantdb-test-admin" FROM CURRENT_USER;
