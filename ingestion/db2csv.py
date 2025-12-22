#!/usr/bin/env python3
"""
Database to CSV Export

Exports all tables from the PostgreSQL database to CSV files.
Each table is exported as a separate CSV file in the output directory.
"""

import csv
import pathlib
import warnings
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import inspect
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import Session

# Suppress SQLAlchemy automap relationship warnings
warnings.filterwarnings('ignore', category=SAWarning)

from quantdb.automap_client import get_automap_session, get_insert_order


def get_table_columns(model) -> list:
    """Get column names for a model/table."""
    if hasattr(model, '__table__'):
        return [col.name for col in model.__table__.columns]
    elif hasattr(model, 'columns'):
        return [col.name for col in model.columns]
    return []


def export_table_to_csv(
    session: Session,
    model,
    table_name: str,
    output_dir: pathlib.Path,
) -> int:
    """
    Export a single table to CSV.

    Parameters
    ----------
    session : Session
        SQLAlchemy session.
    model : Any
        SQLAlchemy model class or table.
    table_name : str
        Name of the table.
    output_dir : Path
        Directory to write CSV files.

    Returns
    -------
    int
        Number of rows exported.
    """
    columns = get_table_columns(model)
    if not columns:
        return 0

    csv_path = output_dir / f'{table_name}.csv'

    if hasattr(model, '__table__'):
        rows = session.query(model).all()
        data = []
        for row in rows:
            data.append({col: getattr(row, col, None) for col in columns})
    else:
        result = session.execute(model.select())
        data = [dict(zip(columns, r)) for r in result]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)

    return len(data)


def export_database_to_csv(
    output_dir: Optional[pathlib.Path] = None,
    test: bool = True,
    tables: Optional[list] = None,
) -> Dict[str, int]:
    """
    Export all database tables to CSV files.

    Parameters
    ----------
    output_dir : Path, optional
        Directory to write CSV files. Defaults to timestamped directory.
    test : bool
        Use test database (default: True).
    tables : list, optional
        Specific tables to export. Exports all if not specified.

    Returns
    -------
    dict
        Dictionary mapping table names to row counts.
    """
    if output_dir is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = pathlib.Path(__file__).parent / f'db_export_{timestamp}'

    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session, models = get_automap_session(test=test)
    results = {}

    try:
        table_order = get_insert_order(models)

        seen_tables = set()
        export_list = []

        for table_name in table_order:
            if table_name not in seen_tables:
                seen_tables.add(table_name)
                export_list.append(table_name)

        for name, model in models.items():
            if name.startswith('t_'):
                clean_name = name[2:]
                if clean_name not in seen_tables:
                    seen_tables.add(clean_name)
                    export_list.append(clean_name)

        print(f'=== Database Export to CSV ===')
        print(f'Output directory: {output_dir}')
        print(f'Database: {"test" if test else "production"}')
        print(f'Tables to export: {len(export_list)}')
        print()

        for table_name in export_list:
            if tables and table_name not in tables:
                continue

            model = models.get(table_name) or models.get(f't_{table_name}')
            if model is None:
                continue

            try:
                row_count = export_table_to_csv(session, model, table_name, output_dir)
                results[table_name] = row_count
                print(f'  {table_name}: {row_count} rows')
            except Exception as e:
                print(f'  {table_name}: ERROR - {e}')
                results[table_name] = -1

        print()
        print(f'=== Export Complete ===')
        print(f'Total tables: {len(results)}')
        print(f'Total rows: {sum(c for c in results.values() if c > 0)}')

    finally:
        session.close()

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Export database tables to CSV')
    parser.add_argument(
        '-o',
        '--output',
        type=pathlib.Path,
        help='Output directory (default: timestamped directory)',
    )
    parser.add_argument(
        '--test',
        action='store_true',
        default=True,
        help='Use test database (default)',
    )
    parser.add_argument(
        '--prod',
        action='store_true',
        help='Use production database',
    )
    parser.add_argument(
        '-t',
        '--tables',
        nargs='+',
        help='Specific tables to export (default: all)',
    )
    args = parser.parse_args()

    export_database_to_csv(
        output_dir=args.output,
        test=not args.prod,
        tables=args.tables,
    )
