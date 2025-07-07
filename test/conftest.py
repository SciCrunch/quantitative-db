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
    This fixture runs once per test session.
    """
    print(f'\n=== Setting up test database ===')
    print(f"Database: {test_database_config['database']}")
    print(f"Host: {test_database_config['host']}")
    print(f"Port: {test_database_config['port']}")
    print(f"User: {test_database_config['user']}")

    # Path to dbsetup script
    dbsetup_script = project_root / 'bin' / 'dbsetup'

    if not dbsetup_script.exists():
        pytest.fail(f'dbsetup script not found at: {dbsetup_script}')

    # Make sure the script is executable
    os.chmod(dbsetup_script, 0o755)

    try:
        # Set up environment with hardcoded test password
        test_env = os.environ.copy()
        test_env['PGPASSWORD'] = 'tom-is-cool'  # Hardcoded test password

        # Run dbsetup with test database parameters
        cmd = [
            str(dbsetup_script),
            str(test_database_config['port']),
            test_database_config['database'],
            test_database_config['host'],
        ]

        print(f"Running command: {' '.join(cmd)}")
        print(f'Using hardcoded test password: tom-is-cool')

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
