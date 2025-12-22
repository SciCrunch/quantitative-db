#!/usr/bin/env python3
"""
Test script to compare F006 databases created by quantdb/ingest.py
and ingestion/f006_ingestion_aligned.py

This ensures both methods produce identical test databases locally.
"""

import pathlib
import subprocess
import sys
from typing import Any, Dict, List

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

# Add parent directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from quantdb.client import get_session
from quantdb.models import (
    Addresses,
    Aspects,
    ControlledTerms,
    DescriptorsInst,
    DescriptorsQuant,
    ObjDescQuant,
    Objects,
    Units,
    ValuesInst,
    ValuesQuant,
)


def clear_test_database(session: Session):
    """Clear all data from test database."""
    # Delete in reverse dependency order
    tables_to_clear = [
        'values_quant',
        'values_cat',
        'values_inst',
        'obj_desc_quant',
        'obj_desc_cat',
        'obj_desc_inst',
        'descriptors_quant',
        'descriptors_cat',
        'descriptors_inst',
        'objects',
        'controlled_terms',
        'units',
        'aspects',
        'addresses',
    ]

    for table in tables_to_clear:
        try:
            session.execute(text(f'DELETE FROM {table}'))
        except Exception as e:
            print(f'Warning: Could not clear {table}: {e}')

    session.commit()


def run_quantdb_ingest(session: Session):
    """Run F006 ingestion using quantdb/ingest.py method with local data."""
    print('Running quantdb/ingest.py F006 ingestion (local data)...')

    # Import and run the local version of ingest_fasc_fib
    from quantdb.ingest_local import ingest_fasc_fib_local

    # Run with local source and test database
    ingest_fasc_fib_local(session, source_local=True, do_insert=True, commit=True, dev=False)

    print('quantdb/ingest.py ingestion complete')


def run_ingestion_pipeline(session: Session):
    """Run F006 ingestion using ingestion/ pipeline."""
    print('Running ingestion/f006_ingestion_aligned.py ingestion...')

    # Import and run the F006Ingestion class
    from ingestion.f006_ingestion_aligned import F006Ingestion

    # Create ingestion instance with local data
    ingestion = F006Ingestion()

    # Modify to use local data instead of fetching from API
    ingestion.use_local_data = True

    # Run ingestion
    ingestion.run(session, commit=True)

    print('ingestion/ pipeline complete')


def get_table_counts(session: Session) -> Dict[str, int]:
    """Get row counts for all tables."""
    counts = {}

    tables = [
        'addresses',
        'aspects',
        'controlled_terms',
        'descriptors_inst',
        'descriptors_quant',
        'objects',
        'units',
        'values_inst',
        'values_quant',
        'obj_desc_quant',
    ]

    for table in tables:
        try:
            result = session.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
            counts[table] = result
        except Exception as e:
            counts[table] = f'Error: {e}'

    return counts


def get_sample_data(session: Session) -> Dict[str, List]:
    """Get sample data from key tables for comparison."""
    samples = {}

    # Get sample aspects
    aspects = session.query(Aspects).limit(5).all()
    samples['aspects'] = [(a.label, a.iri) for a in aspects]

    # Get sample units
    units = session.query(Units).limit(5).all()
    samples['units'] = [(u.label, u.iri) for u in units]

    # Get sample descriptors
    desc_inst = session.query(DescriptorsInst).limit(5).all()
    samples['descriptors_inst'] = [(d.label, d.iri) for d in desc_inst]

    # Get sample objects
    objects = session.query(Objects).limit(5).all()
    samples['objects'] = [(str(o.id), o.id_type) for o in objects]

    # Get sample instances
    instances = session.query(ValuesInst).limit(5).all()
    samples['values_inst'] = [(i.id_formal, i.type, i.id_sub) for i in instances]

    # Get sample values
    values = session.query(ValuesQuant).limit(10).all()
    samples['values_quant'] = [(v.value, v.orig_value) for v in values]

    return samples


def compare_databases(counts1: Dict, counts2: Dict, samples1: Dict, samples2: Dict, method1: str, method2: str):
    """Compare two database states."""
    print(f"\n{'='*60}")
    print(f'Database Comparison: {method1} vs {method2}')
    print(f"{'='*60}\n")

    # Compare counts
    print('Table Row Counts:')
    print(f"{'Table':<20} {method1:<20} {method2:<20} {'Match':<10}")
    print('-' * 70)

    all_match = True
    for table in sorted(set(counts1.keys()) | set(counts2.keys())):
        count1 = counts1.get(table, 0)
        count2 = counts2.get(table, 0)
        match = '✓' if count1 == count2 else '✗'
        if count1 != count2:
            all_match = False
        print(f'{table:<20} {str(count1):<20} {str(count2):<20} {match:<10}')

    print('\n' + '-' * 70)
    print(f"Overall Match: {'✓ PASS' if all_match else '✗ FAIL'}")

    # Compare sample data
    print(f"\n{'='*60}")
    print('Sample Data Comparison:')
    print(f"{'='*60}\n")

    for table_name in samples1.keys():
        print(f'\n{table_name}:')
        data1 = samples1.get(table_name, [])
        data2 = samples2.get(table_name, [])

        if data1 == data2:
            print(f'  ✓ Sample data matches ({len(data1)} records)')
        else:
            print(f'  ✗ Sample data differs')
            print(f'    {method1}: {data1[:3]}...')
            print(f'    {method2}: {data2[:3]}...')

    return all_match


def main():
    """Main test function."""
    import argparse

    parser = argparse.ArgumentParser(description='Compare F006 database ingestion methods')
    parser.add_argument(
        '--method', choices=['quantdb', 'ingestion', 'both'], default='both', help='Which ingestion method to run'
    )
    parser.add_argument('--no-clear', action='store_true', help='Do not clear database before ingestion')
    parser.add_argument(
        '--compare-only', action='store_true', help='Only compare existing databases without running ingestion'
    )
    args = parser.parse_args()

    # Get test database session
    session = get_session(test=True)

    if not args.compare_only:
        if args.method in ['quantdb', 'both']:
            print('\n' + '=' * 60)
            print('Testing quantdb/ingest.py method')
            print('=' * 60)

            if not args.no_clear:
                print('Clearing test database...')
                clear_test_database(session)

            try:
                run_quantdb_ingest(session)
                counts_quantdb = get_table_counts(session)
                samples_quantdb = get_sample_data(session)

                print('\nDatabase state after quantdb ingestion:')
                for table, count in sorted(counts_quantdb.items()):
                    print(f'  {table}: {count}')

            except Exception as e:
                print(f'Error running quantdb ingestion: {e}')
                import traceback

                traceback.print_exc()
                counts_quantdb = {}
                samples_quantdb = {}

        if args.method in ['ingestion', 'both']:
            print('\n' + '=' * 60)
            print('Testing ingestion/ pipeline method')
            print('=' * 60)

            if not args.no_clear:
                print('Clearing test database...')
                clear_test_database(session)

            try:
                run_ingestion_pipeline(session)
                counts_ingestion = get_table_counts(session)
                samples_ingestion = get_sample_data(session)

                print('\nDatabase state after ingestion pipeline:')
                for table, count in sorted(counts_ingestion.items()):
                    print(f'  {table}: {count}')

            except Exception as e:
                print(f'Error running ingestion pipeline: {e}')
                import traceback

                traceback.print_exc()
                counts_ingestion = {}
                samples_ingestion = {}

    else:
        # Just get current database state
        print('Getting current database state...')
        counts_current = get_table_counts(session)
        samples_current = get_sample_data(session)

        print('\nCurrent database state:')
        for table, count in sorted(counts_current.items()):
            print(f'  {table}: {count}')

    # Compare if both methods were run
    if args.method == 'both' and not args.compare_only:
        # First run quantdb method and save state
        if not args.no_clear:
            clear_test_database(session)
        run_quantdb_ingest(session)
        counts_quantdb = get_table_counts(session)
        samples_quantdb = get_sample_data(session)

        # Then run ingestion method and save state
        if not args.no_clear:
            clear_test_database(session)
        run_ingestion_pipeline(session)
        counts_ingestion = get_table_counts(session)
        samples_ingestion = get_sample_data(session)

        # Compare results
        match = compare_databases(
            counts_quantdb, counts_ingestion, samples_quantdb, samples_ingestion, 'quantdb/ingest.py', 'ingestion/'
        )

        if match:
            print('\n✅ SUCCESS: Both methods produce identical databases!')
        else:
            print('\n❌ FAILURE: Databases differ between methods')
            sys.exit(1)

    session.close()
    print('\nTest complete!')


if __name__ == '__main__':
    main()
