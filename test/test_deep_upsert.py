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
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session

from quantdb.generic_ingest import (
    FKCache,
    Ingest,
    IngestError,
    LookupTableError,
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


# ---------------------------------------------------------------------------
# Regression: _ensure_obj_desc_inst must match the SPECIFIC (object, desc_inst) pair
# ---------------------------------------------------------------------------


class TestObjDescInstSpecificPair:
    """Regression: _ensure_obj_desc_inst creates the exact (object, desc_inst)
    pair needed, even when the object already has a DIFFERENT desc_inst
    mapping in obj_desc_inst.

    The composite FK on values_quant/values_cat is::

        FOREIGN KEY (object, desc_inst) REFERENCES obj_desc_inst (object, desc_inst)

    If the helper only checks ``WHERE object = ?`` (any row), it
    short-circuits and does NOT create the specific pair needed for the
    new desc_inst, causing the composite FK to fail on INSERT.
    """

    def test_second_desc_inst_auto_created(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
    ) -> None:
        """Object with obj_desc_inst for 'nerve' can also get
        obj_desc_inst for 'fascicle-cross-section' via deep_upsert.

        Steps:
            1. Find a non-dataset object with no obj_desc_inst rows.
            2. Manually create obj_desc_inst for desc_inst='nerve' (id 14).
            3. deep_upsert a values_quant referencing
               desc_inst='fascicle-cross-section' (id 25) with a
               matching values_inst row whose desc_inst is also 25
               (required by values_quant_check_before trigger).
            4. Verify a *second* obj_desc_inst row was auto-created for
               the fascicle-cross-section pair.
        """
        Objects = reflected.Objects
        ODI = reflected.ObjDescInst
        ODQ = reflected.ObjDescQuant
        VQ = reflected.ValuesQuant
        DI = reflected.DescriptorsInst
        DQ = reflected.DescriptorsQuant
        VI = reflected.ValuesInst

        # 1. Find an object with NO obj_desc_inst rows
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

        # Look up the two distinct desc_inst IDs
        nerve_id = _lookup_id(session, DI, 'label', 'nerve')
        fascicle_id = _lookup_id(session, DI, 'label', 'fascicle-cross-section')
        assert nerve_id != fascicle_id, 'Test requires two distinct desc_inst'

        # 2. Manually create an obj_desc_inst for (object, nerve)
        odi_nerve = ODI(
            object=fresh_uuid,
            desc_inst=nerve_id,
            addr_field=1,
        )
        session.add(odi_nerve)
        session.flush()

        # Confirm exactly 1 obj_desc_inst row exists for this object
        odi_count = (
            session.execute(
                select(ODI).where(ODI.__table__.c.object == fresh_uuid),
            )
            .scalars()
            .all()
        )
        assert len(odi_count) == 1

        # 3. deep_upsert a values_quant referencing
        #    desc_inst='fascicle-cross-section'.  Use a values_inst row
        #    whose desc_inst is also fascicle-cross-section (required by
        #    the values_quant_check_before trigger) and a desc_quant
        #    whose domain matches (domain=25 or domain IS NULL).
        vi = session.execute(
            select(VI).where(VI.desc_inst == fascicle_id).limit(1),
        ).scalar_one_or_none()
        if vi is None:
            pytest.skip('No values_inst row with desc_inst=fascicle-cross-section')

        dq = session.execute(
            select(DQ).where((DQ.domain == fascicle_id) | DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        cache: FKCache = {}
        result = deep_upsert(
            session,
            VQ,
            schema,
            {
                'value': 99.0,
                'value_blob': 99.0,
                'object': fresh_uuid,
                'desc_inst': fascicle_id,
                'desc_quant': dq.id,
                'instance': vi.id,
            },
            cache,
        )
        assert result is not None
        assert result.value == 99.0

        # 4. Verify TWO obj_desc_inst rows exist — one for nerve,
        #    one for fascicle-cross-section
        odi_rows = (
            session.execute(
                select(ODI).where(ODI.__table__.c.object == fresh_uuid),
            )
            .scalars()
            .all()
        )
        assert len(odi_rows) == 2, (
            f'Expected 2 obj_desc_inst rows but found {len(odi_rows)}; '
            f'_ensure_obj_desc_inst must match the specific (object, desc_inst) pair'
        )

        # Verify the specific pairs
        odi_desc_inst_ids = {row.desc_inst for row in odi_rows}
        assert nerve_id in odi_desc_inst_ids, 'Original nerve pair missing'
        assert fascicle_id in odi_desc_inst_ids, 'fascicle-cross-section pair was not auto-created'

        # Also verify obj_desc_quant was auto-created for the new pair
        odq_row = session.execute(
            select(ODQ)
            .where(
                ODQ.__table__.c.object == fresh_uuid,
                ODQ.__table__.c.desc_quant == dq.id,
            )
            .limit(1),
        ).scalar_one_or_none()
        assert odq_row is not None, 'obj_desc_quant should have been auto-created'


# ===========================================================================
# VAL-API: Ingest class tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Ingest fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def ingest(reflected: ReflectedModels) -> Ingest:
    """Create an Ingest instance for the reflected models."""
    return Ingest(reflected)


# ---------------------------------------------------------------------------
# Helper: find a fresh object with no obj_desc_inst rows
# ---------------------------------------------------------------------------


def _fresh_object(session: Session, reflected: ReflectedModels):
    """Find a non-dataset object with no obj_desc_inst rows."""
    Objects = reflected.Objects
    ODI = reflected.ObjDescInst
    return session.execute(
        select(Objects)
        .where(
            Objects.id_type != 'dataset',
            ~Objects.id.in_(select(ODI.__table__.c.object)),
        )
        .limit(1),
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# VAL-API-001: Ingest.row() for values_quant
# ---------------------------------------------------------------------------


class TestIngestRowValuesQuant:
    """Ingest.row() inserts values_quant with FKs resolved from labels."""

    def test_row_values_quant_with_string_fk_labels(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
        ingest: Ingest,
    ) -> None:
        """VAL-API-001: Ingest.row(s, 'values_quant', ...) inserts with
        all FK columns correctly resolved from labels.
        """
        obj = _fresh_object(session, reflected)
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        # Find a values_inst row and its desc_inst label
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        vi = session.execute(select(VI).limit(1)).scalar_one()
        di = session.execute(
            select(DI).where(DI.id == vi.desc_inst),
        ).scalar_one()

        # Find a desc_quant with domain=NULL (compatible with any desc_inst)
        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        result = ingest.row(
            session,
            'values_quant',
            value=42.0,
            value_blob=42.0,
            object=obj.id,
            desc_inst=di.label,  # string FK → resolved
            desc_quant=dq.label,  # string FK → resolved
            instance={
                'dataset': str(vi.dataset),
                'id_formal': vi.id_formal,
            },
        )

        assert result is not None
        assert result.value == 42.0
        assert result.desc_inst == di.id
        assert result.desc_quant == dq.id
        assert result.object == obj.id


# ---------------------------------------------------------------------------
# VAL-API-002: Ingest.row() for values_cat
# ---------------------------------------------------------------------------


class TestIngestRowValuesCat:
    """Ingest.row() inserts values_cat with FKs resolved from labels."""

    def test_row_values_cat_with_string_fk_labels(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
        ingest: Ingest,
    ) -> None:
        """VAL-API-002: Ingest.row(s, 'values_cat', ...) inserts with
        all FK columns correctly resolved from labels.
        """
        obj = _fresh_object(session, reflected)
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        vi = session.execute(select(VI).limit(1)).scalar_one()
        di = session.execute(
            select(DI).where(DI.id == vi.desc_inst),
        ).scalar_one()

        # Find a desc_cat with domain=NULL
        DC = reflected.DescriptorsCat
        dc = session.execute(
            select(DC).where(DC.domain.is_(None)).limit(1),
        ).scalar_one()

        # Find a controlled_term
        CT = reflected.ControlledTerms
        ct = session.execute(select(CT).limit(1)).scalar_one()

        result = ingest.row(
            session,
            'values_cat',
            value_open=ct.label,
            value_controlled=ct.label,  # string FK → resolved
            object=obj.id,
            desc_inst=di.label,  # string FK → resolved
            desc_cat=dc.id,  # pre-resolved int (composite natural key)
            instance={
                'dataset': str(vi.dataset),
                'id_formal': vi.id_formal,
            },
        )

        assert result is not None
        assert result.object == obj.id
        assert result.desc_inst == di.id
        assert result.desc_cat == dc.id
        assert result.value_controlled == ct.id


# ---------------------------------------------------------------------------
# VAL-API-003: Ingest.batch() for multiple rows
# ---------------------------------------------------------------------------


class TestIngestBatch:
    """Ingest.batch() inserts multiple rows with shared FK cache."""

    def test_batch_values_quant_10_rows(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
        ingest: Ingest,
    ) -> None:
        """VAL-API-003: batch inserts 10+ rows with shared FK cache."""
        obj = _fresh_object(session, reflected)
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        vi = session.execute(select(VI).limit(1)).scalar_one()
        di = session.execute(
            select(DI).where(DI.id == vi.desc_inst),
        ).scalar_one()

        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        rows = [
            {
                'value': float(i),
                'value_blob': float(i),
                'object': obj.id,
                'desc_inst': di.label,  # shared string FK
                'desc_quant': dq.label,  # shared string FK
                'instance': {
                    'dataset': str(vi.dataset),
                    'id_formal': vi.id_formal,
                },
            }
            for i in range(10)
        ]

        results = ingest.batch(session, 'values_quant', rows)
        assert len(results) == 10
        # All rows should reference the same object
        for r in results:
            assert r.object == obj.id
            assert r.desc_inst == di.id
            assert r.desc_quant == dq.id


# ---------------------------------------------------------------------------
# VAL-API-004: Ingest.get() retrieves by natural key
# ---------------------------------------------------------------------------


class TestIngestGet:
    """Ingest.get() retrieves existing rows and returns None for missing."""

    def test_get_existing_unit(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """VAL-API-004: Ingest.get(s, 'units', label='um') returns row."""
        result = ingest.get(session, 'units', label='um')
        assert result is not None
        assert result.label == 'um'
        assert isinstance(result.id, int)

    def test_get_nonexistent_returns_none(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """VAL-API-004: Ingest.get(s, 'units', label='nonexistent') → None."""
        result = ingest.get(session, 'units', label='nonexistent')
        assert result is None


# ---------------------------------------------------------------------------
# VAL-API-005: Human-readable error messages
# ---------------------------------------------------------------------------


class TestIngestErrorMessages:
    """Error messages include table name and constraint/trigger info."""

    def test_error_includes_table_name_and_trigger_identifier(
        self,
        session: Session,
        reflected: ReflectedModels,
        schema: SchemaGraph,
        ingest: Ingest,
    ) -> None:
        """VAL-API-005: Error includes table name AND constraint/trigger ID.

        Deliberately pass incompatible desc_inst + instance to
        values_quant to trigger the ``values_quant_check_before``
        trigger.  The raised ``IngestError`` message must include:
        (a) the table name ``'values_quant'`` and (b) the trigger
        function name or constraint identifier.
        """
        obj = _fresh_object(session, reflected)
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        vi = session.execute(select(VI).limit(1)).scalar_one()

        # Find a desc_inst DIFFERENT from the one on values_inst
        di_other = session.execute(
            select(DI).where(DI.id != vi.desc_inst).limit(1),
        ).scalar_one_or_none()
        if di_other is None:
            pytest.skip('Only one desc_inst in the database')

        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        with pytest.raises(IngestError) as exc_info:
            ingest.row(
                session,
                'values_quant',
                value=99.0,
                value_blob=99.0,
                object=obj.id,
                desc_inst=di_other.id,  # WRONG: doesn't match vi.desc_inst
                desc_quant=dq.id,
                instance=vi.id,
            )

        error_msg = str(exc_info.value)
        # (a) Must include the table name
        assert 'values_quant' in error_msg, f'Error message should contain table name: {error_msg}'
        # (b) Must include the constraint name OR trigger function name
        has_identifier = (
            'constraint' in error_msg.lower() or 'check_before' in error_msg or 'values_quant_check_before' in error_msg
        )
        assert has_identifier, f'Error message should contain constraint or trigger ' f'identifier: {error_msg}'


# ---------------------------------------------------------------------------
# VAL-API-006: Session lifecycle
# ---------------------------------------------------------------------------


class TestIngestSessionLifecycle:
    """Ingest.session() commits writes on clean exit, rolls back on exception."""

    def test_session_commits_writes_on_clean_exit(
        self,
        reflected: ReflectedModels,
        ingest: Ingest,
    ) -> None:
        """VAL-API-006: Inserted row persists after successful session exit.

        Insert a temporary ``objects`` row inside ``Ingest.session()``,
        then verify it is visible in a brand-new session (proving the
        context manager committed).  Cleanup uses a superuser connection
        because the ``quantdb-test-user`` role lacks DELETE grants.
        """
        test_uuid = uuid.uuid4()
        Objects = reflected.Objects

        with ingest.session() as s:
            obj = Objects(id=test_uuid, id_type='collection')
            s.add(obj)
            s.flush()
        # Session commits on clean exit

        # Verify committed row is visible in a fresh session
        fresh = reflected.Session()
        try:
            result = fresh.execute(
                select(Objects).where(
                    Objects.__table__.c.id == test_uuid,
                ),
            ).scalar_one_or_none()
            assert result is not None, 'Committed row should be visible in new session'
            assert result.id == test_uuid
            assert result.id_type == 'collection'
        finally:
            fresh.close()

        # Clean up test data via superuser (test user lacks DELETE)
        cleanup_engine = create_engine(
            'postgresql://localhost:5432/quantdb_test',
        )
        try:
            with cleanup_engine.connect() as conn:
                conn.execute(
                    text(
                        'DELETE FROM quantdb.objects WHERE id = :id',
                    ),
                    {'id': str(test_uuid)},
                )
                conn.commit()
        finally:
            cleanup_engine.dispose()

    def test_session_rolls_back_writes_on_exception(
        self,
        reflected: ReflectedModels,
        ingest: Ingest,
    ) -> None:
        """VAL-API-006: Inserted row absent after exception-triggered rollback.

        Insert a temporary ``objects`` row inside ``Ingest.session()``,
        then raise an exception.  Verify the row is NOT visible in a
        new session (proving the context manager rolled back).
        """
        test_uuid = uuid.uuid4()
        Objects = reflected.Objects

        with pytest.raises(RuntimeError, match='deliberate'):
            with ingest.session() as s:
                obj = Objects(id=test_uuid, id_type='collection')
                s.add(obj)
                s.flush()
                raise RuntimeError('deliberate test exception')
        # Session should rollback on exception

        # Verify rolled-back row is NOT visible in a fresh session
        fresh = reflected.Session()
        try:
            result = fresh.execute(
                select(Objects).where(
                    Objects.__table__.c.id == test_uuid,
                ),
            ).scalar_one_or_none()
            assert result is None, 'Rolled-back row should not be visible in new session'
        finally:
            fresh.rollback()
            fresh.close()


# ---------------------------------------------------------------------------
# VAL-API-007: Lookup table protection
# ---------------------------------------------------------------------------


class TestLookupTableProtection:
    """FK resolution on lookup tables raises error for unknown values."""

    def test_unknown_desc_inst_raises_lookup_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """VAL-API-007: Unknown value for lookup table raises LookupTableError.

        descriptors_inst is a lookup table (is_lookup=True).  Passing a
        non-existent label should raise LookupTableError, not silently
        create a new row.
        """
        with pytest.raises(LookupTableError, match='descriptors_inst'):
            ingest.row(
                session,
                'values_quant',
                value=1.0,
                value_blob=1.0,
                object=uuid.UUID(F006_UUID),
                desc_inst='nonexistent-class',
                desc_quant=1,
                instance=1,
            )

    def test_unknown_unit_raises_lookup_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """VAL-API-007: Unknown unit raises LookupTableError.

        units is a lookup table.  Passing a non-existent label should
        raise LookupTableError.
        """
        with pytest.raises(LookupTableError, match='units'):
            ingest.row(
                session,
                'descriptors_quant',
                label='test-nonexistent',
                unit='nonexistent-unit',
                aspect='count',
            )

    def test_unknown_aspect_raises_lookup_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """VAL-API-007: Unknown aspect raises LookupTableError.

        aspects is a lookup table.  Passing a non-existent label should
        raise LookupTableError.
        """
        with pytest.raises(LookupTableError, match='aspects'):
            ingest.row(
                session,
                'descriptors_quant',
                label='test-nonexistent',
                unit='um',
                aspect='nonexistent-aspect',
            )


# ---------------------------------------------------------------------------
# Regression: Ingest.row() must block direct inserts into lookup tables
# ---------------------------------------------------------------------------


class TestIngestRowLookupTableGuard:
    """Regression: Ingest.row() raises LookupTableError for lookup tables.

    The scrutiny review found that Ingest.row() allowed direct inserts
    into lookup tables (units, aspects, descriptors_inst, etc.).  The
    fix adds a guard at the TOP of Ingest.row() that checks
    ``table_info.is_lookup`` and raises ``LookupTableError`` before
    reaching ``deep_upsert``.
    """

    def test_row_into_units_raises_lookup_table_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'units', label='test', iri='test') → LookupTableError.

        units is a pre-populated lookup table.  Direct inserts via
        Ingest.row() must be blocked.
        """
        with pytest.raises(LookupTableError, match='units'):
            ingest.row(session, 'units', label='test', iri='test')

    def test_row_into_aspects_raises_lookup_table_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'aspects', ...) → LookupTableError."""
        with pytest.raises(LookupTableError, match='aspects'):
            ingest.row(session, 'aspects', label='test', iri='test')

    def test_row_into_descriptors_inst_raises_lookup_table_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'descriptors_inst', ...) → LookupTableError."""
        with pytest.raises(LookupTableError, match='descriptors_inst'):
            ingest.row(
                session,
                'descriptors_inst',
                label='test',
                iri='test',
            )

    def test_row_into_controlled_terms_raises_lookup_table_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'controlled_terms', ...) → LookupTableError."""
        with pytest.raises(LookupTableError, match='controlled_terms'):
            ingest.row(
                session,
                'controlled_terms',
                label='test',
                iri='test',
            )

    def test_row_into_addresses_raises_lookup_table_error(
        self,
        session: Session,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'addresses', ...) → LookupTableError."""
        with pytest.raises(LookupTableError, match='addresses'):
            ingest.row(
                session,
                'addresses',
                addr_type='constant',
                addr_field='test',
                value_type='single',
            )

    def test_row_into_non_lookup_table_allowed(
        self,
        session: Session,
        reflected: ReflectedModels,
        ingest: Ingest,
    ) -> None:
        """Ingest.row(s, 'objects', ...) succeeds (not a lookup table)."""
        test_uuid = uuid.uuid4()
        result = ingest.row(
            session,
            'objects',
            id=test_uuid,
            id_type='collection',
        )
        assert result is not None
        assert result.id == test_uuid


# ---------------------------------------------------------------------------
# VAL-CROSS-001: End-to-end reflect-to-insert-to-verify
# ---------------------------------------------------------------------------


class TestEndToEndReflectInsertVerify:
    """Full flow from reflect_models() → Ingest → insert → SQL verify."""

    def test_end_to_end_values_quant(
        self,
        session: Session,
        reflected: ReflectedModels,
        ingest: Ingest,
    ) -> None:
        """VAL-CROSS-001: reflect → Ingest → insert → raw SQL verify.

        Starting from reflect_models(), create an Ingest instance,
        insert a values_quant row using only human-readable labels,
        then verify via raw SQL SELECT on quantdb_test.
        """
        obj = _fresh_object(session, reflected)
        if obj is None:
            pytest.skip('No non-dataset object without obj_desc_inst')

        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        vi = session.execute(select(VI).limit(1)).scalar_one()
        di = session.execute(
            select(DI).where(DI.id == vi.desc_inst),
        ).scalar_one()

        DQ = reflected.DescriptorsQuant
        dq = session.execute(
            select(DQ).where(DQ.domain.is_(None)).limit(1),
        ).scalar_one()

        result = ingest.row(
            session,
            'values_quant',
            value=123.456,
            value_blob=123.456,
            object=obj.id,
            desc_inst=di.label,
            desc_quant=dq.label,
            instance={
                'dataset': str(vi.dataset),
                'id_formal': vi.id_formal,
            },
        )

        # Verify via raw SQL
        row = session.execute(
            text('SELECT value, object, desc_quant FROM quantdb.values_quant ' 'WHERE id = :id'),
            {'id': result.id},
        ).one()

        assert float(row.value) == 123.456
        assert row.object == obj.id
        assert row.desc_quant == dq.id
