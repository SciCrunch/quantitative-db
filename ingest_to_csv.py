#!/usr/bin/env python3
"""
Run quantdb.ingest or f006 ingestion and export the resulting data to CSV files for debugging.
This script wraps the ingest process and immediately exports all populated tables.
"""

import argparse
import os
import sys
from datetime import datetime

import pandas as pd
from sqlalchemy import inspect

from quantdb.client import get_session


def export_ingested_data(session, output_dir, run_timestamp, ingest_type='reva_ft'):
    """Export all tables with data to CSV files after ingestion."""

    # Create timestamped subdirectory
    timestamp_dir = os.path.join(output_dir, f'{ingest_type}_ingest_{run_timestamp}')
    os.makedirs(timestamp_dir, exist_ok=True)

    # Get the inspector to examine the database
    inspector = inspect(session.bind)

    # Get all table names
    table_names = inspector.get_table_names()
    print(f'\nFound {len(table_names)} tables in the database')
    print('=' * 60)

    # Track what we export
    exported_tables = []
    empty_tables = []

    # Export each table
    for table_name in sorted(table_names):
        try:
            # Query the table
            df = pd.read_sql_table(table_name, session.bind)

            if len(df) > 0:
                # Save to CSV
                output_file = os.path.join(timestamp_dir, f'{table_name}.csv')
                df.to_csv(output_file, index=False)
                exported_tables.append((table_name, len(df)))
                print(f'✓ Exported {table_name}: {len(df)} rows → {output_file}')
            else:
                empty_tables.append(table_name)

        except Exception as e:
            print(f'✗ Error exporting {table_name}: {e}')

    # Create summary file
    summary_file = os.path.join(timestamp_dir, '_ingest_summary.csv')
    summary_data = []

    for table_name in sorted(table_names):
        if any(t[0] == table_name for t in exported_tables):
            row_count = next(t[1] for t in exported_tables if t[0] == table_name)
        else:
            row_count = 0
        summary_data.append({'table': table_name, 'row_count': row_count})

    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(summary_file, index=False)

    # Also create a metadata file with ingestion details
    metadata_file = os.path.join(timestamp_dir, '_ingest_metadata.txt')
    with open(metadata_file, 'w') as f:
        f.write(f'Ingestion type: {ingest_type}\n')
        f.write(f'Ingestion timestamp: {run_timestamp}\n')
        f.write(f"Command line args: {' '.join(sys.argv)}\n")
        f.write(f'\nTables with data ({len(exported_tables)}):\n')
        for table_name, row_count in sorted(exported_tables):
            f.write(f'  - {table_name}: {row_count} rows\n')

        if empty_tables:
            f.write(f'\nEmpty tables ({len(empty_tables)}):\n')
            for table_name in sorted(empty_tables):
                f.write(f'  - {table_name}\n')

    print('=' * 60)
    print(f'Exported {len(exported_tables)} tables to: {timestamp_dir}')
    print(f'Summary saved to: {summary_file}')
    print(f'Metadata saved to: {metadata_file}')

    return timestamp_dir


def run_reva_ft_ingest(args):
    """Run the original REVA FT ingestion from quantdb.ingest."""
    from quantdb.ingest import main as ingest_main

    # Build argv for ingest.py
    ingest_argv = [args.path_or_id]
    if args.test:
        ingest_argv.append('--test')

    # Save original argv and replace with our args
    original_argv = sys.argv
    sys.argv = ['ingest.py'] + ingest_argv

    try:
        # Run the ingest
        print('\n' + '=' * 60)
        print('Running REVA FT ingest...')
        print('=' * 60)

        ingest_main()
    finally:
        # Restore original argv
        sys.argv = original_argv


def run_f006_ingest(args):
    """Run the F006 ingestion from ingestion.f006."""
    from ingestion.f006 import run_f006_ingestion

    print('\n' + '=' * 60)
    print('Running F006 ingest...')
    print('=' * 60)

    # Get session
    session = get_session(echo=False, test=args.test)

    try:
        # Run the F006 ingestion
        result = run_f006_ingestion(session, commit=args.commit)
        print('\n✓ F006 ingestion completed successfully!')
    finally:
        session.close()


def main():
    """Run ingest and export to CSV."""
    parser = argparse.ArgumentParser(
        description='Run quantdb ingest (REVA FT or F006) and export results to CSV files for debugging',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ingestion Types:
  reva_ft: Original multi-dataset REVA FT ingestion (default)
  f006:    F006 dataset ingestion using ORM approach

Examples:
  # Run REVA FT ingest on a local path and export to CSVs
  python ingest_to_csv.py /path/to/dataset

  # Run REVA FT ingest on remote dataset and export to CSVs
  python ingest_to_csv.py N:dataset:abc123

  # Run F006 ingestion and export to CSVs
  python ingest_to_csv.py --type f006

  # Export to custom directory
  python ingest_to_csv.py /path/to/dataset --output-dir my_debug_csvs

  # Use test database
  python ingest_to_csv.py /path/to/dataset --test

  # F006 with commit (actual data insertion)
  python ingest_to_csv.py --type f006 --commit
""",
    )

    # Add arguments
    parser.add_argument(
        'path_or_id', nargs='?', help='Path to local dataset or remote dataset ID (required for reva_ft)'
    )
    parser.add_argument(
        '--type', choices=['reva_ft', 'f006'], default='reva_ft', help='Type of ingestion to run (default: reva_ft)'
    )
    parser.add_argument(
        '--output-dir', default='debug_csvs', help='Directory to save CSV exports (default: debug_csvs)'
    )
    parser.add_argument('--test', action='store_true', help='Use test database instead of production')
    parser.add_argument('--no-export', action='store_true', help='Skip CSV export (just run ingest)')
    parser.add_argument(
        '--commit', action='store_true', help='For F006: commit the transaction (default: rollback/dry-run)'
    )

    args = parser.parse_args()

    # Validate arguments
    if args.type == 'reva_ft' and not args.path_or_id:
        parser.error('path_or_id is required for REVA FT ingestion')

    # Generate timestamp for this run
    run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if args.type == 'reva_ft':
        print(f'Starting REVA FT ingest process for: {args.path_or_id}')
    else:
        print(f'Starting F006 ingest process')
        print(f"Commit mode: {'Yes' if args.commit else 'No (dry run)'}")

    print(f"Using {'test' if args.test else 'production'} database")

    try:
        # Run the appropriate ingestion
        if args.type == 'reva_ft':
            run_reva_ft_ingest(args)
        else:  # f006
            run_f006_ingest(args)

        if not args.no_export:
            # Export the data to CSV
            print('\n' + '=' * 60)
            print('Exporting ingested data to CSV...')
            print('=' * 60)

            session = get_session(echo=False, test=args.test)
            try:
                export_dir = export_ingested_data(session, args.output_dir, run_timestamp, args.type)
                print(f'\n✓ Success! Data exported to: {export_dir}')
            finally:
                session.close()
        else:
            print('\n✓ Ingest completed (export skipped)')

    except Exception as e:
        print(f'\n✗ Error during ingest: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
