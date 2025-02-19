-- postgres postgres
-- CONNECT TO postgres USER postgres;

DO
$body$
BEGIN
    -- test
    IF NOT EXISTS ( SELECT * FROM pg_catalog.pg_user
        WHERE usename = 'quantdb-test-user') THEN
        CREATE ROLE "quantdb-test-user" LOGIN
        NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS ( SELECT * FROM pg_catalog.pg_user
        WHERE usename = 'quantdb-test-admin') THEN
        CREATE ROLE "quantdb-test-admin" LOGIN
        NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE;
    END IF;
    -- prod
    IF NOT EXISTS ( SELECT * FROM pg_catalog.pg_user
        WHERE usename = 'quantdb-user') THEN
        CREATE ROLE "quantdb-user" LOGIN
        NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS ( SELECT * FROM pg_catalog.pg_user
        WHERE usename = 'quantdb-admin') THEN
        CREATE ROLE "quantdb-admin" LOGIN
        NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE;
    END IF;
END;
$body$ language plpgsql;

-- postgres postgres

ALTER ROLE "quantdb-test-admin" SET search_path = quantdb, public;
ALTER ROLE "quantdb-test-user" SET search_path = quantdb, public;
ALTER ROLE "quantdb-admin" SET search_path = quantdb, public;
ALTER ROLE "quantdb-user" SET search_path = quantdb, public;
