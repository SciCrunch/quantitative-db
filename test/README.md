# Test Database Setup

This directory contains pytest setup for creating and verifying a local test PostgreSQL database using the `dbsetup` script.

## Purpose

This test setup is focused **solely** on:
1. Creating a test PostgreSQL database using the `bin/dbsetup` script
2. Verifying that the expected tables were created
3. Ensuring basic database connectivity works

**No other functionality is tested** - this is just for basic database setup verification.

## Prerequisites

1. **PostgreSQL server** must be running locally on port 5432 (or configured port)
2. **postgres superuser** must be available for database creation
3. **Python dependencies** must be installed (see `pyproject.toml`)

## Configuration

The test database configuration is **hardcoded** to always use a local PostgreSQL instance:
- Database: `quantdb_test` (can be overridden by `QUANTDB_TEST_DB_DATABASE`)
- Host: `localhost` (**ALWAYS localhost for testing - ignores all other config**)
- Port: `5432` (**ALWAYS 5432 for testing**)
- User: `quantdb-test-admin` (**ALWAYS this user for testing**)
- Password: `tom-is-cool` (**hardcoded for test database**)

**Important**: Testing will NEVER use remote databases (like AWS RDS). All test database connections are forced to use localhost regardless of environment variables or configuration files.

**Note**: Tables are created in the `quantdb` schema, not the `public` schema. The database users are configured with `search_path = quantdb, public` which makes `quantdb` the default schema for table creation.

## Running Tests

### Run all database setup tests:
```bash
pytest test/test_database_setup.py -v
```

### Run with more detailed output:
```bash
pytest test/test_database_setup.py -v -s
```

### Run only the table creation test:
```bash
pytest test/test_database_setup.py::TestDatabaseSetup::test_tables_created -v
```

## What the Tests Do

1. **`test_database_connection`**: Verifies basic database connectivity
2. **`test_tables_created`**: Checks that core tables (objects, units, aspects, etc.) exist in the `quantdb` schema
3. **`test_database_schema_info`**: Queries schema information from both `quantdb` and `public` schemas
4. **`test_database_functions_created`**: Verifies custom functions were created in the `quantdb` schema
5. **`test_database_enums_created`**: Checks that custom enum types exist

## Test Flow

1. The `setup_test_database` fixture runs the `bin/dbsetup` script
2. The `test_session` fixture creates a database connection
3. The `verify_database_tables` fixture queries and lists all tables
4. Individual tests verify different aspects of the database setup

## Troubleshooting

- **Connection errors**: Check that PostgreSQL is running and accessible
- **Permission errors**: Ensure the postgres user has proper permissions
- **Script errors**: Check that `bin/dbsetup` is executable and all SQL files exist
- **Timeout errors**: Database creation is taking longer than 2 minutes

## Expected Tables

The tests verify these core tables exist:
- `objects` - Main object table
- `units` - Unit definitions
- `aspects` - Aspect definitions
- `descriptors_inst` - Instance descriptors
- `descriptors_cat` - Categorical descriptors
- `descriptors_quant` - Quantitative descriptors
- `values_inst` - Instance values
- `values_cat` - Categorical values
- `values_quant` - Quantitative values
- `addresses` - Address mappings
- `controlled_terms` - Controlled vocabulary
