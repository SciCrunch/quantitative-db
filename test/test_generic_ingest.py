"""Tests for quantdb.generic_ingest -- SchemaGraph introspection.

Tests connect to the live ``quantdb_test`` database since
:meth:`SchemaGraph.from_reflected` needs reflected automap models from
a real PostgreSQL schema.

Covers all 8 VAL-SCHEMA assertions from the validation contract.
"""
from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import create_engine, event

from quantdb.generic_ingest import FKInfo, SchemaGraph, TableInfo
from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def reflected() -> Generator[ReflectedModels, None, None]:
    """Reflect the quantdb_test schema once per test module.

    Creates a local engine directly (bypassing orthauth) to guarantee
    a localhost connection.

    Yields:
        ReflectedModels NamedTuple with engine, Session, Base, all 20
        ORM classes, and a SchemaGraph instance.

    Skips all tests in this module if the test database is not reachable.
    """
    engine = create_engine(
        dbUri('quantdb-test-user', 'localhost', 5432, 'quantdb_test'),
    )

    @event.listens_for(engine, 'connect')
    def _set_search_path(
        dbapi_connection: object,
        connection_record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    try:
        models = reflect_models(engine=engine)
    except Exception as e:
        pytest.skip(f'quantdb_test database not available: {e}')

    yield models
    models.engine.dispose()


@pytest.fixture(scope='module')
def schema_graph(reflected: ReflectedModels) -> SchemaGraph:
    """Get the SchemaGraph from reflected models."""
    return reflected.schema_graph


# ---------------------------------------------------------------------------
# VAL-SCHEMA-001: SchemaGraph builds from reflected models
# ---------------------------------------------------------------------------


class TestSchemaGraphBuild:
    """Verify SchemaGraph constructs correctly from reflected models."""

    def test_builds_without_errors(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """SchemaGraph.from_reflected(models) succeeds."""
        assert isinstance(schema_graph, SchemaGraph)

    def test_tables_dict_has_20_entries(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """SchemaGraph.tables has 20 entries (one per quantdb table)."""
        assert len(schema_graph.tables) == 20

    def test_all_table_infos_are_correct_type(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """Every value in tables dict is a TableInfo."""
        for name, info in schema_graph.tables.items():
            assert isinstance(info, TableInfo), (
                f'{name} is {type(info)}, expected TableInfo'
            )


# ---------------------------------------------------------------------------
# VAL-SCHEMA-002: Topological sort produces correct insert order
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    """Verify the topological ordering invariants."""

    ROOT_TABLES: set[str] = {
        'units', 'aspects', 'descriptors_inst',
        'addresses', 'controlled_terms',
    }
    LEAF_TABLES: set[str] = {'values_quant', 'values_cat'}

    def test_root_tables_before_leaf_tables(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """Root tables appear before leaf tables in topo_order."""
        order = schema_graph.topo_order
        for root in self.ROOT_TABLES:
            for leaf in self.LEAF_TABLES:
                assert order.index(root) < order.index(leaf), (
                    f'{root} should come before {leaf}'
                )

    def test_no_table_before_its_dependencies(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """No table appears before any of its FK dependencies."""
        order = schema_graph.topo_order
        for name, info in schema_graph.tables.items():
            for fk_col, fk_info in info.fk_map.items():
                target = fk_info.target_table
                # Skip circular deps (those edges are intentionally broken)
                if frozenset([name, target]) in schema_graph.circular_deps:
                    continue
                assert order.index(target) < order.index(name), (
                    f'{target} should come before {name} (via FK {fk_col})'
                )

    def test_topo_order_contains_all_tables(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """All 20 tables are in the topological order."""
        assert len(schema_graph.topo_order) == 20
        assert set(schema_graph.topo_order) == set(schema_graph.tables.keys())

    def test_topo_levels_are_non_negative(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """Every table has a non-negative topo_level."""
        for name, info in schema_graph.tables.items():
            assert info.topo_level >= 0, f'{name} has topo_level {info.topo_level}'


# ---------------------------------------------------------------------------
# VAL-SCHEMA-003: FK map covers all FK columns
# ---------------------------------------------------------------------------


class TestFKMap:
    """Verify FK map completeness for key tables."""

    def test_descriptors_quant_fk_map(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """descriptors_quant has FK entries for unit, aspect, domain."""
        fk_map = schema_graph.tables['descriptors_quant'].fk_map
        assert 'unit' in fk_map
        assert 'aspect' in fk_map
        assert 'domain' in fk_map
        assert fk_map['unit'].target_table == 'units'
        assert fk_map['aspect'].target_table == 'aspects'
        assert fk_map['domain'].target_table == 'descriptors_inst'

    def test_values_quant_fk_map(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """values_quant has FK entries for object, desc_inst, desc_quant,
        instance."""
        fk_map = schema_graph.tables['values_quant'].fk_map
        assert 'object' in fk_map
        assert 'desc_inst' in fk_map
        assert 'desc_quant' in fk_map
        assert 'instance' in fk_map
        assert fk_map['object'].target_table == 'objects'
        assert fk_map['desc_inst'].target_table == 'descriptors_inst'
        assert fk_map['desc_quant'].target_table == 'descriptors_quant'
        assert fk_map['instance'].target_table == 'values_inst'

    def test_fk_info_has_target_natural_key(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """FKInfo entries include the target table's natural key."""
        fk_info = schema_graph.tables['descriptors_quant'].fk_map['unit']
        assert isinstance(fk_info, FKInfo)
        assert fk_info.target_natural_key == ['label']

    def test_fk_info_has_target_model(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """FKInfo entries include the target ORM model class."""
        fk_info = schema_graph.tables['descriptors_quant'].fk_map['unit']
        assert fk_info.target_model is not None
        assert fk_info.target_model.__name__ == 'Units'

    def test_every_fk_col_has_entry(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """Every single-column FK constraint produces an fk_map entry."""
        for name, info in schema_graph.tables.items():
            for col_name, fk_info in info.fk_map.items():
                assert fk_info.column == col_name
                assert fk_info.target_table in schema_graph.tables, (
                    f'{name}.{col_name} points to unknown table '
                    f'{fk_info.target_table}'
                )


# ---------------------------------------------------------------------------
# VAL-SCHEMA-004: Natural key detection finds correct unique constraints
# ---------------------------------------------------------------------------


class TestNaturalKey:
    """Verify natural key detection for key tables."""

    @pytest.mark.parametrize('table,expected', [
        ('units', ['label']),
        ('aspects', ['label']),
        ('descriptors_inst', ['label']),
        ('controlled_terms', ['label']),
        ('descriptors_quant', ['label']),
    ])
    def test_single_label_natural_key(
        self,
        schema_graph: SchemaGraph,
        table: str,
        expected: list[str],
    ) -> None:
        """Tables with label unique constraint have natural_key=['label']."""
        assert schema_graph.tables[table].natural_key == expected

    def test_addresses_natural_key(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """addresses has composite natural key."""
        assert schema_graph.tables['addresses'].natural_key == [
            'addr_type', 'addr_field', 'value_type',
        ]

    def test_values_inst_natural_key(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """values_inst has natural_key=['dataset', 'id_formal']."""
        assert schema_graph.tables['values_inst'].natural_key == [
            'dataset', 'id_formal',
        ]


# ---------------------------------------------------------------------------
# VAL-SCHEMA-005: Circular dependency detected
# ---------------------------------------------------------------------------


class TestCircularDeps:
    """Verify circular dependency detection."""

    def test_circular_deps_non_empty(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """At least one circular dependency detected."""
        assert len(schema_graph.circular_deps) > 0

    def test_objects_objects_internal_pair(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """objects <-> objects_internal pair is in circular_deps."""
        expected = frozenset(['objects', 'objects_internal'])
        assert expected in schema_graph.circular_deps


# ---------------------------------------------------------------------------
# VAL-SCHEMA-006: Table classification is correct
# ---------------------------------------------------------------------------


class TestTableClassification:
    """Verify lookup vs create table classification."""

    @pytest.mark.parametrize('table', [
        'units', 'aspects', 'descriptors_inst',
        'controlled_terms', 'addresses',
    ])
    def test_lookup_tables(
        self,
        schema_graph: SchemaGraph,
        table: str,
    ) -> None:
        """Pre-populated tables have is_lookup=True."""
        assert schema_graph.tables[table].is_lookup is True

    @pytest.mark.parametrize('table', [
        'values_quant', 'values_cat', 'values_inst', 'objects',
    ])
    def test_data_tables(
        self,
        schema_graph: SchemaGraph,
        table: str,
    ) -> None:
        """Data tables have is_lookup=False."""
        assert schema_graph.tables[table].is_lookup is False


# ---------------------------------------------------------------------------
# VAL-SCHEMA-007: Association tables handled
# ---------------------------------------------------------------------------


class TestAssociationTables:
    """Verify all 5 association tables are present with correct PKs."""

    ASSOCIATION_TABLES: dict[str, set[str]] = {
        'dataset_object': {'dataset', 'object'},
        'equiv_inst': {'left_thing', 'right_thing'},
        'class_parent': {'id', 'parent'},
        'instance_parent': {'id', 'parent'},
        'aspect_parent': {'id', 'parent'},
    }

    @pytest.mark.parametrize(
        'table,expected_pk',
        list(ASSOCIATION_TABLES.items()),
    )
    def test_association_table_present_with_correct_pk(
        self,
        schema_graph: SchemaGraph,
        table: str,
        expected_pk: set[str],
    ) -> None:
        """Association table is in SchemaGraph with correct composite PK."""
        assert table in schema_graph.tables
        assert set(schema_graph.tables[table].pk_cols) == expected_pk

    def test_all_five_association_tables(
        self,
        schema_graph: SchemaGraph,
    ) -> None:
        """All 5 association tables are present."""
        for table in self.ASSOCIATION_TABLES:
            assert table in schema_graph.tables


# ---------------------------------------------------------------------------
# VAL-SCHEMA-008: SchemaGraph on ReflectedModels
# ---------------------------------------------------------------------------


class TestReflectedModelsIntegration:
    """Verify SchemaGraph is integrated into ReflectedModels."""

    def test_schema_graph_field_exists(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """ReflectedModels has a schema_graph field."""
        assert hasattr(reflected, 'schema_graph')

    def test_schema_graph_is_correct_type(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """schema_graph is a SchemaGraph instance (not None)."""
        assert isinstance(reflected.schema_graph, SchemaGraph)

    def test_schema_graph_not_none(
        self,
        reflected: ReflectedModels,
    ) -> None:
        """schema_graph is not None after reflect_models()."""
        assert reflected.schema_graph is not None
