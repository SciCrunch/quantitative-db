#!/usr/bin/env python3
"""
Compare CSV exports from production and local databases.
This helps visualize differences between production and local ingestion.
"""

import argparse
import csv
import json
import pathlib
from typing import Dict, List, Set, Tuple

import pandas as pd


def compare_csv_files(prod_file: pathlib.Path, local_file: pathlib.Path) -> Dict:
    """Compare two CSV files and return differences."""

    # Read CSVs
    prod_df = pd.read_csv(prod_file)
    local_df = pd.read_csv(local_file)

    comparison = {
        'table': prod_file.stem,
        'prod_rows': len(prod_df),
        'local_rows': len(local_df),
        'row_diff': len(local_df) - len(prod_df),
        'prod_columns': list(prod_df.columns),
        'local_columns': list(local_df.columns),
        'missing_columns': list(set(prod_df.columns) - set(local_df.columns)),
        'extra_columns': list(set(local_df.columns) - set(prod_df.columns)),
    }

    # Sample data comparison (first few rows)
    if not prod_df.empty and not local_df.empty:
        # Find primary key or ID column
        id_col = None
        for col in ['id', 'uuid', 'remote_id']:
            if col in prod_df.columns and col in local_df.columns:
                id_col = col
                break

        if id_col:
            # Compare specific IDs
            prod_ids = set(prod_df[id_col].dropna().astype(str))
            local_ids = set(local_df[id_col].dropna().astype(str))

            comparison['ids_only_in_prod'] = len(prod_ids - local_ids)
            comparison['ids_only_in_local'] = len(local_ids - prod_ids)
            comparison['ids_in_both'] = len(prod_ids & local_ids)

    return comparison


def compare_directories(prod_dir: pathlib.Path, local_dir: pathlib.Path) -> None:
    """Compare all CSV files between production and local export directories."""

    print(f'\n{"="*60}')
    print('CSV Export Comparison')
    print(f'{"="*60}')
    print(f'Production: {prod_dir}')
    print(f'Local:      {local_dir}')
    print(f'{"="*60}\n')

    # Get all CSV files
    prod_csvs = {f.stem: f for f in prod_dir.glob('*.csv') if not f.stem.startswith('_')}
    local_csvs = {f.stem: f for f in local_dir.glob('*.csv') if not f.stem.startswith('_')}

    all_tables = sorted(set(prod_csvs.keys()) | set(local_csvs.keys()))

    comparisons = []

    for table in all_tables:
        if table not in prod_csvs:
            print(f'⚠ {table}: Only in local (not in production)')
            continue
        elif table not in local_csvs:
            print(f'⚠ {table}: Only in production (not in local)')
            continue

        # Compare the CSV files
        comp = compare_csv_files(prod_csvs[table], local_csvs[table])
        comparisons.append(comp)

        # Print summary for each table
        status = '✓' if comp['row_diff'] == 0 else '⚠'
        print(f'{status} {table}:')
        print(f'  Rows: prod={comp["prod_rows"]:,} local={comp["local_rows"]:,} diff={comp["row_diff"]:+,}')

        if comp['missing_columns']:
            print(f'  Missing columns: {comp["missing_columns"]}')
        if comp['extra_columns']:
            print(f'  Extra columns: {comp["extra_columns"]}')

        if 'ids_only_in_prod' in comp:
            print(
                f'  IDs: both={comp["ids_in_both"]:,} prod-only={comp["ids_only_in_prod"]:,} local-only={comp["ids_only_in_local"]:,}'
            )

    # Summary statistics
    print(f'\n{"="*60}')
    print('Summary')
    print(f'{"="*60}')

    total_prod_rows = sum(c['prod_rows'] for c in comparisons)
    total_local_rows = sum(c['local_rows'] for c in comparisons)

    print(f'Total rows: prod={total_prod_rows:,} local={total_local_rows:,}')
    print(f'Tables compared: {len(comparisons)}')

    # Tables with differences
    diffs = [c for c in comparisons if c['row_diff'] != 0]
    if diffs:
        print(f'\nTables with row differences: {len(diffs)}')
        for comp in sorted(diffs, key=lambda x: abs(x['row_diff']), reverse=True)[:10]:
            print(f'  {comp["table"]}: {comp["row_diff"]:+,} rows')

    # Save detailed comparison to JSON
    output_file = pathlib.Path('comparison_results.json')
    with open(output_file, 'w') as f:
        json.dump(
            {'production_dir': str(prod_dir), 'local_dir': str(local_dir), 'comparisons': comparisons}, f, indent=2
        )

    print(f'\n✓ Detailed comparison saved to: {output_file}')


def main():
    parser = argparse.ArgumentParser(description='Compare CSV exports from production and local databases')
    parser.add_argument('prod_dir', type=pathlib.Path, help='Production export directory (e.g., production_export_*)')
    parser.add_argument('local_dir', type=pathlib.Path, help='Local export directory (e.g., f006_export_*)')

    args = parser.parse_args()

    if not args.prod_dir.exists():
        print(f'Error: Production directory not found: {args.prod_dir}')
        exit(1)

    if not args.local_dir.exists():
        print(f'Error: Local directory not found: {args.local_dir}')
        exit(1)

    compare_directories(args.prod_dir, args.local_dir)


if __name__ == '__main__':
    main()
