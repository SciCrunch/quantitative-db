#!/usr/bin/env python3
"""
Simple test for back_populate_tables functionality without complex relationships.
"""

import uuid

import pytest
from sqlalchemy import text

from quantdb.client import get_session
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
    session = get_session(echo=False, test=True)

    # Clean all tables before each test
    try:
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

    yield session
    session.rollback()
    session.close()


def test_back_populate_simple_values_cat(session):
    """Test back_populate_tables with a simple ValuesCat object."""

    # Create minimal required data
    ct = ControlledTerms(label='test-term', iri='http://test.org/term')
    ct = get_or_create(session, ct)

    desc_inst = DescriptorsInst(label='test-class', iri='http://test.org/class')
    desc_inst = get_or_create(session, desc_inst)

    desc_cat = DescriptorsCat(domain=desc_inst.id, range='controlled', label='test-category')
    desc_cat = get_or_create(session, desc_cat)

    # Create address for mappings
    addr = Addresses(addr_type='constant', addr_field=None, value_type='single')
    addr = get_or_create(session, addr)

    # Create dataset object (required for ValuesInst)
    dataset_obj = Objects(id=uuid.uuid4(), id_type='dataset')
    dataset_obj = get_or_create(session, dataset_obj)

    # Create package object (required for ValuesCat)
    package_obj = Objects(id=uuid.uuid4(), id_type='package', id_file=12345)
    package_obj = get_or_create(session, package_obj)

    # Create required intermediate mappings
    obj_desc_inst = ObjDescInst(object=package_obj.id, desc_inst=desc_inst.id, addr_field=addr.id)
    obj_desc_inst = get_or_create(session, obj_desc_inst)

    obj_desc_cat = ObjDescCat(object=package_obj.id, desc_cat=desc_cat.id, addr_field=addr.id)
    obj_desc_cat = get_or_create(session, obj_desc_cat)

    # Create values_inst (uses dataset, not package)
    values_inst = ValuesInst(
        type='subject', id_sub='sub-001', desc_inst=desc_inst.id, dataset=dataset_obj.id, id_formal='sub-001'
    )
    values_inst = get_or_create(session, values_inst)

    # Create ValuesCat object without setting relationships (uses package)
    values_cat = ValuesCat(
        value_open='test-value',
        value_controlled=ct.id,
        object=package_obj.id,
        desc_inst=desc_inst.id,
        desc_cat=desc_cat.id,
        instance=values_inst.id,
    )

    # Test back_populate_tables
    result = back_populate_tables(session, values_cat)

    # Verify the result
    assert result is not None
    assert isinstance(result, ValuesCat)
    assert result.value_open == 'test-value'
    assert result.value_controlled == ct.id
    assert str(result.object) == str(package_obj.id)

    print('✓ Simple back_populate_tables test passed')


def test_back_populate_simple_values_quant(session):
    """Test back_populate_tables with a simple ValuesQuant object."""

    # Create minimal required data
    aspect = Aspects(label='test-aspect', iri='http://test.org/aspect')
    aspect = get_or_create(session, aspect)

    unit = Units(label='test-unit', iri='http://test.org/unit')
    unit = get_or_create(session, unit)

    desc_inst = DescriptorsInst(label='test-class', iri='http://test.org/class')
    desc_inst = get_or_create(session, desc_inst)

    desc_quant = DescriptorsQuant(
        label='test-quantitative',
        unit=unit.id,
        aspect=aspect.id,
        domain=desc_inst.id,
        shape='scalar',
        aggregation_type='instance',
    )
    desc_quant = get_or_create(session, desc_quant)

    # Create address for mappings
    addr = Addresses(addr_type='constant', addr_field=None, value_type='single')
    addr = get_or_create(session, addr)

    # Create dataset object (required for ValuesInst)
    dataset_obj = Objects(id=uuid.uuid4(), id_type='dataset')
    dataset_obj = get_or_create(session, dataset_obj)

    # Create package object (required for ValuesQuant)
    package_obj = Objects(id=uuid.uuid4(), id_type='package', id_file=12345)
    package_obj = get_or_create(session, package_obj)

    # Create required intermediate mappings
    obj_desc_inst = ObjDescInst(object=package_obj.id, desc_inst=desc_inst.id, addr_field=addr.id)
    obj_desc_inst = get_or_create(session, obj_desc_inst)

    obj_desc_quant = ObjDescQuant(object=package_obj.id, desc_quant=desc_quant.id, addr_field=addr.id)
    obj_desc_quant = get_or_create(session, obj_desc_quant)

    # Create values_inst (uses dataset, not package)
    values_inst = ValuesInst(
        type='subject', id_sub='sub-001', desc_inst=desc_inst.id, dataset=dataset_obj.id, id_formal='sub-001'
    )
    values_inst = get_or_create(session, values_inst)

    # Create ValuesQuant object with required value_blob field
    values_quant = ValuesQuant(
        value=42.5,
        value_blob={'value': 42.5, 'unit': 'test-unit'},
        object=package_obj.id,
        desc_inst=desc_inst.id,
        desc_quant=desc_quant.id,
        instance=values_inst.id,  # Required field
    )

    # Test back_populate_tables
    result = back_populate_tables(session, values_quant)

    # Verify the result
    assert result is not None
    assert isinstance(result, ValuesQuant)
    assert float(result.value) == 42.5
    assert str(result.object) == str(package_obj.id)

    print('✓ Simple back_populate_tables test passed')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
