import subprocess
from pathlib import Path

import pytest
from flask_sqlalchemy import SQLAlchemy

from quantdb.api import make_app
from quantdb.config import auth


# ---------------------------------------------------------------------------
# pytest CLI flag: --run-aws
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        '--run-aws',
        action='store_true',
        default=False,
        help='Run tests marked with @pytest.mark.aws',
    )


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'aws: mark test as requiring AWS RDS connectivity',
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption('--run-aws'):
        return
    skip_aws = pytest.mark.skip(reason='need --run-aws option to run')
    for item in items:
        if 'aws' in item.keywords:
            item.add_marker(skip_aws)


# ---------------------------------------------------------------------------
# Flask fixtures (used by test_api.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    db = SQLAlchemy()
    app = make_app(db=db, dev=True)  # test=True is the default
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Shared database rebuild fixture
# ---------------------------------------------------------------------------

_SQL_DIR = Path(__file__).resolve().parent.parent / 'sql'
_PROD_DUMP = (
    Path(__file__).resolve().parent.parent
    / 'resources'
    / 'quantdb_production_template.dump'
)
_PG_RESTORE = '/opt/homebrew/opt/postgresql@16/bin/pg_restore'


def _psql(
    sql=None,
    *,
    file=None,
    database='postgres',
    host='localhost',
    port=5432,
    extra_vars=None,
):
    """Run a psql command against the local PostgreSQL instance."""
    cmd = [
        'psql', '-U', 'postgres',
        '-h', host, '-p', str(port),
        '-d', database,
        '-v', 'ON_ERROR_STOP=on',
    ]
    if extra_vars:
        for k, v in extra_vars.items():
            cmd.extend(['-v', f'{k}={v}'])
    if file is not None:
        cmd.extend(['-f', str(file)])
    elif sql is not None:
        cmd.extend(['-c', sql])
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


@pytest.fixture(scope='session')
def rebuild_database():
    """Drop and recreate quantdb_test from scratch, restore production dump.

    Steps:
        1. Create roles (postgres.sql)
        2. Drop/create database (local_test_database.sql)
        3. Set search_path for postgres role
        4. Create schema (schemas.sql)
        5. Create tables/functions/triggers (tables.sql)
        6. Grant permissions (permissions.sql)
        7. Drop unique constraints that conflict with dump duplicates
        8. pg_restore data from production dump
        9. Deduplicate and restore unique constraints
    """
    test_db = auth.get('test-db-database')
    assert test_db == 'quantdb_test', f'Unexpected test database: {test_db}'

    # Step 1: Create roles
    _psql(file=_SQL_DIR / 'postgres.sql', extra_vars={
        'test_database': test_db,
        'database': test_db,
    })

    # Step 2: Drop and create database
    _psql(sql='GRANT "quantdb-test-admin" TO CURRENT_USER;')
    _psql(sql=f'DROP DATABASE IF EXISTS {test_db};')
    _psql(sql=(
        f'CREATE DATABASE {test_db}'
        f"  WITH OWNER = 'quantdb-test-admin'"
        f"  TEMPLATE template0"
        f"  ENCODING = 'UTF8'"
        f"  LC_COLLATE = 'C'"
        f"  LC_CTYPE = 'C'"
        f"  CONNECTION LIMIT = -1;"
    ))
    _psql(sql='REVOKE "quantdb-test-admin" FROM CURRENT_USER;')

    # Step 3: Set search_path for postgres role
    _psql(sql='ALTER ROLE postgres SET search_path = quantdb, public;')

    # Step 4: Create schema
    _psql(file=_SQL_DIR / 'schemas.sql', database=test_db)

    # Step 5: Create tables, functions, triggers
    _psql(file=_SQL_DIR / 'tables.sql', database=test_db)

    # Step 6: Grant permissions
    _psql(
        file=_SQL_DIR / 'permissions.sql',
        database=test_db,
        extra_vars={
            'database': test_db,
            'perm_user': 'quantdb-test-user',
        },
    )

    # Step 7: Drop unique constraints that conflict with dump duplicates
    _psql(
        sql=(
            'ALTER TABLE quantdb.values_cat'
            '  DROP CONSTRAINT IF EXISTS'
            '  values_cat_object_instance_desc_cat_key;'
            ' ALTER TABLE quantdb.values_quant'
            '  DROP CONSTRAINT IF EXISTS'
            '  values_quant_object_instance_desc_quant_key;'
        ),
        database=test_db,
    )

    # Step 8: Restore production dump data
    subprocess.run([
        _PG_RESTORE,
        '--data-only',
        '--schema=quantdb',
        '--no-owner',
        '--no-privileges',
        '--disable-triggers',
        '-U', 'postgres',
        '-h', 'localhost',
        '-p', '5432',
        '-d', test_db,
        str(_PROD_DUMP),
    ], check=True, capture_output=True, text=True)

    # Step 9: Deduplicate and restore unique constraints
    _psql(
        sql=(
            'DELETE FROM quantdb.values_cat a USING quantdb.values_cat b'
            '  WHERE a.id > b.id'
            '  AND a.object = b.object'
            '  AND a.instance = b.instance'
            '  AND a.desc_cat = b.desc_cat;'
            ' DELETE FROM quantdb.values_quant a'
            '  USING quantdb.values_quant b'
            '  WHERE a.id > b.id'
            '  AND a.object = b.object'
            '  AND a.instance = b.instance'
            '  AND a.desc_quant = b.desc_quant;'
            ' ALTER TABLE quantdb.values_cat'
            '  ADD CONSTRAINT values_cat_object_instance_desc_cat_key'
            '  UNIQUE (object, instance, desc_cat);'
            ' ALTER TABLE quantdb.values_quant'
            '  ADD CONSTRAINT'
            '  values_quant_object_instance_desc_quant_key'
            '  UNIQUE (object, instance, desc_quant);'
        ),
        database=test_db,
    )
