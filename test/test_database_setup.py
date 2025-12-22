"""
Test database setup and table creation.

This test module focuses solely on verifying that:
1. The test database can be created using the dbsetup script
2. The expected tables are present in the database
3. The database connection works properly

No other functionality is tested - this is just for basic database setup verification.
"""

import pytest
from sqlalchemy import text


class TestDatabaseSetup:
    """Test the basic database setup and table creation."""

    def test_database_connection(self, test_session):
        """Test that we can connect to the test database."""
        # Try a simple query to verify the connection works
        result = test_session.execute(text('SELECT 1 as test_value'))
        row = result.fetchone()
        assert row[0] == 1, 'Basic database connection failed'

    def test_tables_created(self, verify_database_tables):
        """Test that the expected core tables were created."""
        tables = verify_database_tables

        # Verify we have tables (the list should not be empty)
        assert len(tables) > 0, 'No tables found in the database'

        # Check for some core tables that should exist based on sql/tables.sql
        expected_core_tables = [
            'objects',
            'units',
            'aspects',
            'descriptors_inst',
            'descriptors_cat',
            'descriptors_quant',
            'values_inst',
            'values_cat',
            'values_quant',
            'addresses',
            'controlled_terms',
        ]

        missing_tables = []
        for expected_table in expected_core_tables:
            if expected_table not in tables:
                missing_tables.append(expected_table)

        assert len(missing_tables) == 0, f'Missing expected tables: {missing_tables}'

        print(f'✓ All {len(expected_core_tables)} core tables found in database')

    def test_database_schema_info(self, test_session):
        """Test that we can query basic schema information."""
        # Check that we can query table information in both schemas
        result = test_session.execute(
            text(
                """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_schema IN ('quantdb', 'public')
        """
            )
        )

        table_count = result.fetchone()[0]
        assert table_count > 0, 'No tables found in quantdb or public schemas'

        print(f'✓ Found {table_count} tables in quantdb and public schemas')

    def test_database_functions_created(self, test_session):
        """Test that database functions were created."""
        # Check for some of the custom functions from tables.sql in both schemas
        result = test_session.execute(
            text(
                """
            SELECT COUNT(*) as function_count
            FROM information_schema.routines
            WHERE routine_schema IN ('quantdb', 'public')
            AND routine_type = 'FUNCTION'
        """
            )
        )

        function_count = result.fetchone()[0]
        # We expect several functions to be created based on tables.sql
        assert function_count > 0, 'No custom functions found in database'

        print(f'✓ Found {function_count} custom functions in database')

    def test_database_enums_created(self, test_session):
        """Test that custom enum types were created."""
        result = test_session.execute(
            text(
                """
            SELECT COUNT(*) as enum_count
            FROM pg_type
            WHERE typtype = 'e'
        """
            )
        )

        enum_count = result.fetchone()[0]
        # We expect several enum types based on tables.sql (remote_id_type, instance_type, etc.)
        assert enum_count > 0, 'No custom enum types found in database'

        print(f'✓ Found {enum_count} custom enum types in database')
