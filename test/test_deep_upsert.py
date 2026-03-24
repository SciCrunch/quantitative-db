"""Integration tests for deep upsert primitives.

Tests ``get_or_create``, ``resolve_fk_value``, and ``deep_upsert``
against a live ``quantdb_test`` PostgreSQL database on localhost:5432.

Covers VAL-UPSERT assertions from the validation contract.  Every test
uses ``session.rollback()`` in teardown so no test data persists.

Requires:
    - PostgreSQL running on localhost:5432 (trust auth)
    - ``quantdb_test`` database with reference data loaded
"""
from __future__ import annotations

import uuid
from typing import Any, Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from quantdb.generic_ingest import (
    FKCache,
    SchemaGraph,
    deep_upsert,
    get_or_create,
    resolve_fk_value,
)
from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

F006_UUID = '2a3d01c0-39d3-464a-8746-54c9d67ebe0f'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def reflected() -> Generator[ReflectedModels, None, None]:
    """Reflect the quantdb_test schema once per module.

    Uses an explicit localhost engine to avoid the orthauth → AWS
    redirect.  Skips all tests if the database is unreachable.
    """
    try:
        engine = create_engine(
            dbUri(
                dbuser='quantdb-test-user',
                host='localhost',
                port=5432,
                database='quantdb_test',
            ),
        )

        @event.listens_for(engine, 'connect')
        def _set_search_path(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('SET search_path TO quantdb, public')
            cursor.close()

        models = reflect_models(engine=engine)
    except Exception as e:
        pytest.skip(f'quantdb_test database not available: {e}')
    yield models
    models.engine.dispose()


@pytest.fixture(scope='module')
def schema(reflected: ReflectedModels) -> SchemaGraph:
    """Convenience accessor for the SchemaGraph."""
    assert reflected.schema_graph is not None
    return reflected.schema_graph


@pytest.fixture
def session(reflected: ReflectedModels) -> Generator[Session, None, None]:
    """Provide a fresh session per test, rolled back after each test."""
    sess = reflected.Session()
    yield sess
    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# Helper to look up reference data IDs
# ---------------------------------------------------------------------------


def _lookup_id(
    session: Session,
    Model: type,
    col_name: str,
    value: Any,
) -> Any:
    """Look up a single row's PK by a column value."""
    table = Model.__table__
    pk_col = list(table.primary_key.columns)[0]
    stmt = select(pk_col).where(table.c[col_name] == value)
    return session.execute(stmt).scalar_one()


# ---------------------------------------------------------------------------
# VAL-UPSERT-001: String FK resolved to integer PK
# ---------------------------------------------------------------------------


class TestStringFKResolution:
    """resolve_fk_value resolves 'um' → units.id integer."""

    def test_string_fk_resolved_to_integer(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-001: 'um' on descriptors_quant.unit → units.id."""
        cache: FKCache = {}
        result = resolve_fk_value(
            session,
            schema,
            'descriptors_quant',
            'unit',
            'um',
            cache,
        )
        expected_id = _lookup_id(session, reflected.Units, 'label', 'um')
        assert result == expected_id
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# VAL-UPSERT-002: Dict FK resolved via composite natural key
# ---------------------------------------------------------------------------


class TestDictFKResolution:
    """resolve_fk_value resolves dict to composite natural key lookup."""

    def test_dict_fk_resolved_composite(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-002: dict with dataset+id_formal → values_inst.id."""
        # Find an existing values_inst row to use as test data
        VI = reflected.ValuesInst
        existing = session.execute(
            select(VI).where(VI.dataset == F006_UUID).limit(1),
        ).scalar_one()
        dataset_uuid = str(existing.dataset)
        id_formal = existing.id_formal

        cache: FKCache = {}
        # values_quant.instance is FK to values_inst
        result = resolve_fk_value(
            session,
            schema,
            'values_quant',
            'instance',
            {'dataset': dataset_uuid, 'id_formal': id_formal},
            cache,
        )
        assert result == existing.id
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# VAL-UPSERT-003: Pre-resolved FK values passed through
# ---------------------------------------------------------------------------


class TestPassthroughFKValues:
    """resolve_fk_value passes through int/UUID values unchanged."""

    def test_int_passthrough(
        self,
        session: Session,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-003: integer FK value passed through."""
        cache: FKCache = {}
        result = resolve_fk_value(
            session,
            schema,
            'descriptors_quant',
            'unit',
            42,
            cache,
        )
        assert result == 42

    def test_uuid_passthrough(
        self,
        session: Session,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-003: UUID FK value passed through."""
        cache: FKCache = {}
        test_uuid = uuid.UUID(F006_UUID)
        result = resolve_fk_value(
            session,
            schema,
            'values_quant',
            'object',
            test_uuid,
            cache,
        )
        assert result == test_uuid

    def test_none_passthrough(
        self,
        session: Session,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-003: None FK value passed through."""
        cache: FKCache = {}
        result = resolve_fk_value(
            session,
            schema,
            'descriptors_quant',
            'domain',
            None,
            cache,
        )
        assert result is None


# ---------------------------------------------------------------------------
# VAL-UPSERT-004: Recursive FK resolution
# ---------------------------------------------------------------------------


class TestRecursiveFKResolution:
    """deep_upsert recursively resolves nested FK dicts."""

    def test_recursive_fk_resolution(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-004: nested string FKs on descriptors_quant.

        Look up an existing descriptors_quant row with string values for
        unit and aspect — deep_upsert should resolve both to integers.
        """
        DQ = reflected.DescriptorsQuant

        # Use 'count' descriptor: unit='unitless', aspect='count', domain=None
        cache: FKCache = {}
        result = deep_upsert(
            session,
            DQ,
            schema,
            {
                'label': 'count',
                'unit': 'unitless',
                'aspect': 'count',
                'domain': None,
                'shape': 'scalar',
                'aggregation_type': 'instance',
            },
            cache,
        )

        # Verify FK values are resolved integers
        unit_id = _lookup_id(session, reflected.Units, 'label', 'unitless')
        aspect_id = _lookup_id(session, reflected.Aspects, 'label', 'count')
        assert result.unit == unit_id
        assert result.aspect == aspect_id
        assert result.label == 'count'


# ---------------------------------------------------------------------------
# VAL-UPSERT-005: get_or_create is idempotent
# ---------------------------------------------------------------------------


class TestGetOrCreateIdempotent:
    """get_or_create returns same row on repeated calls."""

    def test_idempotent_same_pk(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-005: two calls return same PK, second created=False."""
        Units = reflected.Units
        nk = schema.tables['units'].natural_key  # ['label']

        inst1, created1 = get_or_create(
            session,
            Units,
            nk,
            {'label': 'um'},
        )
        inst2, created2 = get_or_create(
            session,
            Units,
            nk,
            {'label': 'um'},
        )

        assert inst1.id == inst2.id
        # First call finds existing row — not a new creation
        assert created1 is False
        assert created2 is False


# ---------------------------------------------------------------------------
# VAL-UPSERT-006: Nullable FK columns handled
# ---------------------------------------------------------------------------


class TestNullableFKHandled:
    """deep_upsert handles domain=None on descriptors_quant."""

    def test_nullable_fk_domain_none(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-006: domain=None stores NULL, lookup finds it."""
        DQ = reflected.DescriptorsQuant
        cache: FKCache = {}

        # 'count' has domain=NULL in the DB
        result = deep_upsert(
            session,
            DQ,
            schema,
            {
                'label': 'count',
                'unit': 'unitless',
                'aspect': 'count',
                'domain': None,
            },
            cache,
        )
        assert result.domain is None

        # Second call finds the same row
        result2 = deep_upsert(
            session,
            DQ,
            schema,
            {
                'label': 'count',
                'unit': 'unitless',
                'aspect': 'count',
                'domain': None,
            },
            cache,
        )
        assert result2.id == result.id


# ---------------------------------------------------------------------------
# VAL-UPSERT-007: Cache prevents redundant queries
# ---------------------------------------------------------------------------


class TestCachePreventsRedundantQueries:
    """Shared cache across batch prevents redundant SELECTs."""

    def test_cache_shared_across_calls(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-007: 10 rows share 1 FK lookup via cache.

        Resolve 'um' via unit FK 10 times with a shared cache.  The
        cache should contain the mapping after the first call, and all
        subsequent calls use the cached value.
        """
        cache: FKCache = {}

        for _ in range(10):
            resolve_fk_value(
                session,
                schema,
                'descriptors_quant',
                'unit',
                'um',
                cache,
            )

        # The cache should contain the 'um' entry (only 1 lookup needed)
        um_key = ('units', frozenset({('label', 'um')}))
        assert um_key in cache
        # Cache size should be exactly 1 (not 10)
        assert len(cache) == 1


# ---------------------------------------------------------------------------
# VAL-UPSERT-008: ENUM columns accepted as strings
# ---------------------------------------------------------------------------


class TestEnumColumnsAsStrings:
    """deep_upsert handles ENUM columns as plain strings."""

    def test_enum_string_values(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-008: shape='scalar', aggregation_type='instance'."""
        DQ = reflected.DescriptorsQuant
        cache: FKCache = {}

        result = deep_upsert(
            session,
            DQ,
            schema,
            {
                'label': 'count',
                'unit': 'unitless',
                'aspect': 'count',
                'shape': 'scalar',
                'aggregation_type': 'instance',
            },
            cache,
        )

        assert result.shape == 'scalar'
        assert result.aggregation_type == 'instance'


# ---------------------------------------------------------------------------
# VAL-UPSERT-009: Trigger ordering enforced automatically
# ---------------------------------------------------------------------------


class TestTriggerOrdering:
    """deep_upsert auto-creates prerequisite rows for trigger ordering."""

    def test_auto_creates_obj_desc_inst_for_obj_desc_quant(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-009: obj_desc_quant auto-ensures obj_desc_inst.

        Use an existing non-dataset object that has no
        ``obj_desc_inst`` rows.  Then call ``deep_upsert`` on
        ``obj_desc_quant`` — the system should auto-create
        ``obj_desc_inst`` before inserting ``obj_desc_quant``
        (which fires the ``check_desc_inst_exists`` trigger).
        """
        Objects = reflected.Objects
        ODQ = reflected.ObjDescQuant
        ODI = reflected.ObjDescInst

        # Find an existing non-dataset object with NO obj_desc_inst
        obj = session.execute(
            select(Objects)
            .where(
                Objects.id_type != 'dataset',
                ~Objects.id.in_(
                    select(ODI.__table__.c.object),
                ),
            )
            .limit(1),
        ).scalar_one_or_none()
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        fresh_uuid = obj.id

        # Verify no obj_desc_inst for this new object
        check = session.execute(
            select(ODI).where(ODI.__table__.c.object == fresh_uuid),
        ).scalar_one_or_none()
        assert check is None

        # Pick a desc_quant with a non-NULL domain for domain→desc_inst
        # derivation.  'fascicle cross section diameter um' has
        # domain=25 (fascicle-cross-section).
        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.isnot(None)).limit(1),
        ).scalar_one()

        # deep_upsert on obj_desc_quant should auto-create obj_desc_inst
        # using the desc_quant's domain as desc_inst
        cache: FKCache = {}
        result = deep_upsert(
            session,
            ODQ,
            schema,
            {
                'object': fresh_uuid,
                'desc_quant': dq.id,
                'addr_field': 1,
            },
            cache,
        )
        assert result is not None

        # Verify obj_desc_inst was auto-created for this object
        odi = session.execute(
            select(ODI).where(ODI.__table__.c.object == fresh_uuid).limit(1),
        ).scalar_one_or_none()
        assert odi is not None

    def test_values_quant_auto_creates_both_prerequisites(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-009: values_quant auto-creates obj_desc_inst AND
        obj_desc_quant without pre-creation.

        Insert a fresh ``values_quant`` row via ``deep_upsert`` for an
        object that has NO ``obj_desc_inst`` or ``obj_desc_quant`` rows.
        The system must auto-create both prerequisite rows.
        """
        Objects = reflected.Objects
        VQ = reflected.ValuesQuant
        ODI = reflected.ObjDescInst
        ODQ = reflected.ObjDescQuant

        # Find a non-dataset object with NO obj_desc_inst rows
        obj = session.execute(
            select(Objects)
            .where(
                Objects.id_type != 'dataset',
                ~Objects.id.in_(
                    select(ODI.__table__.c.object),
                ),
            )
            .limit(1),
        ).scalar_one_or_none()
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        fresh_uuid = obj.id

        # Verify no obj_desc_inst and no obj_desc_quant for this object
        assert (
            session.execute(
                select(ODI).where(ODI.__table__.c.object == fresh_uuid),
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(ODQ).where(ODQ.__table__.c.object == fresh_uuid),
            ).scalar_one_or_none()
            is None
        )

        # Use an existing values_inst row and a desc_quant with
        # domain=NULL so the values_quant_check_before trigger passes
        # for any desc_inst.
        VI = reflected.ValuesInst
        vi = session.execute(select(VI).limit(1)).scalar_one()

        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        # deep_upsert on values_quant — NO pre-created obj_desc_inst
        # or obj_desc_quant.
        cache: FKCache = {}
        result = deep_upsert(
            session,
            VQ,
            schema,
            {
                'value': 42.0,
                'value_blob': 42.0,
                'object': fresh_uuid,
                'desc_inst': vi.desc_inst,
                'desc_quant': dq.id,
                'instance': vi.id,
            },
            cache,
        )
        assert result is not None
        assert result.value == 42.0
        assert result.object == fresh_uuid

        # Verify obj_desc_inst was auto-created
        odi = session.execute(
            select(ODI).where(ODI.__table__.c.object == fresh_uuid).limit(1),
        ).scalar_one_or_none()
        assert odi is not None, 'obj_desc_inst should have been auto-created'

        # Verify obj_desc_quant was auto-created
        odq = session.execute(
            select(ODQ)
            .where(
                ODQ.__table__.c.object == fresh_uuid,
                ODQ.__table__.c.desc_quant == dq.id,
            )
            .limit(1),
        ).scalar_one_or_none()
        assert odq is not None, 'obj_desc_quant should have been auto-created'

    def test_values_cat_auto_creates_both_prerequisites(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-009: values_cat auto-creates obj_desc_inst AND
        obj_desc_cat without pre-creation.

        Insert a fresh ``values_cat`` row via ``deep_upsert`` for an
        object that has NO ``obj_desc_inst`` or ``obj_desc_cat`` rows.
        The system must auto-create both prerequisite rows.
        """
        Objects = reflected.Objects
        VC = reflected.ValuesCat
        ODI = reflected.ObjDescInst
        ODC = reflected.ObjDescCat

        # Find a non-dataset object with NO obj_desc_inst rows
        obj = session.execute(
            select(Objects)
            .where(
                Objects.id_type != 'dataset',
                ~Objects.id.in_(
                    select(ODI.__table__.c.object),
                ),
            )
            .limit(1),
        ).scalar_one_or_none()
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        fresh_uuid = obj.id

        # Verify no obj_desc_inst and no obj_desc_cat for this object
        assert (
            session.execute(
                select(ODI).where(ODI.__table__.c.object == fresh_uuid),
            ).scalar_one_or_none()
            is None
        )
        assert (
            session.execute(
                select(ODC).where(ODC.__table__.c.object == fresh_uuid),
            ).scalar_one_or_none()
            is None
        )

        # Use an existing values_inst row
        VI = reflected.ValuesInst
        vi = session.execute(select(VI).limit(1)).scalar_one()

        # Use a desc_cat with domain=NULL so desc_inst check passes
        DC = reflected.DescriptorsCat
        dc = session.execute(
            select(DC).where(DC.domain.is_(None)).limit(1),
        ).scalar_one()

        # Find a controlled_term for the value_controlled field
        CT = reflected.ControlledTerms
        ct = session.execute(select(CT).limit(1)).scalar_one()

        # deep_upsert on values_cat — NO pre-created obj_desc_inst
        # or obj_desc_cat.
        cache: FKCache = {}
        result = deep_upsert(
            session,
            VC,
            schema,
            {
                'value_open': ct.label,
                'value_controlled': ct.id,
                'object': fresh_uuid,
                'desc_inst': vi.desc_inst,
                'desc_cat': dc.id,
                'instance': vi.id,
            },
            cache,
        )
        assert result is not None
        assert result.object == fresh_uuid

        # Verify obj_desc_inst was auto-created
        odi = session.execute(
            select(ODI).where(ODI.__table__.c.object == fresh_uuid).limit(1),
        ).scalar_one_or_none()
        assert odi is not None, 'obj_desc_inst should have been auto-created'

        # Verify obj_desc_cat was auto-created
        odc = session.execute(
            select(ODC)
            .where(
                ODC.__table__.c.object == fresh_uuid,
                ODC.__table__.c.desc_cat == dc.id,
            )
            .limit(1),
        ).scalar_one_or_none()
        assert odc is not None, 'obj_desc_cat should have been auto-created'


# ---------------------------------------------------------------------------
# VAL-UPSERT-010: IDENTITY PKs excluded from get_or_create filters
# ---------------------------------------------------------------------------


class TestIdentityPKExcluded:
    """get_or_create does not include IDENTITY PK in filter."""

    def test_identity_pk_not_in_filter(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-010: find units row without knowing its integer PK.

        Call get_or_create with label='um' — the IDENTITY id column
        should NOT be part of the existence-check filter.
        """
        Units = reflected.Units
        nk = schema.tables['units'].natural_key

        # We intentionally include id=None to prove it's ignored
        inst, created = get_or_create(
            session,
            Units,
            nk,
            {'label': 'um'},
        )
        assert inst is not None
        assert inst.label == 'um'
        assert isinstance(inst.id, int)
        assert created is False


# ---------------------------------------------------------------------------
# VAL-UPSERT-011: NULL in unique constraint handled with IS NULL
# ---------------------------------------------------------------------------


class TestNullUniqueConstraint:
    """NULL columns in unique constraints use IS NULL semantics."""

    def test_null_in_unique_constraint_is_null(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-011: domain=None finds row with IS NULL, not = NULL.

        Two calls with domain=None should find the same row (not create
        duplicates).
        """
        DQ = reflected.DescriptorsQuant
        # Use composite unique constraint columns
        composite_nk = ['unit', 'aspect', 'domain', 'shape', 'aggregation_type']

        # Look up resolved integer IDs for 'count' descriptor
        unit_id = _lookup_id(session, reflected.Units, 'label', 'unitless')
        aspect_id = _lookup_id(session, reflected.Aspects, 'label', 'count')

        data = {
            'label': 'count',
            'unit': unit_id,
            'aspect': aspect_id,
            'domain': None,
            'shape': 'scalar',
            'aggregation_type': 'instance',
        }

        inst1, _ = get_or_create(session, DQ, composite_nk, data)
        inst2, _ = get_or_create(session, DQ, composite_nk, data)

        # Same row found both times (IS NULL semantics, not = NULL)
        assert inst1.id == inst2.id


# ---------------------------------------------------------------------------
# VAL-UPSERT-012: Server defaults not included in lookup filter
# ---------------------------------------------------------------------------


class TestServerDefaultsOmitted:
    """Server-default columns omitted from data skip filter."""

    def test_server_default_not_in_filter(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """VAL-UPSERT-012: omitting shape/aggregation_type from data.

        When the caller omits ``shape`` (server default 'scalar') from
        the data dict, get_or_create should not filter on ``shape``.
        """
        DQ = reflected.DescriptorsQuant
        # Use the composite unique constraint as natural key
        composite_nk = ['unit', 'aspect', 'domain', 'shape', 'aggregation_type']

        unit_id = _lookup_id(session, reflected.Units, 'label', 'unitless')
        aspect_id = _lookup_id(session, reflected.Aspects, 'label', 'count')

        # Data WITHOUT shape and aggregation_type (server defaults)
        data_partial = {
            'label': 'count',
            'unit': unit_id,
            'aspect': aspect_id,
            'domain': None,
        }

        # Should still find the existing 'count' row
        inst, created = get_or_create(session, DQ, composite_nk, data_partial)
        assert inst is not None
        assert inst.label == 'count'
        # Not created — found existing row even without shape in filter
        assert created is False
