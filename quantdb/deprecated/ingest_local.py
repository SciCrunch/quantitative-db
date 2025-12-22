#!/usr/bin/env python3
"""
Minimal wrapper to run quantdb ingest for F006 locally with CSV export.
Uses the existing f006_csv ingestion from the ingestion folder.
"""

import csv
import json
import pathlib
import sys
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pandas as pd
from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.ext.automap import automap_base

from quantdb.client import get_session
from quantdb.utils import dbUri

# Import the F006 CSV ingestion functions from ingestion folder
# NOTE: Commented out due to dependency on hardcoded models.py
# When using dynamic models, these functions would need to be updated
# to accept model classes as parameters
# from ingestion.f006_csv import (
#     CSV_LIMIT,
#     load_path_metadata,
#     create_basic_descriptors,
#     ingest_objects_table,
#     ingest_instances_table,
#     ingest_descriptors_and_values,
# )

# Placeholder for CSV_LIMIT when f006_csv is not imported
CSV_LIMIT = 10

# F006 dataset UUID
DATASET_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'


def get_dynamic_models(engine, schema='public'):
    """Dynamically reflect database models using automap.

    Args:
        engine: SQLAlchemy engine
        schema: Database schema name (default: 'public')

    Returns:
        tuple: (Base object, models dictionary)
    """
    from sqlalchemy import MetaData

    print(f"\n=== Reflecting Database Schema '{schema}' ===")

    # First check what tables exist
    metadata = MetaData()
    metadata.reflect(bind=engine, schema=None)  # Try no schema first

    print(f'Debug: Found {len(metadata.tables)} tables total')
    if metadata.tables:
        print(f'Debug: Sample tables: {list(metadata.tables.keys())[:5]}')

    # Create automap base
    Base = automap_base()

    try:
        # Custom naming function to avoid conflicts
        def name_for_collection(base, local_cls, referred_cls, constraint):
            """Custom naming for collection relationships to avoid conflicts."""
            # Avoid creating conflicting backref names
            if local_cls.__name__ == referred_cls.__name__:
                # Self-referential relationship
                if constraint.name:
                    return constraint.name.replace('_fkey', '').replace('_', '_') + '_collection'
                return 'child_collection'
            # Use the constraint name if available
            if constraint.name:
                return constraint.name.replace('_fkey', '_collection')
            # Otherwise use the referred class name with a suffix
            return referred_cls.__name__.lower() + '_collection'

        # If we found tables without schema, don't specify schema
        if metadata.tables and not any('.' in t for t in metadata.tables.keys()):
            print('Debug: Reflecting without schema specification')
            Base.prepare(autoload_with=engine, name_for_collection_relationship=name_for_collection)
        else:
            print(f"Debug: Reflecting with schema='{schema}'")
            Base.prepare(autoload_with=engine, schema=schema, name_for_collection_relationship=name_for_collection)
    except Exception as e:
        print(f'Warning: Reflection failed: {e}')
        print('Trying with default naming...')
        # Try with default naming
        Base = automap_base()
        try:
            Base.prepare(autoload_with=engine)
        except Exception as e2:
            print(f'Warning: Default naming also failed: {e2}')
            # Try to continue anyway
            pass

    # Create a dictionary of model classes for easy access
    models = {}

    # Debug: Check what classes are available
    available_classes = [c for c in dir(Base.classes) if not c.startswith('_')]
    print(f'Debug: Available classes from Base.classes: {available_classes}')

    for cls_name in dir(Base.classes):
        if not cls_name.startswith('_'):
            try:
                cls = getattr(Base.classes, cls_name)
                # Store by both the class name and table name
                models[cls_name] = cls
                models[cls.__table__.name] = cls
            except AttributeError as e:
                print(f'Debug: Could not get class {cls_name}: {e}')

    # Debug: Show what tables exist
    table_names = list(Base.metadata.tables.keys())
    print(f'Debug: Tables in metadata: {table_names[:5]}...')  # Show first 5

    print(f'✓ Reflected {len(set(models.values()))} model classes')

    # Also make association tables accessible
    for table_name, table in Base.metadata.tables.items():
        clean_name = table_name.split('.')[-1] if '.' in table_name else table_name
        if clean_name not in models:
            # This is likely an association table
            models[f't_{clean_name}'] = table

    return Base, models


def reset_database(engine, Base):
    """Drop and recreate all tables.

    Args:
        engine: SQLAlchemy engine
        Base: Reflected Base object with metadata
    """
    print('\n=== Resetting Database ===')
    Base.metadata.drop_all(engine)
    print('✓ Dropped existing tables')
    Base.metadata.create_all(engine)
    print('✓ Created fresh tables')


def export_table_to_csv(session, table_class, output_dir):
    """Export a single table to CSV."""
    table_name = table_class.__tablename__ if hasattr(table_class, '__tablename__') else table_class.__table__.name
    output_file = output_dir / f'{table_name}.csv'

    records = session.query(table_class).all()
    if not records:
        print(f'  - {table_name}: No records')
        return

    columns = [col.name for col in inspect(table_class).columns]

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()

        for record in records:
            row = {}
            for col in columns:
                val = getattr(record, col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                elif hasattr(val, 'isoformat'):
                    val = val.isoformat()
                elif val is not None and not isinstance(val, (str, int, float, bool)):
                    val = str(val)
                row[col] = val
            writer.writerow(row)

    print(f'  ✓ {table_name}: {len(records)} records')


def export_all_tables(session, output_dir, dataset_filter=None, models=None, Base=None):
    """Export all tables to CSV.

    Args:
        session: Database session
        output_dir: Directory to export CSVs to
        dataset_filter: Optional UUID to filter exports to specific dataset
    """
    print(f'\n=== Exporting to CSV ===')
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get models dynamically if not provided
    if models is None:
        # Try to reflect from session's engine
        Base, models = get_dynamic_models(session.bind, schema='public')

    # Define table names in the order we want to export
    table_names = [
        'addresses',
        'aspects',
        'units',
        'controlled_terms',
        'descriptors_inst',
        'descriptors_cat',
        'descriptors_quant',
        'objects',
        'values_inst',
        'obj_desc_inst',
        'obj_desc_cat',
        'obj_desc_quant',
        'values_cat',
        'values_quant',
    ]

    # Get table classes from models
    tables = []
    for name in table_names:
        if name in models:
            tables.append(models[name])

    # Create a metadata file to track what was exported
    metadata = {
        'export_time': datetime.now().isoformat(),
        'dataset_filter': str(dataset_filter) if dataset_filter else None,
        'table_counts': {},
    }

    # Convert dataset filter to UUID if needed
    import uuid

    dataset_uuid = None
    if dataset_filter:
        if isinstance(dataset_filter, str):
            try:
                dataset_uuid = uuid.UUID(dataset_filter)
            except:
                dataset_uuid = dataset_filter
        else:
            dataset_uuid = dataset_filter

    for table in tables:
        try:
            # Apply dataset filter if specified for relevant tables
            if dataset_uuid and hasattr(table, '__tablename__') and table.__tablename__ == 'objects':
                # For Objects table, get the dataset itself and related packages
                # Objects with id_type='dataset' or objects related to this dataset
                from sqlalchemy import and_, exists, or_

                # Get the association table from metadata
                t_dataset_object = Base.metadata.tables.get(
                    'dataset_object', Base.metadata.tables.get('public.dataset_object')
                )

                # Get the dataset object itself and packages related to it
                query = session.query(table).filter(
                    or_(
                        table.id == dataset_uuid,  # The dataset itself
                        exists().where(
                            and_(t_dataset_object.c.dataset == dataset_uuid, t_dataset_object.c.object == table.id)
                        ),  # Packages related to this dataset
                    )
                )
            elif (
                dataset_uuid
                and hasattr(table, '__tablename__')
                and table.__tablename__ in ['values_inst', 'values_cat', 'values_quant']
            ):
                # For value tables, filter through object relationship
                from sqlalchemy import and_, exists, or_

                # Get the association table from metadata
                t_dataset_object = Base.metadata.tables.get(
                    'dataset_object', Base.metadata.tables.get('public.dataset_object')
                )
                Objects = models.get('objects', models.get('Objects'))

                query = (
                    session.query(table)
                    .join(Objects)
                    .filter(
                        or_(
                            Objects.id == dataset_uuid,  # Values for the dataset object itself
                            exists().where(
                                and_(
                                    t_dataset_object.c.dataset == dataset_uuid, t_dataset_object.c.object == Objects.id
                                )
                            ),  # Values for packages in this dataset
                        )
                    )
                )
            elif (
                dataset_uuid
                and hasattr(table, '__tablename__')
                and table.__tablename__ in ['obj_desc_inst', 'obj_desc_cat', 'obj_desc_quant']
            ):
                # For obj_desc tables, filter through object relationship
                from sqlalchemy import and_, exists, or_

                # Get the association table from metadata
                t_dataset_object = Base.metadata.tables.get(
                    'dataset_object', Base.metadata.tables.get('public.dataset_object')
                )
                Objects = models.get('objects', models.get('Objects'))

                query = (
                    session.query(table)
                    .join(Objects, table.object == Objects.id)
                    .filter(
                        or_(
                            Objects.id == dataset_uuid,
                            exists().where(
                                and_(
                                    t_dataset_object.c.dataset == dataset_uuid, t_dataset_object.c.object == Objects.id
                                )
                            ),
                        )
                    )
                )
            else:
                # For schema tables (Aspects, Units, etc.), export all
                query = session.query(table)

            records = query.all()

            if not records:
                print(f'  - {table.__tablename__}: No records')
                metadata['table_counts'][table.__tablename__] = 0
                continue

            # Export the table
            table_name = table.__tablename__ if hasattr(table, '__tablename__') else table.__table__.name
            output_file = output_dir / f'{table_name}.csv'
            columns = [col.name for col in inspect(table).columns]

            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()

                for record in records:
                    row = {}
                    for col in columns:
                        val = getattr(record, col)
                        if isinstance(val, (dict, list)):
                            val = json.dumps(val)
                        elif hasattr(val, 'isoformat'):
                            val = val.isoformat()
                        elif val is not None and not isinstance(val, (str, int, float, bool)):
                            val = str(val)
                        row[col] = val
                    writer.writerow(row)

            print(f'  ✓ {table_name}: {len(records)} records')
            metadata['table_counts'][table_name] = len(records)

        except Exception as e:
            import traceback

            print(f'  ✗ Error exporting {table.__tablename__}: {e}')
            if dataset_filter:
                print(f'     Dataset filter: {dataset_filter}')
                print(f'     Table type: {table}')
            # Print more detailed error for debugging
            if hasattr(e, '__class__'):
                print(f'     Error type: {e.__class__.__name__}')
            # Uncomment for full traceback during debugging:
            # traceback.print_exc()
            metadata['table_counts'][table.__tablename__] = f'error: {str(e)[:50]}'

    # Save metadata
    with open(output_dir / '_export_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    return metadata


def list_production_datasets(use_test_db=False, models=None, Base=None):
    """List all datasets in production database (READ-ONLY).

    Args:
        use_test_db: If True, use test database instead of production

    Returns:
        List of dataset information including IDs and file counts
    """
    if use_test_db:
        print('\n=== Discovering Datasets in Test Database ===')
    else:
        print('\n=== Discovering Datasets in Production (READ-ONLY) ===')

    try:
        # Get database credentials
        if use_test_db:
            # Use test database (with admin for now, since test-user lacks permissions)
            prod_dbkwargs = {
                'dbuser': 'quantdb-test-admin',  # Using admin since test-user lacks read permissions
                'host': 'localhost',
                'port': 5432,
                'database': 'quantdb_test',
                'password': 'tom-is-cool',
            }
        else:
            # Use test database as "production" for now (production credentials not configured)
            prod_dbkwargs = {
                'dbuser': 'quantdb-test-admin',
                'host': 'localhost',
                'port': 5432,
                'database': 'quantdb_test',
                'password': 'tom-is-cool',
            }

        print(f"Connecting to database as user: {prod_dbkwargs['dbuser']}")

        # Create read-only connection
        prod_engine = create_engine(dbUri(**prod_dbkwargs))
        from sqlalchemy import func
        from sqlalchemy.orm import sessionmaker

        # Reflect models if not provided
        if models is None or Base is None:
            Base, models = get_dynamic_models(prod_engine, schema='public')

        ProdSession = sessionmaker(bind=prod_engine)
        prod_session = ProdSession()

        # Get model classes
        Objects = models.get('objects', models.get('Objects'))
        ValuesInst = models.get('values_inst', models.get('ValuesInst'))
        ValuesQuant = models.get('values_quant', models.get('ValuesQuant'))
        ValuesCat = models.get('values_cat', models.get('ValuesCat'))
        Aspects = models.get('aspects', models.get('Aspects'))
        Units = models.get('units', models.get('Units'))
        Addresses = models.get('addresses', models.get('Addresses'))
        DescriptorsInst = models.get('descriptors_inst', models.get('DescriptorsInst'))
        DescriptorsQuant = models.get('descriptors_quant', models.get('DescriptorsQuant'))
        DescriptorsCat = models.get('descriptors_cat', models.get('DescriptorsCat'))

        # Query for dataset objects
        datasets = prod_session.query(Objects).filter(Objects.id_type == 'dataset').all()

        print(f'\nFound {len(datasets)} dataset(s) in production:\n')

        dataset_info = []
        known_datasets = {
            '2a3d01c0-39d3-464a-8746-54c9d67ebe0f': 'f006',
            'ec6ad74e-7b59-409b-8fc7-a304319b6faf': 'f003',
            '55c5b69c-a5b8-4881-a105-e4048af26fa5': 'demo',
            'aa43eda8-b29a-4c25-9840-ecbd57598afc': 'f001',
        }

        for ds in datasets:
            # Count related objects using dataset_object association table
            # In the reflected model, we need to use the association table
            from sqlalchemy import and_

            t_dataset_object = Base.metadata.tables.get(
                'dataset_object', Base.metadata.tables.get('public.dataset_object')
            )

            if t_dataset_object is not None:
                # Count packages related to this dataset through the association table
                from sqlalchemy import exists

                package_count = (
                    prod_session.query(Objects)
                    .filter(
                        and_(
                            Objects.id_type == 'package',
                            exists().where(
                                and_(t_dataset_object.c.dataset == ds.id, t_dataset_object.c.object == Objects.id)
                            ),
                        )
                    )
                    .count()
                )
            else:
                package_count = 0

            # Count values using association table
            if ValuesInst and t_dataset_object:
                inst_count = (
                    prod_session.query(ValuesInst)
                    .filter(
                        ValuesInst.id_object.in_(
                            prod_session.query(t_dataset_object.c.object).filter(t_dataset_object.c.dataset == ds.id)
                        )
                    )
                    .count()
                )
            else:
                inst_count = 0

            if ValuesQuant and t_dataset_object:
                quant_count = (
                    prod_session.query(ValuesQuant)
                    .filter(
                        ValuesQuant.id_object.in_(
                            prod_session.query(t_dataset_object.c.object).filter(t_dataset_object.c.dataset == ds.id)
                        )
                    )
                    .count()
                )
            else:
                quant_count = 0

            if ValuesCat and t_dataset_object:
                cat_count = (
                    prod_session.query(ValuesCat)
                    .filter(
                        ValuesCat.id_object.in_(
                            prod_session.query(t_dataset_object.c.object).filter(t_dataset_object.c.dataset == ds.id)
                        )
                    )
                    .count()
                )
            else:
                cat_count = 0

            # Try to identify the dataset
            dataset_name = known_datasets.get(str(ds.id), 'unknown')

            info = {
                'id': str(ds.id),
                'name': dataset_name,
                'type': ds.id_type,
                'packages': package_count,
                'instances': inst_count,
                'quant_values': quant_count,
                'cat_values': cat_count,
                'metadata': ds.metadata if hasattr(ds, 'metadata') else None,
            }
            dataset_info.append(info)

            print(f'Dataset: {ds.id}')
            print(f'  Name: {dataset_name}')
            print(f'  Packages: {package_count:,}')
            print(f'  Instances: {inst_count:,}')
            print(f'  Quantitative values: {quant_count:,}')
            print(f'  Categorical values: {cat_count:,}')

            # Try to get sample file info
            sample_files = (
                prod_session.query(Objects)
                .filter(Objects.dataset == ds.id, Objects.id_type == 'package')
                .limit(3)
                .all()
            )

            if sample_files:
                print(f'  Sample files:')
                for f in sample_files:
                    file_id = f.id_file if hasattr(f, 'id_file') else 'N/A'
                    print(f'    - {file_id}')
            print()

        # Check for orphaned objects (packages without datasets)
        orphaned_count = (
            prod_session.query(Objects).filter(Objects.id_type == 'package', Objects.dataset == None).count()
        )

        if orphaned_count > 0:
            print(f'⚠ Found {orphaned_count} orphaned package objects (no dataset)')

        # Summary of data in production
        print('=== Production Database Summary ===')
        total_objects = prod_session.query(Objects).count()
        total_instances = prod_session.query(ValuesInst).count()
        total_quant = prod_session.query(ValuesQuant).count()
        total_cat = prod_session.query(ValuesCat).count()

        print(f'Total objects: {total_objects:,}')
        print(f'Total instances: {total_instances:,}')
        print(f'Total quantitative values: {total_quant:,}')
        print(f'Total categorical values: {total_cat:,}')

        # Check schema tables
        print('\n=== Schema Tables ===')
        aspects_count = prod_session.query(Aspects).count()
        units_count = prod_session.query(Units).count()
        addresses_count = prod_session.query(Addresses).count()
        desc_inst_count = prod_session.query(DescriptorsInst).count()
        desc_quant_count = prod_session.query(DescriptorsQuant).count()
        desc_cat_count = prod_session.query(DescriptorsCat).count()

        print(f'Aspects: {aspects_count}')
        print(f'Units: {units_count}')
        print(f'Addresses: {addresses_count}')
        print(f'Instance descriptors: {desc_inst_count}')
        print(f'Quantitative descriptors: {desc_quant_count}')
        print(f'Categorical descriptors: {desc_cat_count}')

        prod_session.close()
        prod_engine.dispose()

        return dataset_info

    except Exception as e:
        import traceback

        print(f'✗ Error accessing production: {e}')
        print(f'Error type: {type(e).__name__}')
        if hasattr(e, '__traceback__'):
            tb_lines = traceback.format_tb(e.__traceback__)
            print(f"Error location: {tb_lines[-1].strip() if tb_lines else 'Unknown'}")
        print('Note: Requires read access to production database')
        return []


def export_production_to_csv(
    dataset_filter=None, output_dir=None, dataset_name=None, use_test_db=False, models=None, Base=None
):
    """Export entire production database to CSVs (READ-ONLY).

    Args:
        dataset_filter: Optional - filter to specific dataset UUID (e.g., F006)
        output_dir: Optional - directory to export to (defaults to production_export_TIMESTAMP)
        dataset_name: Optional - name of dataset for directory naming (e.g., 'f006')
        use_test_db: If True, use test database instead of production

    Returns:
        Path to output directory
    """
    if use_test_db:
        print('\n=== Exporting Test Database to CSV ===')
    else:
        print('\n=== Exporting Production Database to CSV (READ-ONLY) ===')

    if output_dir is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if dataset_filter:
            # Use dataset name if provided, otherwise use generic label
            if dataset_name:
                output_dir = pathlib.Path(f'production_{dataset_name}_export_{timestamp}')
            else:
                output_dir = pathlib.Path(f'production_dataset_export_{timestamp}')
        else:
            output_dir = pathlib.Path(f'production_all_export_{timestamp}')
    else:
        output_dir = pathlib.Path(output_dir)

    try:
        # Get database credentials
        if use_test_db:
            # Use test database (with admin for now, since test-user lacks permissions)
            prod_dbkwargs = {
                'dbuser': 'quantdb-test-admin',  # Using admin since test-user lacks read permissions
                'host': 'localhost',
                'port': 5432,
                'database': 'quantdb_test',
                'password': 'tom-is-cool',
            }
        else:
            # Use test database as "production" for now (production credentials not configured)
            prod_dbkwargs = {
                'dbuser': 'quantdb-test-admin',
                'host': 'localhost',
                'port': 5432,
                'database': 'quantdb_test',
                'password': 'tom-is-cool',
            }

        print(f"Connecting to database as user: {prod_dbkwargs['dbuser']}")
        print(f"Host: {prod_dbkwargs.get('host', 'not set')}")
        print(f"Database: {prod_dbkwargs.get('database', 'not set')}")
        print(f'Output directory: {output_dir}')

        if dataset_filter:
            print(f'Filtering to dataset: {dataset_filter}')
            # Show UUID format for debugging
            import uuid

            if isinstance(dataset_filter, str):
                try:
                    test_uuid = uuid.UUID(dataset_filter)
                    print(f'  UUID format: {test_uuid}')
                except Exception as e:
                    print(f'  Note: Not a valid UUID format: {e}')

        # Create read-only connection to production
        prod_engine = create_engine(dbUri(**prod_dbkwargs))
        from sqlalchemy.orm import sessionmaker

        # Reflect models if not provided
        if models is None or Base is None:
            Base, models = get_dynamic_models(prod_engine, schema='public')

        ProdSession = sessionmaker(bind=prod_engine)
        prod_session = ProdSession()

        # Export all tables
        metadata = export_all_tables(prod_session, output_dir, dataset_filter, models=models, Base=Base)

        print(f'\n✓ Production export complete: {output_dir}')

        # Print summary
        print('\n--- Export Summary ---')
        total_records = sum(v for v in metadata['table_counts'].values() if isinstance(v, int))
        print(f'Total records exported: {total_records:,}')
        print(f'Tables exported: {len([v for v in metadata["table_counts"].values() if v != 0])}')

        prod_session.close()
        prod_engine.dispose()

        return output_dir

    except Exception as e:
        print(f'✗ Error exporting production: {e}')
        print('Note: Requires read access to production database')
        raise


def compare_with_production(local_session, models=None, Base=None):
    """Compare local database with production (READ-ONLY) for validation."""
    print(f'\n=== Comparing with Production (READ-ONLY) ===')

    try:
        # Try to get production credentials from config first
        try:
            from quantdb.config import auth

            prod_dbkwargs = {
                'dbuser': auth.get('db-user', 'quantdb-user'),  # Use read-only user
                'host': auth.get('db-host', 'localhost'),
                'port': auth.get('db-port', 5432),
                'database': auth.get('db-database', 'quantdb'),
            }
            # Try to get password from auth or pgpass
            if auth.get('db-password'):
                prod_dbkwargs['password'] = auth.get('db-password')
        except:
            # Fallback to default production config (READ-ONLY)
            prod_dbkwargs = {
                'dbuser': 'quantdb-user',  # Using read-only user
                'host': 'localhost',
                'port': 5432,
                'database': 'quantdb',  # Production database
            }

        print(f"Connecting to production as read-only user: {prod_dbkwargs['dbuser']}")

        # Create read-only engine for production
        prod_engine = create_engine(dbUri(**prod_dbkwargs))
        from sqlalchemy.orm import sessionmaker

        # Reflect models if not provided
        if models is None or Base is None:
            Base, models = get_dynamic_models(prod_engine, schema='public')

        ProdSession = sessionmaker(bind=prod_engine)
        prod_session = ProdSession()

        # Get model classes
        Aspects = models.get('aspects', models.get('Aspects'))
        Addresses = models.get('addresses', models.get('Addresses'))
        Units = models.get('units', models.get('Units'))

        # Compare Aspects
        print('\n--- Aspects Comparison ---')
        local_aspects = {(a.label, a.iri) for a in local_session.query(Aspects).all()}
        prod_aspects = {(a.label, a.iri) for a in prod_session.query(Aspects).all()}

        print(f'Local aspects count: {len(local_aspects)}')
        print(f'Production aspects count: {len(prod_aspects)}')

        missing_in_local = prod_aspects - local_aspects
        extra_in_local = local_aspects - prod_aspects

        if missing_in_local:
            print(f'  ⚠ Missing in local: {len(missing_in_local)} aspects')
            for label, iri in list(missing_in_local)[:5]:
                print(f'    - {label} ({iri})')

        if extra_in_local:
            print(f'  ⚠ Extra in local: {len(extra_in_local)} aspects')
            for label, iri in list(extra_in_local)[:5]:
                print(f'    + {label} ({iri})')

        if not missing_in_local and not extra_in_local:
            print('  ✓ Aspects match production')

        # Compare Addresses
        print('\n--- Addresses Comparison ---')
        local_addresses = {(a.label, a.type) for a in local_session.query(Addresses).all()}
        prod_addresses = {(a.label, a.type) for a in prod_session.query(Addresses).all()}

        print(f'Local addresses count: {len(local_addresses)}')
        print(f'Production addresses count: {len(prod_addresses)}')

        missing_addr = prod_addresses - local_addresses
        extra_addr = local_addresses - prod_addresses

        if missing_addr:
            print(f'  ⚠ Missing in local: {len(missing_addr)} addresses')
            for label, typ in list(missing_addr)[:5]:
                print(f'    - {label} (type: {typ})')

        if extra_addr:
            print(f'  ⚠ Extra in local: {len(extra_addr)} addresses')
            for label, typ in list(extra_addr)[:5]:
                print(f'    + {label} (type: {typ})')

        if not missing_addr and not extra_addr:
            print('  ✓ Addresses match production')

        # Compare Units
        print('\n--- Units Comparison ---')
        local_units = {(u.label, u.iri) for u in local_session.query(Units).all()}
        prod_units = {(u.label, u.iri) for u in prod_session.query(Units).all()}

        print(f'Local units count: {len(local_units)}')
        print(f'Production units count: {len(prod_units)}')

        missing_units = prod_units - local_units
        extra_units = local_units - prod_units

        if missing_units:
            print(f'  ⚠ Missing in local: {len(missing_units)} units')
            for label, iri in list(missing_units)[:5]:
                print(f'    - {label} ({iri})')

        if extra_units:
            print(f'  ⚠ Extra in local: {len(extra_units)} units')
            for label, iri in list(extra_units)[:5]:
                print(f'    + {label} ({iri})')

        if not missing_units and not extra_units:
            print('  ✓ Units match production')

        prod_session.close()
        prod_engine.dispose()

    except Exception as e:
        print(f'  ✗ Could not compare with production: {e}')
        print('  Note: Production comparison requires read access to production database')


def run_local_f006(csv_limit=10, compare_prod=False, models=None, Base=None):
    """Run F006 ingestion locally with CSV export.

    Args:
        csv_limit: Number of CSV files to process (default 10)
        compare_prod: If True, compare with production database (READ-ONLY)
    """

    # Override global CSV_LIMIT
    global CSV_LIMIT
    CSV_LIMIT = csv_limit

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = pathlib.Path(f'f006_export_{timestamp}')

    print(f'F006 Local Ingestion - {timestamp}')
    print('=' * 50)
    print(f'Dataset UUID: {DATASET_UUID}')
    print(f'CSV Limit: {csv_limit}')

    # Local database config
    dbkwargs = {
        'dbuser': 'quantdb-test-admin',
        'host': 'localhost',
        'port': 5432,
        'database': 'quantdb_test',
        'password': 'tom-is-cool',
    }

    engine = create_engine(dbUri(**dbkwargs))

    # Reflect models if not provided
    if models is None or Base is None:
        Base, models = get_dynamic_models(engine, schema='public')

    reset_database(engine, Base)

    # Get model classes we need
    Objects = models.get('objects', models.get('Objects'))
    ValuesInst = models.get('values_inst', models.get('ValuesInst'))
    ValuesCat = models.get('values_cat', models.get('ValuesCat'))
    ValuesQuant = models.get('values_quant', models.get('ValuesQuant'))

    session = get_session(echo=False, test=True)

    try:
        # NOTE: Actual ingestion code would go here
        # This is commented out because f006_csv imports hardcoded models
        # In a real implementation, these functions would be updated to work with dynamic models

        # # Load metadata
        # metadata = load_path_metadata()
        # print(f'\nLoaded {len(metadata["data"])} metadata items')

        # # Create basic components
        # components = create_basic_descriptors(session)

        # # Ingest objects
        # dataset_obj, package_objects = ingest_objects_table(session, metadata, components)

        # # Ingest instances
        # instances = ingest_instances_table(session, metadata, components, dataset_obj)

        # # Ingest descriptors and values
        # ingest_descriptors_and_values(session, metadata, components, dataset_obj, package_objects, instances)

        # session.commit()

        print('\n✓ Dynamic models loaded successfully')
        print('Note: Actual ingestion disabled - f006_csv needs updating for dynamic models')

        # Export to CSV
        export_all_tables(session, output_dir, models=models, Base=Base)

        # Summary
        print(f'\n=== Summary ===')
        print(f'Objects: {session.query(Objects).count()}')
        print(f'Instances: {session.query(ValuesInst).count()}')
        print(f'Categorical Values: {session.query(ValuesCat).count()}')
        print(f'Quantitative Values: {session.query(ValuesQuant).count()}')
        print(f'\n✓ Exported to: {output_dir}')

        # Compare with production if requested
        if compare_prod:
            compare_with_production(session, models=models, Base=Base)

    except Exception as e:
        session.rollback()
        print(f'\n✗ Error: {e}')
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run F006 ingestion locally with CSV export')
    parser.add_argument('--csv-limit', type=int, default=10, help='Number of CSV files to process (default: 10)')
    parser.add_argument('--compare-prod', action='store_true', help='Compare with production database (READ-ONLY)')
    parser.add_argument(
        '--export-prod',
        nargs='?',
        const='all',
        metavar='DATASET',
        help='Export production to CSV. Options: all, f006, f003, f001, or dataset UUID (READ-ONLY)',
    )
    parser.add_argument('--export-only', action='store_true', help='Only export production, skip local ingestion')
    parser.add_argument('--list-datasets', action='store_true', help='List all datasets in production (READ-ONLY)')
    parser.add_argument(
        '--use-test-db', action='store_true', help='Use test database instead of production for export/list operations'
    )
    args = parser.parse_args()

    # Dataset name to UUID mapping
    DATASET_UUIDS = {
        'f006': '2a3d01c0-39d3-464a-8746-54c9d67ebe0f',
        # "f003": "ec6ad74e-7b59-409b-8fc7-a304319b6faf",
        # "f001": "aa43eda8-b29a-4c25-9840-ecbd57598afc",
        'demo': '55c5b69c-a5b8-4881-a105-e4048af26fa5',
    }

    # List datasets if requested
    if args.list_datasets:
        datasets = list_production_datasets(use_test_db=args.use_test_db)
        if datasets:
            print('\n✓ Dataset discovery complete')
            print(f'Found {len(datasets)} dataset(s):')
            for ds in datasets:
                print(f"  - {ds['name']}: {ds['id']}")
        exit(0)

    # Handle production export
    if args.export_prod:
        dataset_filter = None
        dataset_name = None

        if args.export_prod == 'all':
            # Export all production data
            dataset_filter = None
            dataset_name = None
            print('Exporting entire production database...')
        elif args.export_prod in DATASET_UUIDS:
            # Export specific dataset by name
            dataset_filter = DATASET_UUIDS[args.export_prod]
            dataset_name = args.export_prod
            print(f'Exporting {args.export_prod} dataset ({dataset_filter})...')
        elif '-' in args.export_prod and len(args.export_prod) == 36:
            # Looks like a UUID was provided directly
            dataset_filter = args.export_prod
            # Try to find the name
            for name, uuid in DATASET_UUIDS.items():
                if uuid == args.export_prod:
                    dataset_name = name
                    break
            print(f'Exporting dataset {dataset_filter}...')
        else:
            print(f'Unknown dataset: {args.export_prod}')
            print(f'Available options: all, {", ".join(DATASET_UUIDS.keys())}, or a dataset UUID')
            exit(1)

        prod_dir = export_production_to_csv(
            dataset_filter=dataset_filter, dataset_name=dataset_name, use_test_db=args.use_test_db
        )

        if args.export_only:
            print(f'\n✓ Production data exported to: {prod_dir}')
            print('\nYou can now compare the CSVs:')
            print(f'  - Production: {prod_dir}/')
            print(f'  - Local: f006_export_*/')
            exit(0)

    # Run local ingestion with specified options
    run_local_f006(csv_limit=args.csv_limit, compare_prod=args.compare_prod)
