#!/usr/bin/env python3
"""
Simple test to ensure F006 ingestion methods are compatible.
Tests that both quantdb/ingest.py and ingestion/ pipeline can run successfully.
"""

import pathlib
import sys

# Add parent directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from sqlalchemy import text

from quantdb.client import get_session


def test_quantdb_ingest():
    """Test quantdb/ingest.py method."""
    print('\nTesting quantdb/ingest.py method...')

    from quantdb.ingest import ingest_fasc_fib

    # Get test session
    session = get_session(test=True)

    try:
        # Clear test data
        session.execute(text('DELETE FROM values_quant'))
        session.execute(text('DELETE FROM values_inst'))
        session.execute(text("DELETE FROM objects WHERE id_type = 'dataset'"))
        session.commit()

        # Run ingestion (will fetch from API)
        ingest_fasc_fib(session, source_local=False, do_insert=True, commit=True, dev=False)

        # Check results
        count_objects = session.execute(text('SELECT COUNT(*) FROM objects')).scalar()
        count_instances = session.execute(text('SELECT COUNT(*) FROM values_inst')).scalar()
        count_values = session.execute(text('SELECT COUNT(*) FROM values_quant')).scalar()

        print(f'  Objects created: {count_objects}')
        print(f'  Instances created: {count_instances}')
        print(f'  Values created: {count_values}')

        session.close()
        return True

    except Exception as e:
        print(f'  ERROR: {e}')
        session.rollback()
        session.close()
        return False


def test_ingestion_pipeline():
    """Test ingestion/ pipeline method."""
    print('\nTesting ingestion/ pipeline method...')

    from ingestion.f006_ingestion_aligned import F006Ingestion

    # Get test session
    session = get_session(test=True)

    try:
        # Clear test data
        session.execute(text('DELETE FROM values_quant'))
        session.execute(text('DELETE FROM values_inst'))
        session.execute(text("DELETE FROM objects WHERE id_type = 'dataset'"))
        session.commit()

        # Run ingestion
        ingestion = F006Ingestion()
        ingestion.use_local_data = True  # Use local data
        ingestion.run(session, commit=True)

        # Check results
        count_objects = session.execute(text('SELECT COUNT(*) FROM objects')).scalar()
        count_instances = session.execute(text('SELECT COUNT(*) FROM values_inst')).scalar()
        count_values = session.execute(text('SELECT COUNT(*) FROM values_quant')).scalar()

        print(f'  Objects created: {count_objects}')
        print(f'  Instances created: {count_instances}')
        print(f'  Values created: {count_values}')

        session.close()
        return True

    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback

        traceback.print_exc()
        session.rollback()
        session.close()
        return False


def main():
    """Main test function."""
    print('=' * 60)
    print('F006 Ingestion Methods Compatibility Test')
    print('=' * 60)

    # Test quantdb method
    quantdb_success = test_quantdb_ingest()

    # Test ingestion pipeline
    ingestion_success = test_ingestion_pipeline()

    # Report results
    print('\n' + '=' * 60)
    print('Test Results:')
    print('=' * 60)
    print(f"quantdb/ingest.py:     {'✓ PASS' if quantdb_success else '✗ FAIL'}")
    print(f"ingestion/ pipeline:   {'✓ PASS' if ingestion_success else '✗ FAIL'}")

    if quantdb_success and ingestion_success:
        print('\n✅ SUCCESS: Both methods work!')
        print('\nNote: The exact data may differ if they use different data sources.')
        print('The important thing is that both can successfully ingest F006 data.')
        return 0
    else:
        print('\n❌ FAILURE: One or both methods failed')
        return 1


if __name__ == '__main__':
    sys.exit(main())
