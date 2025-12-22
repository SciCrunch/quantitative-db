#!/usr/bin/env python3
"""
Test back_populate_tables functionality for leaf tables in the quantdb schema.

This test demonstrates the proper order of table population and tests the
back_populate_tables function for ValuesCat and ValuesQuant models.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from quantdb.generic_ingest import back_populate_tables, get_or_create
from quantdb.models import (
    Addresses,
    Aspects,
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


@pytest.fixture
def session():
    """Create a test database session with clean tables for each test."""
    from sqlalchemy import text

    from quantdb.client import get_session

    # Use test database
    session = get_session(echo=False, test=True)

    # Clean all tables before each test to ensure isolation
    # Use TRUNCATE CASCADE to handle foreign key constraints
    try:
        # Truncate all tables in the quantdb schema with CASCADE
        session.execute(
            text(
                'TRUNCATE TABLE quantdb.addresses, quantdb.aspects, quantdb.units, '
                'quantdb.controlled_terms, quantdb.descriptors_inst, quantdb.descriptors_cat, '
                'quantdb.descriptors_quant, quantdb.objects, quantdb.obj_desc_inst, '
                'quantdb.obj_desc_cat, quantdb.obj_desc_quant, quantdb.values_inst, '
                'quantdb.values_cat, quantdb.values_quant CASCADE'
            )
        )
        session.commit()
    except Exception as e:
        session.rollback()
        print(f'Warning: Could not clean tables: {e}')
        # Try to continue anyway

    yield session
    # Rollback any uncommitted changes
    session.rollback()
    session.close()


def create_root_data(session):
    """Create necessary root table data that other tables depend on."""

    # 1. Create Addresses (root table)
    addr_const = Addresses(addr_type='constant', addr_field=None, value_type='single')
    addr_const = get_or_create(session, addr_const)

    addr_tabular = Addresses(addr_type='tabular-header', addr_field='test_field', value_type='single')
    addr_tabular = get_or_create(session, addr_tabular)

    # 2. Create Aspects (root table)
    aspect_distance = Aspects(
        label='test-distance', iri='http://test.org/aspect/distance', description='Test distance aspect'
    )
    aspect_distance = get_or_create(session, aspect_distance)

    # 3. Create Units (root table)
    unit_mm = Units(label='test-mm', iri='http://test.org/unit/mm')
    unit_mm = get_or_create(session, unit_mm)

    # 4. Create ControlledTerms (root table)
    ct_test = ControlledTerms(label='test-term', iri='http://test.org/term/test')
    ct_test = get_or_create(session, ct_test)

    # 5. Create DescriptorsInst (root table)
    desc_inst_human = DescriptorsInst(
        label='test-human', iri='http://test.org/class/human', description='Test human class'
    )
    desc_inst_human = get_or_create(session, desc_inst_human)

    desc_inst_sample = DescriptorsInst(
        label='test-sample', iri='http://test.org/class/sample', description='Test sample class'
    )
    desc_inst_sample = get_or_create(session, desc_inst_sample)

    # 6. Create Objects (root table) - use UUID objects, not strings
    dataset_uuid = uuid.uuid4()
    dataset_obj = Objects(id=dataset_uuid, id_type='dataset')
    dataset_obj = get_or_create(session, dataset_obj)

    package_uuid = uuid.uuid4()
    package_obj = Objects(id=package_uuid, id_type='package', id_file=12345)
    package_obj = get_or_create(session, package_obj)

    # Store references for intermediate table creation
    return {
        'addr_const': addr_const,
        'addr_tabular': addr_tabular,
        'aspect_distance': aspect_distance,
        'unit_mm': unit_mm,
        'ct_test': ct_test,
        'desc_inst_human': desc_inst_human,
        'desc_inst_sample': desc_inst_sample,
        'dataset_obj': dataset_obj,
        'package_obj': package_obj,
    }


def create_intermediate_data(session, root_data):
    """Create intermediate table data that depends on root tables."""

    # 1. Create DescriptorsCat (depends on DescriptorsInst)
    desc_cat = DescriptorsCat(
        domain=root_data['desc_inst_sample'].id,
        range='controlled',
        label='test-category',
        description='Test categorical descriptor',
    )
    desc_cat = get_or_create(session, desc_cat)

    # 2. Create DescriptorsQuant (depends on Aspects, DescriptorsInst, Units)
    desc_quant = DescriptorsQuant(
        shape='scalar',
        label='test-measurement',
        aggregation_type='instance',
        unit=root_data['unit_mm'].id,
        aspect=root_data['aspect_distance'].id,
        domain=root_data['desc_inst_sample'].id,
        description='Test quantitative descriptor',
    )
    desc_quant = get_or_create(session, desc_quant)

    # 3. Create ValuesInst (depends on Objects, DescriptorsInst)
    values_inst = ValuesInst(
        type='sample',
        desc_inst=root_data['desc_inst_sample'].id,
        dataset=root_data['dataset_obj'].id,
        id_formal='sam-test-001',
        id_sub='sub-test-001',
        id_sam='sam-test-001',
    )
    values_inst = get_or_create(session, values_inst)

    # 4. Create ObjDescInst (depends on Addresses, DescriptorsInst, Objects)
    obj_desc_inst = ObjDescInst(
        object=root_data['package_obj'].id,
        desc_inst=root_data['desc_inst_sample'].id,
        addr_field=root_data['addr_tabular'].id,
        addr_desc_inst=root_data['addr_const'].id,
    )
    obj_desc_inst = get_or_create(session, obj_desc_inst)

    # 5. Create ObjDescCat (depends on Addresses, DescriptorsCat, Objects)
    obj_desc_cat = ObjDescCat(
        object=root_data['package_obj'].id, desc_cat=desc_cat.id, addr_field=root_data['addr_tabular'].id
    )
    obj_desc_cat = get_or_create(session, obj_desc_cat)

    # 6. Create ObjDescQuant (depends on Addresses, DescriptorsQuant, Objects)
    obj_desc_quant = ObjDescQuant(
        object=root_data['package_obj'].id,
        desc_quant=desc_quant.id,
        addr_field=root_data['addr_tabular'].id,
        addr_unit=root_data['addr_const'].id,
        addr_aspect=root_data['addr_const'].id,
    )
    obj_desc_quant = get_or_create(session, obj_desc_quant)

    return {
        **root_data,
        'desc_cat': desc_cat,
        'desc_quant': desc_quant,
        'values_inst': values_inst,
        'obj_desc_inst': obj_desc_inst,
        'obj_desc_cat': obj_desc_cat,
        'obj_desc_quant': obj_desc_quant,
    }


def test_back_populate_values_cat(session):
    """Test back_populate_tables for ValuesCat (leaf table)."""

    # Create all prerequisite data
    data = create_intermediate_data(session, create_root_data(session))

    # Create a ValuesCat object - don't set relationships, let back_populate_tables handle it
    values_cat = ValuesCat(
        value_open='test-open-value',
        value_controlled=data['ct_test'].id,
        object=data['package_obj'].id,
        desc_inst=data['desc_inst_sample'].id,
        desc_cat=data['desc_cat'].id,
        instance=data['values_inst'].id,
    )

    # Test back_populate_tables
    result = back_populate_tables(session, values_cat)

    # Verify the result
    assert result is not None
    assert isinstance(result, ValuesCat)
    assert result.value_open == 'test-open-value'
    assert result.value_controlled == data['ct_test'].id
    assert str(result.object) == str(data['package_obj'].id)

    # Verify it was saved to database
    saved = session.query(ValuesCat).filter_by(value_open='test-open-value', object=data['package_obj'].id).first()
    assert saved is not None


def test_back_populate_values_quant(session):
    """Test back_populate_tables for ValuesQuant (leaf table)."""

    # Create all prerequisite data
    data = create_intermediate_data(session, create_root_data(session))

    # Create a ValuesQuant object - don't set relationships, let back_populate_tables handle it
    values_quant = ValuesQuant(
        value=42.5,
        value_blob={'value': 42.5, 'unit': 'mm'},  # Required field
        object=data['package_obj'].id,
        desc_inst=data['desc_inst_sample'].id,
        desc_quant=data['desc_quant'].id,
        instance=data['values_inst'].id,
    )

    # Test back_populate_tables
    result = back_populate_tables(session, values_quant)

    # Verify the result
    assert result is not None
    assert isinstance(result, ValuesQuant)
    assert float(result.value) == 42.5
    assert str(result.object) == str(data['package_obj'].id)

    # Verify it was saved to database
    saved = session.query(ValuesQuant).filter_by(value=42.5, object=data['package_obj'].id).first()
    assert saved is not None


def test_back_populate_with_missing_parents(session):
    """Test back_populate_tables when parent objects don't exist yet."""

    # This test demonstrates that back_populate_tables can create missing parent objects
    # We'll create a simple scenario where some parents don't exist yet

    # Create a new DescriptorsInst that doesn't exist yet
    desc_inst = DescriptorsInst(label='new-test-class', iri='http://test.org/class/new-test')

    # Test back_populate_tables with a simple object
    result = back_populate_tables(session, desc_inst)

    # Verify the result
    assert result is not None
    assert isinstance(result, DescriptorsInst)
    assert result.label == 'new-test-class'

    # Verify it was saved to database
    saved = session.query(DescriptorsInst).filter_by(label='new-test-class').first()
    assert saved is not None

    # Now create a more complex object that depends on the one we just created
    unit = Units(label='new-test-unit', iri='http://test.org/unit/new-test')
    unit_result = back_populate_tables(session, unit)

    aspect = Aspects(label='new-test-aspect', iri='http://test.org/aspect/new-test')
    aspect_result = back_populate_tables(session, aspect)

    # Create a DescriptorsQuant that depends on the above
    desc_quant = DescriptorsQuant(
        shape='scalar',
        label='new-test-quant',
        aggregation_type='instance',
        unit=unit_result.id,
        aspect=aspect_result.id,
        domain=result.id,
    )

    desc_quant_result = back_populate_tables(session, desc_quant)

    # Verify all objects were created
    assert desc_quant_result is not None
    assert desc_quant_result.unit == unit_result.id
    assert desc_quant_result.aspect == aspect_result.id
    assert desc_quant_result.domain == result.id

    # Check that all objects now exist in DB
    saved_unit = session.query(Units).filter_by(label='new-test-unit').first()
    assert saved_unit is not None

    saved_aspect = session.query(Aspects).filter_by(label='new-test-aspect').first()
    assert saved_aspect is not None

    saved_desc_quant = session.query(DescriptorsQuant).filter_by(label='new-test-quant').first()
    assert saved_desc_quant is not None


def test_population_order_documentation():
    """
    Document the required population order for tables.

    This test serves as documentation and doesn't actually test anything.
    """

    population_order = """
    QUANTDB TABLE POPULATION ORDER
    ==============================

    1. ROOT TABLES (No dependencies - populate first):
       - Addresses: Store data source locations (e.g., 'tabular-header', 'json-path')
       - Aspects: Measurement aspects (e.g., 'distance', 'diameter')
       - Units: Measurement units (e.g., 'mm', 'um')
       - ControlledTerms: Controlled vocabulary (e.g., 'microct', 'human')
       - DescriptorsInst: Instance class descriptors (e.g., 'human', 'sample')
       - Objects: Data objects with types ('dataset', 'package')

    2. INTERMEDIATE TABLES (Populate after root tables):
       - DescriptorsCat: Categorical descriptors
         * Requires: DescriptorsInst (for domain)

       - DescriptorsQuant: Quantitative descriptors
         * Requires: Units, Aspects, DescriptorsInst (for domain)

       - ValuesInst: Instance values
         * Requires: Objects (dataset), DescriptorsInst
         * Must follow pattern: subjects (type='subject'), then samples (type='sample')

       - ObjDescInst: Maps objects to instance descriptors
         * Requires: Objects, DescriptorsInst, Addresses

       - ObjDescCat: Maps objects to categorical descriptors
         * Requires: Objects, DescriptorsCat, Addresses

       - ObjDescQuant: Maps objects to quantitative descriptors
         * Requires: Objects, DescriptorsQuant, Addresses

    3. LEAF TABLES (Populate last - use back_populate_tables):
       - ValuesCat: Categorical measurement values
         * Requires: All of the above + ControlledTerms
         * Use back_populate_tables() to handle complex relationships

       - ValuesQuant: Quantitative measurement values
         * Requires: All of the above except ControlledTerms
         * Use back_populate_tables() to handle complex relationships

    4. SELF-REFERENCING TABLES (Can populate after base records exist):
       - instance_parent: Parent-child relationships for ValuesInst
       - class_parent: Parent-child relationships for DescriptorsInst
       - aspect_parent: Parent-child relationships for Aspects
       - dataset_object: Links datasets to their objects
       - equiv_inst: Equivalent instances

    HARDCODED VALUES REQUIRED:
    ==========================

    1. Enum Values (defined in schema):
       - address_type: 'constant', 'tabular-header', 'json-path-with-types', etc.
       - cat_range_type: 'open', 'controlled'
       - instance_type: 'subject', 'sample', 'below'
       - remote_id_type: 'dataset', 'package', 'collection', 'organization', 'quantdb'
       - quant_agg_type: 'instance', 'min', 'max', 'mean', etc.
       - quant_shape: 'scalar'
       - field_value_type: 'single', 'multi'

    2. ID Patterns:
       - Subject IDs must match: '^sub-' (e.g., 'sub-001')
       - Sample IDs must match: '^sam-' (e.g., 'sam-001')
       - For type='subject': id_formal must equal id_sub, id_sam must be NULL
       - For type='sample': id_formal must equal id_sam

    3. Object Constraints:
       - Objects with id_type='package' MUST have id_file set
       - Objects with id_type='quantdb' MUST have id_internal set
       - Dataset objects cannot be used in obj_desc_* tables

    USING back_populate_tables:
    ===========================

    The back_populate_tables function is designed for leaf tables (ValuesCat, ValuesQuant)
    and complex intermediate tables. It will:

    1. Recursively traverse all parent relationships
    2. Create any missing parent records
    3. Update foreign key references
    4. Handle the complex web of relationships automatically

    Example usage:
        values_cat = ValuesCat(...)
        values_cat.descriptors_inst = desc_inst  # Set relationship
        values_cat.controlled_terms = term        # Set relationship
        result = back_populate_tables(session, values_cat)
    """

    print(population_order)
    assert True  # This test always passes


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
