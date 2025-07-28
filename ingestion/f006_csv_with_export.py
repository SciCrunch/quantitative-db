#!/usr/bin/env python3
"""
Enhanced F006 CSV ingestion that:
1. Drops and recreates the test database
2. Ingests F006 data including CSV files
3. Exports all tables to CSV files for debugging
"""

import csv
import json
import pathlib
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine, inspect, text

# Import everything from f006_csv.py instead of f006.py
from ingestion.f006_csv import *
from quantdb.client import get_session
from quantdb.config import auth
from quantdb.models import (
    Addresses,
    Aspects,
    Base,
    ControlledTerms,
    DescriptorsCat,
    DescriptorsInst,
    DescriptorsQuant,
    ObjDescCat,
    ObjDescInst,
    ObjDescQuant,
    Objects,
    Units,
    ValuesCat,
    ValuesInst,
    ValuesQuant,
)
from quantdb.utils import dbUri


# Copy the export functions from f006_with_export.py
def drop_and_create_database(engine):
    """Drop all tables and recreate them."""
    print('\n=== Dropping existing tables ===')

    # Get the connection URL parts
    url = engine.url
    database = url.database

    # Connect to postgres database to drop/create the target database
    postgres_url = url.set(database='postgres')
    postgres_engine = sqlalchemy.create_engine(postgres_url, isolation_level='AUTOCOMMIT')

    with postgres_engine.connect() as conn:
        # Check if database exists
        exists = conn.execute(
            text('SELECT 1 FROM pg_database WHERE datname = :dbname'), {'dbname': database}
        ).fetchone()

        if exists:
            # Terminate existing connections
            conn.execute(
                text(
                    f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{database}'
                AND pid <> pg_backend_pid()
            """
                )
            )

            # Drop database
            print(f'Dropping database: {database}')
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))

        # Create database
        print(f'Creating database: {database}')
        conn.execute(text(f'CREATE DATABASE "{database}"'))

    postgres_engine.dispose()

    # Now create all tables
    print('\n=== Creating tables ===')
    Base.metadata.create_all(engine)
    print('✓ All tables created')


def export_table_to_csv(session, table_class, output_dir: pathlib.Path):
    """Export a single table to CSV."""
    table_name = table_class.__tablename__
    output_file = output_dir / f'{table_name}.csv'

    # Query all records
    records = session.query(table_class).all()

    if not records:
        print(f'  - {table_name}: No records to export')
        return

    # Get column names
    columns = [column.name for column in inspect(table_class).columns]

    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()

        for record in records:
            row_dict = {}
            for col in columns:
                value = getattr(record, col)
                # Handle special types
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                elif isinstance(value, uuid.UUID):
                    value = str(value)
                elif isinstance(value, datetime):
                    value = value.isoformat()
                row_dict[col] = value
            writer.writerow(row_dict)

    print(f'  ✓ {table_name}: {len(records)} records exported to {output_file.name}')


def export_all_tables_to_csv(session, output_dir: pathlib.Path):
    """Export all database tables to CSV files."""
    print(f'\n=== Exporting database to CSV files in {output_dir} ===')

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # List of all model classes to export
    table_classes = [
        # Root tables
        Addresses,
        Aspects,
        Units,
        ControlledTerms,
        DescriptorsInst,
        # Intermediate tables
        DescriptorsCat,
        DescriptorsQuant,
        # Core tables
        Objects,
        ValuesInst,
        # Mapping tables
        ObjDescInst,
        ObjDescCat,
        ObjDescQuant,
        # Value tables
        ValuesCat,
        ValuesQuant,
    ]

    # Export each table
    table_summary = []
    for table_class in table_classes:
        try:
            export_table_to_csv(session, table_class, output_dir)
            count = session.query(table_class).count()
            table_summary.append(
                {
                    'table': table_class.__tablename__,
                    'record_count': count,
                    'category': get_table_category(table_class.__tablename__),
                }
            )
        except Exception as e:
            print(f'  ✗ Error exporting {table_class.__tablename__}: {e}')

    # Create a table summary CSV
    if table_summary:
        summary_df = pd.DataFrame(table_summary)
        summary_df = summary_df.sort_values(['category', 'table'])
        summary_df.to_csv(output_dir / '_table_summary.csv', index=False)
        print(f'  ✓ Table summary exported to _table_summary.csv')


def get_table_category(table_name):
    """Categorize tables for better organization."""
    if table_name in ['addresses', 'aspects', 'units', 'controlled_terms', 'descriptors_inst']:
        return '1_root_tables'
    elif table_name in ['descriptors_cat', 'descriptors_quant']:
        return '2_descriptor_tables'
    elif table_name in ['objects', 'values_inst']:
        return '3_core_tables'
    elif table_name.startswith('obj_desc'):
        return '4_mapping_tables'
    elif table_name.startswith('values_'):
        return '5_value_tables'
    else:
        return '6_other_tables'


def run_f006_csv_with_export(test=True, csv_limit=10):
    """Run F006 CSV ingestion with database reset and CSV export."""

    # Override the CSV limit
    global CSV_LIMIT
    CSV_LIMIT = csv_limit

    # Set up timestamp for output directory
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = pathlib.Path(f'f006_csv_debug_{timestamp}')

    print(f'Starting F006 CSV ingestion with export at {timestamp}')
    print(f'CSV processing limit: {CSV_LIMIT}')

    # Create engine
    if test:
        dbkwargs = {
            'dbuser': 'quantdb-test-admin',
            'host': 'localhost',
            'port': 5432,
            'database': 'quantdb_test',
            'password': 'tom-is-cool',
        }
    else:
        dbkwargs = {k: auth.get(f'db-{k}') for k in ('user', 'host', 'port', 'database')}
        dbkwargs['dbuser'] = dbkwargs.pop('user')

    engine = create_engine(dbUri(**dbkwargs))

    # Drop and recreate database
    if test:
        drop_and_create_database(engine)

    # Get a new session
    session = get_session(echo=False, test=test)

    try:
        # Load metadata
        metadata = load_path_metadata()
        print(f'Loaded metadata with {len(metadata["data"])} items')

        # Count file types
        jpx_count = sum(1 for item in metadata['data'] if item.get('mimetype') == 'image/jpx')
        csv_count = sum(1 for item in metadata['data'] if item.get('mimetype') == 'text/csv')
        print(f'Found {jpx_count} JPX files and {csv_count} CSV files')

        # Create basic components
        components = create_basic_descriptors(session)

        # Ingest objects table
        dataset_obj, package_objects = ingest_objects_table(session, metadata, components)

        # Ingest instances table
        instances = ingest_instances_table(session, metadata, components, dataset_obj)

        # Ingest descriptor relationships and values
        ingest_descriptors_and_values(session, metadata, components, dataset_obj, package_objects, instances)

        # Commit all changes
        session.commit()
        print('\n=== Ingestion Complete ===')

        # Export all tables to CSV
        export_all_tables_to_csv(session, output_dir)

        # Create a detailed summary file
        summary_file = output_dir / 'summary.txt'
        with open(summary_file, 'w') as f:
            f.write(f'F006 CSV Dataset Ingestion Summary\n')
            f.write(f'==================================\n')
            f.write(f'Timestamp: {timestamp}\n')
            f.write(f'Dataset UUID: {DATASET_UUID}\n')
            f.write(f"Database: {'quantdb_test' if test else 'quantdb'}\n")
            f.write(f'CSV Limit: {CSV_LIMIT}\n')

            # Get additional statistics from the database
            total_files = session.query(Objects).filter_by(id_type='package').count()

            subjects = session.query(ValuesInst).filter_by(type='subject').count()
            samples = session.query(ValuesInst).filter_by(type='sample').count()

            # Count unique descriptors used
            unique_desc_inst = session.query(DescriptorsInst).count()
            unique_desc_cat = session.query(DescriptorsCat).count()
            unique_desc_quant = session.query(DescriptorsQuant).count()

            f.write(f'\n=== Database Contents ===\n')
            f.write(f'Total Package Objects: {total_files}\n')
            f.write(f"  - JPX files: {len(package_objects.get('jpx', []))}\n")
            f.write(f"  - CSV files: {len(package_objects.get('csv', []))}\n")

            f.write(f'\n=== Biological Entities ===\n')
            f.write(f'Subjects: {subjects}\n')
            f.write(f'Samples: {samples}\n')

            # Get value counts
            cat_values = session.query(ValuesCat).count()
            quant_values = session.query(ValuesQuant).count()

            f.write(f'\n=== Values ===\n')
            f.write(f'Categorical values: {cat_values}\n')
            f.write(f'Quantitative values: {quant_values}\n')

            # List sample IDs
            sample_records = session.query(ValuesInst).filter_by(type='sample').order_by(ValuesInst.id_sam).all()
            if sample_records:
                f.write(f'\nSample IDs:\n')
                for sample in sample_records[:10]:  # Show first 10
                    f.write(f'  - {sample.id_sam}\n')
                if len(sample_records) > 10:
                    f.write(f'  ... and {len(sample_records) - 10} more\n')

            f.write(f'\n=== Schema Components ===\n')
            f.write(f'Instance Descriptors: {unique_desc_inst}\n')
            f.write(f'Categorical Descriptors: {unique_desc_cat}\n')
            f.write(f'Quantitative Descriptors: {unique_desc_quant}\n')
            f.write(f'Aspects: {session.query(Aspects).count()}\n')
            f.write(f'Units: {session.query(Units).count()}\n')
            f.write(f'Controlled Terms: {session.query(ControlledTerms).count()}\n')
            f.write(f'Address Types: {session.query(Addresses).count()}\n')

            # Add measurement summary
            f.write(f'\n=== Quantitative Measurements ===\n')
            # Query for unique descriptors with their counts
            from sqlalchemy import func

            quant_summary = (
                session.query(
                    DescriptorsQuant.label.label('desc_label'),
                    Aspects.label.label('aspect_label'),
                    Units.label.label('unit_label'),
                    func.count(ValuesQuant.id).label('count'),
                )
                .select_from(ValuesQuant)
                .join(DescriptorsQuant, ValuesQuant.desc_quant == DescriptorsQuant.id)
                .join(Aspects, DescriptorsQuant.aspect == Aspects.id)
                .join(Units, DescriptorsQuant.unit == Units.id)
                .group_by(DescriptorsQuant.label, Aspects.label, Units.label)
                .all()
            )

            for row in quant_summary:
                f.write(f'  - {row.desc_label}: {row.count} measurements ({row.aspect_label} in {row.unit_label})\n')

        print(f'\n✓ Summary written to {summary_file}')

        # Also export some useful queries
        print('\n=== Exporting analysis queries ===')

        # Query 1: All quantitative values with their descriptors
        query1 = """
        SELECT
            vq.id,
            vq.value,
            vq.orig_value,
            vq.orig_units,
            dq.label as descriptor_label,
            a.label as aspect,
            u.label as unit,
            di.label as domain,
            o.id_type as object_type,
            o.id_file as file_id,
            vi.id_sam as sample_id
        FROM values_quant vq
        JOIN descriptors_quant dq ON vq.desc_quant = dq.id
        JOIN aspects a ON dq.aspect = a.id
        JOIN units u ON dq.unit = u.id
        JOIN descriptors_inst di ON dq.domain = di.id
        JOIN objects o ON vq.object = o.id
        JOIN values_inst vi ON vq.instance = vi.id
        ORDER BY vi.id_sam, dq.label
        """

        df1 = pd.read_sql(query1, session.bind)
        df1.to_csv(output_dir / 'quantitative_values_analysis.csv', index=False)
        print(f'  ✓ Exported {len(df1)} quantitative values with details')

        # Query 2: All categorical values with their descriptors
        query2 = """
        SELECT
            vc.id,
            ct.label as value,
            vc.value_open,
            dc.label as descriptor_label,
            di.label as domain,
            o.id_type as object_type,
            o.id_file as file_id,
            vi.id_sam as sample_id
        FROM values_cat vc
        LEFT JOIN controlled_terms ct ON vc.value_controlled = ct.id
        JOIN descriptors_cat dc ON vc.desc_cat = dc.id
        JOIN descriptors_inst di ON dc.domain = di.id
        JOIN objects o ON vc.object = o.id
        JOIN values_inst vi ON vc.instance = vi.id
        ORDER BY vi.id_sam, dc.label
        """

        df2 = pd.read_sql(query2, session.bind)
        df2.to_csv(output_dir / 'categorical_values_analysis.csv', index=False)
        print(f'  ✓ Exported {len(df2)} categorical values with details')

        print(f'\n✓ All exports completed! Check directory: {output_dir}')

    except Exception as e:
        session.rollback()
        print(f'\n✗ Error during ingestion: {e}')
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == '__main__':
    # Run with test database and process 10 CSV files
    run_f006_csv_with_export(test=True, csv_limit=10)
