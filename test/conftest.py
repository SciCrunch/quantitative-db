import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from quantdb.client import get_session
from quantdb.config import auth


@pytest.fixture(scope='session')
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope='session')
def test_database_config():
    """Get test database configuration."""
    config = {
        'user': 'quantdb-test-admin',
        'host': 'localhost',  # ALWAYS use localhost for testing, never remote
        'port': 5432,
        'database': auth.get('test-db-database') or 'quantdb_test',
    }
    return config


@pytest.fixture(scope='session')
def setup_test_database(project_root, test_database_config):
    """
    Set up the test database using the dbsetup script.
    This fixture runs once per test session and ALWAYS:
    1. Deletes the existing test database (if it exists)
    2. Creates a fresh test database with all tables

    This ensures a clean state for every test run.
    """
    print(f'\n=== Setting up test database ===')
    print(f"Database: {test_database_config['database']}")
    print(f"Host: {test_database_config['host']}")
    print(f"Port: {test_database_config['port']}")
    print(f"User: {test_database_config['user']}")

    # Safety check: ONLY work with localhost
    if test_database_config['host'] != 'localhost':
        pytest.fail(f"Refusing to delete database on non-localhost host: {test_database_config['host']}")

    # Path to dbsetup script
    dbsetup_script = project_root / 'bin' / 'dbsetup'

    if not dbsetup_script.exists():
        pytest.fail(f'dbsetup script not found at: {dbsetup_script}')

    # Make sure the script is executable
    os.chmod(dbsetup_script, 0o755)

    print(f"Deleting and recreating test database: {test_database_config['database']}")

    # Always run dbsetup to ensure fresh database
    # The dbsetup script will handle dropping and recreating the database
    test_env = os.environ.copy()
    test_env['PGPASSWORD'] = 'postgres'  # Use postgres password for setup scripts

    # Run dbsetup with test database parameters
    cmd = [
        str(dbsetup_script),
        str(test_database_config['port']),
        test_database_config['database'],
        test_database_config['host'],
    ]

    print(f"Running command: {' '.join(cmd)}")

    try:
        # Run the dbsetup script with the password environment variable
        result = subprocess.run(
            cmd, cwd=project_root, capture_output=True, text=True, timeout=120, env=test_env
        )  # 2 minute timeout

        if result.returncode != 0:
            print(f'STDOUT: {result.stdout}')
            print(f'STDERR: {result.stderr}')
            pytest.fail(f'dbsetup failed with return code {result.returncode}')

        print(f'dbsetup completed successfully')
        print(f'STDOUT: {result.stdout}')

        # Verify the database was created by attempting a connection
        import psycopg2

        try:
            conn = psycopg2.connect(
                host=test_database_config['host'],
                port=test_database_config['port'],
                database=test_database_config['database'],
                user=test_database_config['user'],
                password='tom-is-cool',
            )
            conn.close()
            print('Database connection verification successful!')
        except Exception as e:
            pytest.fail(f'Failed to connect to newly created database: {e}')

        # Return the configuration for use by other fixtures
        return test_database_config

    except subprocess.TimeoutExpired:
        pytest.fail('dbsetup script timed out after 2 minutes')
    except Exception as e:
        pytest.fail(f'Failed to run dbsetup: {e}')


@pytest.fixture(scope='session')
def test_session(setup_test_database):
    """
    Get a SQLAlchemy session connected to the test database.
    Depends on setup_test_database to ensure the database is created first.
    """
    try:
        session = get_session(echo=False, test=True)
        yield session
        session.close()
    except Exception as e:
        pytest.fail(f'Failed to create test database session: {e}')


@pytest.fixture(scope='function')
def test_session_with_rollback(setup_test_database):
    """
    Get a fresh SQLAlchemy session for each test with automatic rollback.
    This ensures test isolation by rolling back all changes after each test.
    """
    try:
        session = get_session(echo=False, test=True)
        # Start a savepoint that will be rolled back after the test
        trans = session.begin()
        yield session
        # Always rollback the transaction to ensure test isolation
        if trans.is_active:
            trans.rollback()
        session.close()
    except Exception as e:
        # If there's an error, make sure we still close the session
        try:
            if 'session' in locals():
                session.close()
        except:
            pass
        pytest.fail(f'Failed to create test database session: {e}')


@pytest.fixture(scope='session')
def verify_database_tables(test_session):
    """
    Verify that the expected database tables were created.
    Returns a list of table names found in the database.
    """
    try:
        # Query for all tables in the quantdb and public schemas
        result = test_session.execute(
            text(
                """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('quantdb', 'public')
            ORDER BY table_schema, table_name
        """
            )
        )

        rows = result.fetchall()
        tables_by_schema = {}
        all_tables = []

        for schema, table in rows:
            if schema not in tables_by_schema:
                tables_by_schema[schema] = []
            tables_by_schema[schema].append(table)
            all_tables.append(table)

        print(f'\n=== Found {len(all_tables)} tables in test database ===')
        for schema, tables in tables_by_schema.items():
            print(f"Schema '{schema}': {len(tables)} tables")
            for table in tables:
                print(f'  - {table}')

        return all_tables

    except Exception as e:
        pytest.fail(f'Failed to query database tables: {e}')
