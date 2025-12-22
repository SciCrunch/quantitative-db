import pytest

from quantdb.generic_ingest import (
    back_populate_tables,
    get_constraint_columns,
    get_or_create,
    object_as_dict,
    query_by_constraints,
)
from quantdb.models import Objects


def test_object_as_dict():
    obj = Objects(id='00000000-0000-0000-0000-000000000001', id_type='dataset', id_file=None, id_internal=None)
    d = object_as_dict(obj)
    assert d['id'] == '00000000-0000-0000-0000-000000000001'
    assert d['id_type'] == 'dataset'


def test_get_or_create_creates_and_gets(test_session_with_rollback):
    obj = Objects(id='00000000-0000-0000-0000-000000000002', id_type='dataset', id_file=None, id_internal=None)
    instance = get_or_create(test_session_with_rollback, obj)
    assert getattr(instance, 'id', None) == '00000000-0000-0000-0000-000000000002'
    # Should return the same instance if called again
    instance2 = get_or_create(test_session_with_rollback, obj)
    assert getattr(instance, 'id', None) == getattr(instance2, 'id', None)


def test_get_constraint_columns():
    cols = get_constraint_columns(Objects)
    assert any('id' in col for col in cols)


def test_query_by_constraints(test_session_with_rollback):
    obj = Objects(id='00000000-0000-0000-0000-000000000003', id_type='dataset', id_file=None, id_internal=None)
    # Use get_or_create instead of manually adding to handle existing objects
    created_obj = get_or_create(test_session_with_rollback, obj)

    # Should find the object by unique constraint
    found = query_by_constraints(
        test_session_with_rollback,
        Objects(id='00000000-0000-0000-0000-000000000003', id_type='dataset', id_file=None, id_internal=None),
    )
    assert found is not None
    assert getattr(found, 'id', None) == '00000000-0000-0000-0000-000000000003'
    assert getattr(found, 'id_type', None) == 'dataset'


def test_back_populate_tables_adds_and_merges(test_session_with_rollback):
    obj = Objects(id='00000000-0000-0000-0000-000000000004', id_type='dataset', id_file=None, id_internal=None)
    # Should add new
    out = back_populate_tables(test_session_with_rollback, obj)
    assert getattr(out, 'id', None) == '00000000-0000-0000-0000-000000000004'
    # Should merge existing
    obj2 = Objects(id='00000000-0000-0000-0000-000000000004', id_type='dataset', id_file=None, id_internal=None)
    out2 = back_populate_tables(test_session_with_rollback, obj2)
    assert getattr(out2, 'id', None) == getattr(out, 'id', None)


def test_get_or_create_back_populate(test_session_with_rollback):
    obj = Objects(id='00000000-0000-0000-0000-000000000005', id_type='dataset', id_file=None, id_internal=None)
    instance = get_or_create(test_session_with_rollback, obj, back_populate={'id_file': 12345})
    assert getattr(instance, 'id_file', None) == 12345


def test_print_first_row_of_each_entity(test_session_with_rollback):
    """
    Prints the first row of each mapped entity in the test database.
    """
    import inspect as pyinspect

    from quantdb import models

    printed = False
    for name, cls in vars(models).items():
        if pyinspect.isclass(cls) and hasattr(cls, '__table__') and hasattr(cls, '__mapper__'):
            try:
                row = test_session_with_rollback.query(cls).first()
                if row:
                    print(f'First row for {name}: {row}')
                    printed = True
            except Exception as e:
                print(f'Could not query {name}: {e}')
    if not printed:
        print('No rows found in any entity.')


def test_f006_table_to_table_ingestion(test_session_with_rollback):
    """
    Test the complete f006 ingestion process using the ORM approach.
    This demonstrates table-to-table ingestion with the generic_ingest functions.
    """
    import pathlib
    import sys

    # Add the ingestion directory to the path so we can import f006
    ingestion_path = pathlib.Path(__file__).parent.parent / 'ingestion'
    sys.path.insert(0, str(ingestion_path))

    try:
        # Import the f006 ingestion module
        import f006

        # Run the ingestion without committing (dry run)
        result = f006.run_f006_ingestion(session=test_session_with_rollback, commit=False)

        # Verify the results
        assert result is not None
        assert 'dataset_obj' in result
        assert 'package_objects' in result
        assert 'instances' in result

        # Check dataset object
        dataset_obj = result['dataset_obj']
        assert dataset_obj.id == f006.DATASET_UUID
        assert dataset_obj.id_type == 'dataset'

        # Check package objects
        package_objects = result['package_objects']
        assert len(package_objects) >= 4  # Should have at least 4 files (actually has 48 in full dataset)
        for pkg in package_objects:
            assert pkg.id_type == 'package'
            assert pkg.id_file is not None

        # Check instances
        instances_dict = result['instances']
        instances = list(instances_dict.values())  # Extract the actual ValuesInst objects from the dictionary
        assert len(instances) >= 2  # Should have at least 1 subject + 1+ samples

        # Verify we have the right types of instances
        instance_types = {inst.type for inst in instances}
        assert 'subject' in instance_types
        assert 'sample' in instance_types

        # Check subject instance
        subject_instances = [inst for inst in instances if inst.type == 'subject']
        assert len(subject_instances) == 1
        subject = subject_instances[0]
        assert subject.id_formal == 'sub-f006'
        assert subject.id_sub == 'sub-f006'
        assert subject.id_sam is None

        # Check sample instances
        sample_instances = [inst for inst in instances if inst.type == 'sample']
        assert len(sample_instances) >= 2  # At least 2 samples based on our test data
        for sample in sample_instances:
            assert sample.id_formal.startswith('sam-')
            assert sample.id_sub == 'sub-f006'
            assert sample.id_sam == sample.id_formal

        print(f'✓ F006 ingestion test passed!')
        print(f'  - Dataset: {dataset_obj.id}')
        print(f'  - Packages: {len(package_objects)}')
        print(f'  - Instances: {len(instances)} ({len(subject_instances)} subjects, {len(sample_instances)} samples)')

    except ImportError as e:
        pytest.skip(f'Could not import f006 module: {e}')
    except Exception as e:
        print(f'F006 ingestion test failed: {e}')
        raise
    finally:
        # Clean up the path
        if str(ingestion_path) in sys.path:
            sys.path.remove(str(ingestion_path))
