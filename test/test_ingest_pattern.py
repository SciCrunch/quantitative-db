#!/usr/bin/env python3
"""
Test the quantdb/ingest.py pattern using only core components.
This will help understand how to modify f006.py to match the pattern.
"""

import os
import shutil
import sys
import uuid

from sqlalchemy.sql import text as sql_text

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_tables_to_csv import export_detailed_views, export_tables_to_csv

from quantdb.client import get_session
from quantdb.ingest import (
    InternalIds,
    Queries,
    makeParamsValues,
    values_objects_from_objects,
)


def clear_test_database(session):
    """Clear all data from the test database (except schema)."""
    print('Clearing test database...')

    # Tables to clear in order (respecting foreign key constraints)
    tables_to_clear = [
        'values_quant',
        'values_cat',
        'obj_desc_quant',
        'obj_desc_cat',
        'obj_desc_inst',
        'instance_parent',
        'values_inst',
        'dataset_object',
        'objects',
        'objects_internal',
    ]

    for table in tables_to_clear:
        try:
            session.execute(sql_text(f'TRUNCATE TABLE {table} CASCADE'))
            print(f'  ✓ Cleared {table}')
        except Exception as e:
            print(f'  - Skipping {table}: {e}')

    session.commit()
    print('Database cleared.\n')


def extract_test_pattern(dataset_uuid):
    """
    Extract function following the exact pattern from quantdb/ingest.py.
    This mimics what extract_reva_ft does but with minimal test data.
    """

    # 1. updated_transitive - would come from metadata timestamps
    updated_transitive = None

    # 2. Create test data - simulate what would come from path metadata
    # Create some test "files" that would be packages
    test_files = [
        {
            'file_id': 1,  # Changed from 'file_001' to integer
            'object_uuid': str(uuid.uuid4()),
            'subject': 'sub-test1',
            'sample': 'sam-test1',
            'modality': 'microct',
        },
        {
            'file_id': 2,  # Changed from 'file_002' to integer
            'object_uuid': str(uuid.uuid4()),
            'subject': 'sub-test1',
            'sample': 'sam-test2',
            'modality': 'microct',
        },
    ]

    # 3. Build objects dictionary (like in extract_reva_ft)
    datasets = {dataset_uuid: {'id_type': 'dataset'}}
    packages = {
        f['object_uuid']: {
            'id_type': 'package',
            'id_file': f['file_id'],
        }
        for f in test_files
    }
    objects = {**datasets, **packages}

    # 4. values_objects - prepare for bulk insert
    values_objects = values_objects_from_objects(objects)

    # 5. values_dataset_object - link packages to dataset
    values_dataset_object = [(dataset_uuid, f['object_uuid']) for f in test_files]

    # 6. Create instances data structure
    subjects = {
        (dataset_uuid, 'sub-test1'): {
            'type': 'subject',
            'desc_inst': 'human',
            'id_sub': 'sub-test1',
        }
    }

    samples = {
        (dataset_uuid, 'sam-test1'): {
            'type': 'sample',
            'desc_inst': 'nerve-volume',
            'id_sub': 'sub-test1',
            'id_sam': 'sam-test1',
        },
        (dataset_uuid, 'sam-test2'): {
            'type': 'sample',
            'desc_inst': 'nerve-volume',
            'id_sub': 'sub-test1',
            'id_sam': 'sam-test2',
        },
    }

    instances = {**subjects, **samples}

    # 7. Parent relationships
    parents = [
        (dataset_uuid, 'sam-test1', 'sub-test1'),
        (dataset_uuid, 'sam-test2', 'sub-test1'),
    ]

    # 8. Define maker functions (exactly like in extract_reva_ft)
    def make_values_instances(i):
        """Create values_inst records."""
        values_instances = [
            (
                d,
                f,
                inst['type'],
                i.luid[inst['desc_inst']],
                inst.get('id_sub'),
                inst.get('id_sam'),
            )
            for (d, f), inst in instances.items()
        ]
        return values_instances

    def make_values_parents(luinst):
        """Create instance_parent records."""
        values_parents = [(luinst[d, child], luinst[d, parent]) for d, child, parent in parents]
        return values_parents

    def make_void(this_dataset_updated_uuid, i):
        """Create obj_desc_inst mappings."""
        void = [
            (o, i.id_nerve_volume, i.addr_const_null, None) for o, b in objects.items() if b['id_type'] == 'package'
        ]
        return void

    def make_vocd(this_dataset_updated_uuid, i):
        """Create obj_desc_cat mappings."""
        vocd = [(o, i.cd_mod, i.addr_const_null) for o, b in objects.items() if b['id_type'] == 'package']
        return vocd

    def make_voqd(this_dataset_updated_uuid, i):
        """Create obj_desc_quant mappings."""
        voqd = []  # No quantitative descriptors in this test
        return voqd

    def make_values_cat(this_dataset_updated_uuid, i, luinst):
        """Create categorical values."""
        values_cv = []
        for f in test_files:
            values_cv.append(
                (
                    f['modality'],  # value_open
                    i.ct_mod,  # value_controlled (microct)
                    f['object_uuid'],  # object
                    i.id_nerve_volume,  # desc_inst
                    i.cd_mod,  # desc_cat (hasDataAboutItModality)
                    luinst[dataset_uuid, f['sample']],  # instance
                )
            )
        return values_cv

    def make_values_quant(this_dataset_updated_uuid, i, luinst):
        """Create quantitative values."""
        values_qv = []  # No quantitative values in this test
        return values_qv

    # Return the 10 required components
    return (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    )


def ingest_test(dataset_uuid, extract_fun, session, commit=False, dev=False):
    """
    Simplified ingest function that follows the exact pattern from quantdb/ingest.py
    """

    ocdn = ' ON CONFLICT DO NOTHING' if dev else ''

    # Get all components from extract function
    (
        updated_transitive,
        values_objects,
        values_dataset_object,
        make_values_instances,
        make_values_parents,
        make_void,
        make_vocd,
        make_voqd,
        make_values_cat,
        make_values_quant,
    ) = extract_fun(dataset_uuid)

    # Initialize queries and internal IDs
    q = Queries(session)
    i = InternalIds(q)

    # Get instances (no dependencies)
    values_instances = make_values_instances(i)

    # Insert dataset
    res0 = session.execute(
        sql_text('INSERT INTO objects (id, id_type) VALUES (:id, :id_type) ON CONFLICT DO NOTHING'),
        dict(id=dataset_uuid, id_type='dataset'),
    )

    # Insert objects (packages)
    vt, params = makeParamsValues(values_objects)
    session.execute(sql_text(f'INSERT INTO objects (id, id_type, id_file) VALUES {vt}{ocdn}'), params)

    # Insert dataset_object relationships
    vt, params = makeParamsValues(values_dataset_object)
    session.execute(sql_text(f'INSERT INTO dataset_object (dataset, object) VALUES {vt}{ocdn}'), params)

    # Insert instances
    vt, params = makeParamsValues(values_instances)
    session.execute(
        sql_text(f'INSERT INTO values_inst (dataset, id_formal, type, desc_inst, id_sub, id_sam) VALUES {vt}{ocdn}'),
        params,
    )

    # Get all instances for lookup
    ilt = q.insts_from_dataset(dataset_uuid)
    luinst = {(str(dataset), id_formal): id for id, dataset, id_formal in ilt}

    # Get dependent values
    values_parents = make_values_parents(luinst)
    void = make_void(None, i)
    vocd = make_vocd(None, i)
    voqd = make_voqd(None, i)
    values_cv = make_values_cat(None, i, luinst)
    values_qv = make_values_quant(None, i, luinst)

    # Insert parent relationships
    if values_parents:
        vt, params = makeParamsValues(values_parents)
        session.execute(sql_text(f'INSERT INTO instance_parent VALUES {vt}{ocdn}'), params)

    # Insert obj_desc_inst
    if void:
        vt, params = makeParamsValues(void)
        session.execute(
            sql_text(f'INSERT INTO obj_desc_inst (object, desc_inst, addr_field, addr_desc_inst) VALUES {vt}{ocdn}'),
            params,
        )

    # Insert obj_desc_cat
    if vocd:
        vt, params = makeParamsValues(vocd)
        session.execute(sql_text(f'INSERT INTO obj_desc_cat (object, desc_cat, addr_field) VALUES {vt}{ocdn}'), params)

    # Insert obj_desc_quant
    if voqd:
        vt, params = makeParamsValues(voqd)
        session.execute(
            sql_text(f'INSERT INTO obj_desc_quant (object, desc_quant, addr_field) VALUES {vt}{ocdn}'), params
        )

    # Insert categorical values
    if values_cv:
        vt, params = makeParamsValues(values_cv)
        session.execute(
            sql_text(
                f'INSERT INTO values_cat (value_open, value_controlled, object, desc_inst, desc_cat, instance) VALUES {vt}{ocdn}'
            ),
            params,
        )

    # Insert quantitative values
    if values_qv:
        from sqlalchemy.dialects.postgresql import JSONB

        vt, params, bindparams = makeParamsValues(
            values_qv,
            row_types=(None, None, None, None, None, JSONB),
        )
        t = sql_text(
            f'INSERT INTO values_quant (value, object, desc_inst, desc_quant, instance, value_blob) VALUES {vt}{ocdn}'
        )
        tin = t.bindparams(*bindparams)
        session.execute(tin, params)

    if commit:
        session.commit()

    print('✓ Ingestion completed')


def main():
    """Main test function."""

    # Create output directory
    output_dir = 'debug_csvs_pattern_test'
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    print('Testing quantdb/ingest.py pattern')
    print('=' * 60)
    print(f'Output will be saved to: {output_dir}/')

    # Get a session
    session = get_session(echo=False, test=True)

    try:
        # Clear database
        clear_test_database(session)

        # Test dataset
        dataset_uuid = str(uuid.uuid4())

        # Run ingestion
        print(f'\nRunning pattern test for dataset {dataset_uuid}...')
        ingest_test(dataset_uuid, extract_test_pattern, session, commit=True, dev=True)

        # Export results
        print(f'\nExporting results to {output_dir}...')
        export_tables_to_csv(output_dir)
        export_detailed_views(output_dir)

        # Show summary
        print('\n' + '=' * 60)
        print('SUMMARY OF POPULATED TABLES:')
        print('=' * 60)

        summary_file = os.path.join(output_dir, '_table_summary.csv')
        if os.path.exists(summary_file):
            import pandas as pd

            df = pd.read_csv(summary_file)
            populated = df[df['row_count'] > 0]
            for _, row in populated.iterrows():
                print(f"  {row['table']}: {row['row_count']} rows")

        print(f'\n✓ Test completed successfully!')
        print(f'Check CSV files in: {output_dir}/')

    except Exception as e:
        print(f'\n✗ Error: {e}')
        import traceback

        traceback.print_exc()
        session.rollback()

    finally:
        session.close()


if __name__ == '__main__':
    main()
