{
    'config-search-paths': [
        '{:user-config-path}/quantdb/config.yaml',
    ],
    'auth-variables': {
        # test-db
        'test-db-user': {'default': 'quantdb-test-user', 'environment-variables': 'QUANTDB_TEST_DB_USER'},
        'test-db-host': {'default': 'localhost', 'environment-variables': 'QUANTDB_TEST_DB_HOST'},
        'test-db-port': {'default': 5432, 'environment-variables': 'QUANTDB_TEST_DB_PORT'},
        'test-db-database': {
            # we DO set a default database for testing
            # so that it is present for reference
            'default': 'quantdb_test',
            'environment-variables': 'QUANTDB_TEST_DB_DATABASE QUANTDB_TEST_DATABASE',
        },
        # db
        'db-user': {'default': 'quantdb-user', 'environment-variables': 'QUANTDB_DB_USER'},
        'db-host': {'default': 'localhost', 'environment-variables': 'QUANTDB_DB_HOST'},
        'db-port': {'default': 5432, 'environment-variables': 'QUANTDB_DB_PORT'},
        'db-database': {
            # we don't set a default here to prevent
            # accidental operations on a default db
            'default': None,
            'environment-variables': 'QUANTDB_DB_DATABASE QUANTDB_DATABASE',
        },
    },
}
