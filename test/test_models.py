"""Tests for quantdb.models -- automap_base ORM reflection.

Demonstrates connecting to the test database, reflecting the schema into
CamelCase ORM classes, and performing basic queries.

Requires a running ``quantdb_test`` PostgreSQL database with the quantdb
schema.  Tests that need the database are automatically skipped if the
database is unreachable.
"""
from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import Integer, Numeric, select
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

from quantdb.models import (
    ReflectedModels,
    _ASSOCIATION_TABLE_NAMES,
    _snake_to_camel,
    reflect_models,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def reflected(rebuild_database) -> Generator[ReflectedModels, None, None]:
    """Reflect the quantdb_test schema once per test module.

    Depends on ``rebuild_database`` (session-scoped) to ensure
    pg_restore has populated lookup tables before any test runs.

    Yields:
        ReflectedModels NamedTuple with engine, Session, Base, and all
        20 ORM classes.

    Skips all tests in this module if the test database is not reachable.
    """
    try:
        models = reflect_models(test=True)
    except Exception as e:
        pytest.skip(f'quantdb_test database not available: {e}')
    yield models
    models.engine.dispose()


@pytest.fixture
def session(reflected: ReflectedModels) -> Generator[None, None, None]:
    """Provide a fresh session per test, rolled back after each test.

    This ensures tests don't pollute each other or modify the test
    database.
    """
    sess = reflected.Session()
    yield sess
    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# Unit tests -- no database required
# ---------------------------------------------------------------------------


class TestCamelCaseNaming:
    """Unit tests for the _snake_to_camel naming function."""

    @pytest.mark.parametrize(
        'snake,camel',
        [
            ('objects', 'Objects'),
            ('objects_internal', 'ObjectsInternal'),
            ('dataset_object', 'DatasetObject'),
            ('values_quant', 'ValuesQuant'),
            ('values_inst', 'ValuesInst'),
            ('values_cat', 'ValuesCat'),
            ('obj_desc_inst', 'ObjDescInst'),
            ('obj_desc_quant', 'ObjDescQuant'),
            ('obj_desc_cat', 'ObjDescCat'),
            ('equiv_inst', 'EquivInst'),
            ('controlled_terms', 'ControlledTerms'),
            ('descriptors_inst', 'DescriptorsInst'),
            ('descriptors_cat', 'DescriptorsCat'),
            ('descriptors_quant', 'DescriptorsQuant'),
            ('units', 'Units'),
            ('aspects', 'Aspects'),
            ('addresses', 'Addresses'),
            ('class_parent', 'ClassParent'),
            ('instance_parent', 'InstanceParent'),
            ('aspect_parent', 'AspectParent'),
        ],
    )
    def test_snake_to_camel(self, snake: str, camel: str) -> None:
        """Verify snake_case -> CamelCase conversion for all table names."""
        assert _snake_to_camel(snake) == camel


# ---------------------------------------------------------------------------
# Database-dependent tests
# ---------------------------------------------------------------------------


class TestSchemaReflection:
    """Verify that all expected tables are reflected as ORM classes."""

    #: The 15 regular tables that automap generates classes for.
    AUTOMAP_CLASSES: set[str] = {
        'ObjectsInternal',
        'Objects',
        'Units',
        'Aspects',
        'DescriptorsInst',
        'DescriptorsCat',
        'DescriptorsQuant',
        'ValuesInst',
        'ValuesQuant',
        'ValuesCat',
        'ControlledTerms',
        'Addresses',
        'ObjDescInst',
        'ObjDescQuant',
        'ObjDescCat',
    }

    #: The 5 association tables pre-declared before prepare().
    ASSOC_CLASSES: set[str] = {
        _snake_to_camel(n) for n in _ASSOCIATION_TABLE_NAMES
    }

    ALL_CLASSES: set[str] = AUTOMAP_CLASSES | ASSOC_CLASSES

    def test_automap_classes_in_base(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """15 regular tables should produce classes in Base.classes."""
        actual = {cls.__name__ for cls in reflected.Base.classes}
        assert self.AUTOMAP_CLASSES.issubset(actual), (
            f'Missing classes: {self.AUTOMAP_CLASSES - actual}'
        )

    def test_association_classes_on_namedtuple(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """5 association-table classes should be on the NamedTuple."""
        for name in self.ASSOC_CLASSES:
            cls = getattr(reflected, name)
            assert cls is not None, f'{name} not found on ReflectedModels'
            assert cls.__name__ == name

    def test_all_20_classes_accessible(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """All 20 quantdb tables should be accessible as NamedTuple fields."""
        for name in self.ALL_CLASSES:
            cls = getattr(reflected, name)
            assert cls is not None, f'{name} missing from ReflectedModels'

    def test_regular_classes_match_base_classes(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """NamedTuple fields for regular tables should be the same objects
        as Base.classes attributes.
        """
        assert reflected.ValuesQuant is reflected.Base.classes.ValuesQuant
        assert reflected.Objects is reflected.Base.classes.Objects
        assert reflected.Units is reflected.Base.classes.Units


class TestColumnTypes:
    """Verify that reflected column types match expectations."""

    def test_objects_id_is_uuid(self, reflected: ReflectedModels) -> None:
        """objects.id should be a UUID column."""
        col = reflected.Objects.__table__.c.id
        assert isinstance(col.type, UUID)

    def test_values_quant_value_is_numeric(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """values_quant.value should be Numeric."""
        col = reflected.ValuesQuant.__table__.c.value
        assert isinstance(col.type, Numeric)

    def test_values_quant_value_blob_is_jsonb(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """values_quant.value_blob should be JSONB."""
        col = reflected.ValuesQuant.__table__.c.value_blob
        assert isinstance(col.type, JSONB)

    def test_objects_id_type_is_enum(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """objects.id_type should be an ENUM (remote_id_type)."""
        col = reflected.Objects.__table__.c.id_type
        assert isinstance(col.type, ENUM)

    def test_units_id_is_integer(self, reflected: ReflectedModels) -> None:
        """units.id should be an Integer type."""
        col = reflected.Units.__table__.c.id
        assert isinstance(col.type, Integer)

    def test_values_inst_has_all_expected_columns(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """values_inst should have the expected set of columns."""
        cols = {c.name for c in reflected.ValuesInst.__table__.columns}
        expected = {
            'id',
            'type',
            'desc_inst',
            'dataset',
            'id_formal',
            'local_identifier',
            'id_sub',
            'id_sam',
        }
        assert expected.issubset(cols), (
            f'Missing columns: {expected - cols}'
        )


class TestBasicQueries:
    """Demonstrate basic ORM queries against the test database."""

    def test_select_all_units(
        self,
        session,
        reflected: ReflectedModels,
    ) -> None:
        """Query all units -- should return rows if test data is loaded."""
        stmt = select(reflected.Units)
        results = session.execute(stmt).scalars().all()
        assert isinstance(results, list)

    def test_select_objects_with_filter(
        self,
        session,
        reflected: ReflectedModels,
    ) -> None:
        """Filter objects by id_type enum value."""
        stmt = select(reflected.Objects).where(
            reflected.Objects.id_type == 'dataset'
        )
        results = session.execute(stmt).scalars().all()
        assert isinstance(results, list)

    def test_select_descriptors_quant_join_units(
        self,
        session,
        reflected: ReflectedModels,
    ) -> None:
        """Join descriptors_quant to units via FK."""
        DQ = reflected.DescriptorsQuant
        U = reflected.Units
        stmt = select(DQ, U.label).join(U, DQ.unit == U.id)
        results = session.execute(stmt).all()
        assert isinstance(results, list)

    def test_select_values_quant_with_value_filter(
        self,
        session,
        reflected: ReflectedModels,
    ) -> None:
        """Filter values_quant by value range."""
        VQ = reflected.ValuesQuant
        stmt = select(VQ).where(VQ.value >= 0)
        results = session.execute(stmt).scalars().all()
        assert isinstance(results, list)

    def test_select_association_table(
        self,
        session,
        reflected: ReflectedModels,
    ) -> None:
        """Query a pre-declared association table (dataset_object)."""
        DO = reflected.DatasetObject
        stmt = select(DO)
        results = session.execute(stmt).scalars().all()
        assert isinstance(results, list)


class TestRelationships:
    """Verify that automap generated FK-based relationships."""

    def test_values_quant_has_object_relationship(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """ValuesQuant should have a relationship to Objects via FK."""
        rels = reflected.ValuesQuant.__mapper__.relationships
        rel_targets = {r.target.name for r in rels}
        assert 'objects' in rel_targets

    def test_descriptors_quant_has_units_relationship(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """DescriptorsQuant should have a relationship to Units."""
        rels = reflected.DescriptorsQuant.__mapper__.relationships
        rel_targets = {r.target.name for r in rels}
        assert 'units' in rel_targets

    def test_descriptors_quant_has_aspects_relationship(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """DescriptorsQuant should have a relationship to Aspects."""
        rels = reflected.DescriptorsQuant.__mapper__.relationships
        rel_targets = {r.target.name for r in rels}
        assert 'aspects' in rel_targets

    def test_values_inst_has_descriptors_inst_relationship(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """ValuesInst should have a relationship to DescriptorsInst."""
        rels = reflected.ValuesInst.__mapper__.relationships
        rel_targets = {r.target.name for r in rels}
        assert 'descriptors_inst' in rel_targets


class TestCompositePrimaryKeys:
    """Verify composite PKs on junction/hierarchy tables."""

    def test_dataset_object_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """dataset_object PK should be (dataset, object)."""
        pk_cols = {
            c.name for c in reflected.DatasetObject.__table__.primary_key
        }
        assert pk_cols == {'dataset', 'object'}

    def test_equiv_inst_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """equiv_inst PK should be (left_thing, right_thing)."""
        pk_cols = {
            c.name for c in reflected.EquivInst.__table__.primary_key
        }
        assert pk_cols == {'left_thing', 'right_thing'}

    def test_class_parent_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """class_parent PK should be (id, parent)."""
        pk_cols = {
            c.name for c in reflected.ClassParent.__table__.primary_key
        }
        assert pk_cols == {'id', 'parent'}

    def test_obj_desc_inst_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """obj_desc_inst PK should be (object, desc_inst)."""
        pk_cols = {
            c.name for c in reflected.ObjDescInst.__table__.primary_key
        }
        assert pk_cols == {'object', 'desc_inst'}

    def test_instance_parent_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """instance_parent PK should be (id, parent)."""
        pk_cols = {
            c.name for c in reflected.InstanceParent.__table__.primary_key
        }
        assert pk_cols == {'id', 'parent'}

    def test_aspect_parent_has_composite_pk(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """aspect_parent PK should be (id, parent)."""
        pk_cols = {
            c.name for c in reflected.AspectParent.__table__.primary_key
        }
        assert pk_cols == {'id', 'parent'}
