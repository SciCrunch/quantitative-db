"""Tests for the v2 ingest pipeline (dump-based extract, delete, re-insert).

Verifies:
  (a) extract_f006_from_db produces dicts with correct counts
  (b) delete_f006_data zeros all counts
  (c) ingest_f006_v2 inserts data successfully

Requires:
    - PostgreSQL running on localhost:5432 (trust auth)
    - quantdb_test database restored from production dump
"""
from __future__ import annotations

from decimal import Decimal
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import text as sql_text

from quantdb.ingest_v2 import (
    F006_UUID,
    delete_f006_data,
    extract_f006_from_db,
    ingest_f006_v2,
)
from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def reflected(rebuild_database) -> Generator[ReflectedModels, None, None]:
    """Reflect quantdb_test schema once per module.

    Uses ``postgres`` user since delete/ingest tests need DELETE
    permission (``quantdb-test-user`` only has SELECT/INSERT).

    Depends on ``rebuild_database`` (session-scoped) to ensure the
    production dump has been restored before any test runs.
    """
    try:
        engine = create_engine(
            dbUri(
                dbuser='postgres',
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


@pytest.fixture
def session(reflected: ReflectedModels) -> Generator[Session, None, None]:
    """Provide a fresh session per test, rolled back after each test."""
    sess = reflected.Session()
    yield sess
    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# Helper: count f006 data across all tables
# ---------------------------------------------------------------------------


def _count_f006(session, models):
    """Return a dict of f006 row counts for all data tables."""
    counts = {}

    # values_inst
    VI = models.ValuesInst
    counts['values_inst'] = session.execute(
        select(func.count()).select_from(VI).where(VI.dataset == F006_UUID)
    ).scalar_one()

    # dataset_object
    DO = models.DatasetObject
    counts['dataset_object'] = session.execute(
        select(func.count()).select_from(DO).where(DO.dataset == F006_UUID)
    ).scalar_one()

    # instance_parent (join to values_inst for f006 filter)
    IP = models.InstanceParent
    counts['instance_parent'] = session.execute(
        select(func.count()).select_from(IP).join(VI, IP.id == VI.id).where(VI.dataset == F006_UUID)
    ).scalar_one()

    # equiv_inst
    EI = models.EquivInst
    counts['equiv_inst'] = session.execute(
        select(func.count()).select_from(EI).join(VI, EI.left_thing == VI.id).where(VI.dataset == F006_UUID)
    ).scalar_one()

    # objects_internal
    OI = models.ObjectsInternal
    counts['objects_internal'] = session.execute(
        select(func.count()).select_from(OI).where(OI.dataset == F006_UUID)
    ).scalar_one()

    # values_quant (join through dataset_object)
    VQ = models.ValuesQuant
    counts['values_quant'] = session.execute(
        select(func.count()).select_from(VQ).join(DO, VQ.object == DO.object).where(DO.dataset == F006_UUID)
    ).scalar_one()

    # values_cat (join through dataset_object)
    VC = models.ValuesCat
    counts['values_cat'] = session.execute(
        select(func.count()).select_from(VC).join(DO, VC.object == DO.object).where(DO.dataset == F006_UUID)
    ).scalar_one()

    # obj_desc_inst
    ODI = models.ObjDescInst
    obj_sub = select(DO.object).where(DO.dataset == F006_UUID)
    counts['obj_desc_inst'] = session.execute(
        select(func.count()).select_from(ODI).where(ODI.object.in_(obj_sub))
    ).scalar_one()

    # obj_desc_quant
    ODQ = models.ObjDescQuant
    counts['obj_desc_quant'] = session.execute(
        select(func.count()).select_from(ODQ).where(ODQ.object.in_(obj_sub))
    ).scalar_one()

    # obj_desc_cat
    ODC = models.ObjDescCat
    counts['obj_desc_cat'] = session.execute(
        select(func.count()).select_from(ODC).where(ODC.object.in_(obj_sub))
    ).scalar_one()

    return counts


# ---------------------------------------------------------------------------
# Tests: Extraction
# ---------------------------------------------------------------------------


class TestExtractF006:
    """Verify extract_f006_from_db produces dicts with correct counts."""

    def test_extract_returns_all_keys(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        expected_keys = {
            'objects',
            'objects_internal',
            'dataset_object',
            'values_inst',
            'instance_parent',
            'equiv_inst',
            'values_quant',
            'values_cat',
        }
        assert set(data.keys()) == expected_keys

    def test_extract_objects_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        # 121 package objects + 1 dataset + 1 internal = 123
        assert len(data['objects']) >= 122

    def test_extract_objects_have_string_ids(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        for obj in data['objects']:
            assert isinstance(obj['id'], str)
            assert isinstance(obj['id_type'], str)

    def test_extract_dataset_object_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        assert len(data['dataset_object']) == 121

    def test_extract_objects_internal_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        assert len(data['objects_internal']) == 1

    def test_extract_values_inst_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        assert len(data['values_inst']) == 609_390

    def test_extract_values_inst_have_string_desc_inst(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        # Check first few entries have string desc_inst labels
        for vi in data['values_inst'][:10]:
            assert isinstance(vi['desc_inst'], str)
            assert vi['desc_inst'] in (
                'human',
                'nerve',
                'nerve-volume',
                'nerve-cross-section',
                'fascicle-cross-section',
                'fiber-cross-section',
                'extruded-plane',
            )

    def test_extract_instance_parent_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        assert len(data['instance_parent']) == 609_389

    def test_extract_instance_parent_uses_dict_refs(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        ip = data['instance_parent'][0]
        assert isinstance(ip['id'], dict)
        assert 'dataset' in ip['id']
        assert 'id_formal' in ip['id']
        assert isinstance(ip['parent'], dict)
        assert 'dataset' in ip['parent']
        assert 'id_formal' in ip['parent']

    def test_extract_equiv_inst_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        assert len(data['equiv_inst']) == 37

    def test_extract_values_quant_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        # Gold-standard counts 2,445,944 via dataset_object only;
        # extraction also includes values for the internal object
        assert len(data['values_quant']) >= 2_445_944

    def test_extract_values_quant_have_string_labels(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        vq = data['values_quant'][0]
        assert isinstance(vq['desc_inst'], str)
        assert isinstance(vq['desc_quant'], str)
        assert isinstance(vq['object'], str)
        assert isinstance(vq['instance'], dict)
        assert 'dataset' in vq['instance']
        assert 'id_formal' in vq['instance']

    def test_extract_values_cat_count(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        # Gold-standard counts 608,859 via dataset_object only;
        # extraction also includes values for the internal object
        assert len(data['values_cat']) >= 608_859

    def test_extract_values_cat_have_string_labels(self, session, reflected):
        data = extract_f006_from_db(session, reflected)
        vc = data['values_cat'][0]
        assert isinstance(vc['desc_inst'], str)
        assert isinstance(vc['desc_cat'], str)
        assert isinstance(vc['object'], str)
        assert isinstance(vc['instance'], dict)


# ---------------------------------------------------------------------------
# Tests: Deletion
# ---------------------------------------------------------------------------


class TestDeleteF006:
    """Verify delete_f006_data zeros all f006 counts."""

    def test_delete_zeros_all_counts(self, session, reflected):
        # Verify data exists before deletion
        pre_counts = _count_f006(session, reflected)
        assert pre_counts['values_inst'] == 609_390
        assert pre_counts['dataset_object'] == 121

        # Delete all f006 data
        delete_f006_data(session, reflected)

        # Verify all counts are zero
        post_counts = _count_f006(session, reflected)
        for table_name, count in post_counts.items():
            assert count == 0, f'{table_name}: expected 0 after deletion, got {count}'

    def test_delete_no_integrity_error(self, session, reflected):
        """Deletion should complete without IntegrityError."""
        # This test proves FK-safe ordering by simply succeeding
        delete_f006_data(session, reflected)

    def test_delete_removes_objects(self, session, reflected):
        """Dataset object and package objects should be removed."""
        Obj = reflected.Objects
        pre_count = session.execute(select(func.count()).select_from(Obj).where(Obj.id == F006_UUID)).scalar_one()
        assert pre_count == 1

        delete_f006_data(session, reflected)

        post_count = session.execute(select(func.count()).select_from(Obj).where(Obj.id == F006_UUID)).scalar_one()
        assert post_count == 0


# ---------------------------------------------------------------------------
# Tests: Ingestion
# ---------------------------------------------------------------------------


class TestIngestF006:
    """Verify ingest_f006_v2 inserts data successfully."""

    def test_ingest_creates_nonzero_counts(self, session, reflected):
        """Extract -> Delete -> Ingest produces non-zero counts."""
        # Step 1: Extract data while it still exists
        data_dicts = extract_f006_from_db(session, reflected)

        # Step 2: Delete all f006 data
        delete_f006_data(session, reflected)

        # Verify zero counts
        zero_counts = _count_f006(session, reflected)
        assert zero_counts['values_inst'] == 0

        # Step 3: Ingest via Ingest.batch()
        ingest_f006_v2(session, reflected, data_dicts)

        # Step 4: Verify non-zero counts
        post_counts = _count_f006(session, reflected)
        assert post_counts['values_inst'] > 0, 'values_inst should have rows after ingest'
        assert post_counts['dataset_object'] > 0, 'dataset_object should have rows after ingest'
        assert post_counts['instance_parent'] > 0, 'instance_parent should have rows after ingest'
        assert post_counts['values_quant'] > 0, 'values_quant should have rows after ingest'
        assert post_counts['values_cat'] > 0, 'values_cat should have rows after ingest'
        assert post_counts['equiv_inst'] > 0, 'equiv_inst should have rows after ingest'
        assert post_counts['objects_internal'] > 0, 'objects_internal should have rows after ingest'

    def test_ingest_trigger_prerequisites_created(self, session, reflected):
        """Deep upsert auto-creates obj_desc_* prerequisites."""
        data_dicts = extract_f006_from_db(session, reflected)
        delete_f006_data(session, reflected)
        ingest_f006_v2(session, reflected, data_dicts)

        post_counts = _count_f006(session, reflected)
        assert post_counts['obj_desc_inst'] > 0, 'obj_desc_inst should have rows after ingest'
        assert post_counts['obj_desc_quant'] > 0, 'obj_desc_quant should have rows after ingest'
        assert post_counts['obj_desc_cat'] > 0, 'obj_desc_cat should have rows after ingest'


# ---------------------------------------------------------------------------
# Module-scoped fixture: extract -> delete -> ingest ONCE
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def f006_ingested_session(
    reflected: ReflectedModels,
) -> Generator[Session, None, None]:
    """Run the full extract->delete->ingest cycle once at module scope.

    Shares the resulting session across all ``TestComparisonProof``
    tests so the ~8-minute pipeline is not repeated per assertion.
    """
    sess = reflected.Session()

    # Extract f006 data while production dump is present
    data_dicts = extract_f006_from_db(sess, reflected)

    # Delete all f006 data (FK-safe child-first)
    delete_f006_data(sess, reflected)

    # Verify zeros after deletion
    zero_counts = _count_f006(sess, reflected)
    for table_name, count in zero_counts.items():
        assert count == 0, f'{table_name}: expected 0 after deletion, got {count}'

    # Re-ingest via v2 pipeline
    ingest_f006_v2(sess, reflected, data_dicts)

    yield sess

    sess.rollback()
    sess.close()


# ---------------------------------------------------------------------------
# Tests: Comparison proof (post-ingest assertions)
# ---------------------------------------------------------------------------


class TestComparisonProof:
    """Post-ingest proof: exact counts, breakdowns, and spot-checks.

    All tests share a single module-scoped session that ran
    extract -> delete -> ingest once.  This avoids running the
    ~8-minute pipeline for each individual assertion.
    """

    # ---- Exact count assertions (VAL-ING-001 through VAL-ING-008) ----

    def test_values_inst_total(self, f006_ingested_session, reflected):
        """VAL-ING-001: values_inst count matches 609,390."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['values_inst'] == 609_390

    def test_instance_parent_count(self, f006_ingested_session, reflected):
        """VAL-ING-003: instance_parent count matches 609,389."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['instance_parent'] == 609_389

    def test_dataset_object_count(self, f006_ingested_session, reflected):
        """VAL-ING-004: dataset_object count matches 121."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['dataset_object'] == 121

    def test_values_quant_total(self, f006_ingested_session, reflected):
        """VAL-ING-005: values_quant count matches 2,445,944."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['values_quant'] == 2_445_944

    def test_values_cat_total(self, f006_ingested_session, reflected):
        """VAL-ING-006: values_cat count matches 608,859."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['values_cat'] == 608_859

    def test_equiv_inst_count(self, f006_ingested_session, reflected):
        """VAL-ING-007: equiv_inst count matches 37."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['equiv_inst'] == 37

    def test_objects_internal_count(self, f006_ingested_session, reflected):
        """VAL-ING-008: objects_internal count matches 1."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['objects_internal'] == 1

    # ---- Values_inst breakdown (VAL-ING-002) ----

    def test_values_inst_breakdown(self, f006_ingested_session, reflected):
        """VAL-ING-002: (type, desc_inst_label) breakdown matches all 7 groups."""
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(VI.type, DI.label, func.count())
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == F006_UUID)
            .group_by(VI.type, DI.label)
            .order_by(VI.type, DI.label)
        )
        rows = f006_ingested_session.execute(stmt).all()
        breakdown = {(row[0], row[1]): row[2] for row in rows}

        expected = {
            ('subject', 'human'): 1,
            ('sample', 'nerve-volume'): 61,
            ('sample', 'nerve-cross-section'): 27,
            ('sample', 'nerve'): 2,
            ('site', 'extruded-plane'): 60,
            ('below', 'fiber-cross-section'): 608_811,
            ('below', 'fascicle-cross-section'): 428,
        }
        assert breakdown == expected

    # ---- Fiber descriptor breakdown (VAL-ING-009) ----

    def test_fiber_quant_descriptors(self, f006_ingested_session, reflected):
        """VAL-ING-009: 4 fiber descriptors at 608,811 each."""
        VQ = reflected.ValuesQuant
        DQ = reflected.DescriptorsQuant
        DO = reflected.DatasetObject

        f006_objects = select(DO.object).where(DO.dataset == F006_UUID)

        stmt = (
            select(DQ.label, func.count())
            .select_from(VQ)
            .join(DQ, VQ.desc_quant == DQ.id)
            .where(VQ.object.in_(f006_objects))
            .group_by(DQ.label)
            .order_by(DQ.label)
        )
        rows = f006_ingested_session.execute(stmt).all()
        breakdown = {row[0]: row[1] for row in rows}

        fiber_descriptors = [
            'fiber cross section area um2',
            'fiber cross section diameter um',
            'fiber cross section diameter um max',
            'fiber cross section diameter um min',
        ]
        for desc in fiber_descriptors:
            assert desc in breakdown, f'Missing descriptor: {desc}'
            assert breakdown[desc] == 608_811, f'{desc}: expected 608811, got {breakdown[desc]}'

    # ---- hasAxonFiberType (VAL-ING-010) ----

    def test_has_axon_fiber_type(self, f006_ingested_session, reflected):
        """VAL-ING-010: hasAxonFiberType = 608,811."""
        VC = reflected.ValuesCat
        DC = reflected.DescriptorsCat
        DO = reflected.DatasetObject

        f006_objects = select(DO.object).where(DO.dataset == F006_UUID)

        stmt = (
            select(func.count())
            .select_from(VC)
            .join(DC, VC.desc_cat == DC.id)
            .where(VC.object.in_(f006_objects))
            .where(DC.label == 'hasAxonFiberType')
        )
        count = f006_ingested_session.execute(stmt).scalar_one()
        assert count == 608_811

    # ---- obj_desc_* existence (VAL-ING-011) ----

    def test_obj_desc_inst_exists(self, f006_ingested_session, reflected):
        """VAL-ING-011: obj_desc_inst rows exist after ingest."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['obj_desc_inst'] > 0, 'obj_desc_inst should have rows (trigger prereqs)'

    def test_obj_desc_quant_exists(self, f006_ingested_session, reflected):
        """VAL-ING-011: obj_desc_quant rows exist after ingest."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['obj_desc_quant'] > 0, 'obj_desc_quant should have rows (trigger prereqs)'

    def test_obj_desc_cat_exists(self, f006_ingested_session, reflected):
        """VAL-ING-011: obj_desc_cat rows exist after ingest."""
        counts = _count_f006(f006_ingested_session, reflected)
        assert counts['obj_desc_cat'] > 0, 'obj_desc_cat should have rows (trigger prereqs)'

    # ---- Spot-check values (VAL-ING-013) ----

    def test_spot_check_values_quant(self, f006_ingested_session, reflected):
        """VAL-ING-013: fiber values_quant have valid numeric values."""
        VQ = reflected.ValuesQuant
        DQ = reflected.DescriptorsQuant
        DI = reflected.DescriptorsInst
        VI = reflected.ValuesInst
        DO = reflected.DatasetObject

        f006_objects = select(DO.object).where(DO.dataset == F006_UUID)

        # Pick a small sample of fiber quant values and verify numerics
        stmt = (
            select(VQ.value, DQ.label, VI.id_formal)
            .join(DQ, VQ.desc_quant == DQ.id)
            .join(VI, VQ.instance == VI.id)
            .join(DI, VI.desc_inst == DI.id)
            .where(VQ.object.in_(f006_objects))
            .where(DI.label == 'fiber-cross-section')
            .where(
                DQ.label.in_(
                    [
                        'fiber cross section area um2',
                        'fiber cross section diameter um',
                        'fiber cross section diameter um max',
                        'fiber cross section diameter um min',
                    ]
                )
            )
            .order_by(VI.id_formal, DQ.label)
            .limit(20)
        )
        rows = f006_ingested_session.execute(stmt).all()
        assert len(rows) == 20, f'Expected 20 spot-check rows, got {len(rows)}'
        for value, desc_label, id_formal in rows:
            assert value is not None, f'{id_formal}/{desc_label}: value should not be None'
            assert isinstance(value, (int, float, Decimal)), (
                f'{id_formal}/{desc_label}: value should be numeric, ' f'got {type(value)}'
            )
            assert value >= 0, f'{id_formal}/{desc_label}: value should be >= 0, ' f'got {value}'

    def test_spot_check_values_cat(self, f006_ingested_session, reflected):
        """VAL-ING-013: fiber values_cat have valid categorical values."""
        VC = reflected.ValuesCat
        DC = reflected.DescriptorsCat
        CT = reflected.ControlledTerms
        VI = reflected.ValuesInst
        DO = reflected.DatasetObject

        f006_objects = select(DO.object).where(DO.dataset == F006_UUID)

        # Verify hasAxonFiberType values are myelinated or unmyelinated
        stmt = (
            select(VC.value_open, CT.label, VI.id_formal)
            .select_from(VC)
            .join(DC, VC.desc_cat == DC.id)
            .join(CT, VC.value_controlled == CT.id)
            .join(VI, VC.instance == VI.id)
            .where(VC.object.in_(f006_objects))
            .where(DC.label == 'hasAxonFiberType')
            .order_by(VI.id_formal)
            .limit(10)
        )
        rows = f006_ingested_session.execute(stmt).all()
        assert len(rows) == 10, f'Expected 10 spot-check rows, got {len(rows)}'
        for value_open, ct_label, id_formal in rows:
            assert ct_label in ('myelinated', 'unmyelinated'), f'{id_formal}: unexpected axon fiber type {ct_label!r}'

    # ---- Fascicle / fiber count validation (VAL-EXT-003/004) ----

    def test_fascicle_count(self, f006_ingested_session, reflected):
        """VAL-EXT-003: 428 fascicle-cross-section instances."""
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(func.count())
            .select_from(VI)
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == F006_UUID)
            .where(DI.label == 'fascicle-cross-section')
        )
        count = f006_ingested_session.execute(stmt).scalar_one()
        assert count == 428

    def test_fiber_count(self, f006_ingested_session, reflected):
        """VAL-EXT-004: 608,811 fiber-cross-section instances."""
        VI = reflected.ValuesInst
        DI = reflected.DescriptorsInst
        stmt = (
            select(func.count())
            .select_from(VI)
            .join(DI, VI.desc_inst == DI.id)
            .where(VI.dataset == F006_UUID)
            .where(DI.label == 'fiber-cross-section')
        )
        count = f006_ingested_session.execute(stmt).scalar_one()
        assert count == 608_811

    # ---- Idempotency (VAL-CROSS-003) ----

    @pytest.mark.slow
    def test_idempotency(self, f006_ingested_session, reflected):
        """VAL-CROSS-003: second ingest produces same counts.

        Extracts the current (re-ingested) data, deletes, re-ingests
        a second time, and asserts all counts are unchanged.  Marked
        ``@pytest.mark.slow`` because it runs the full ~8-min cycle
        again.
        """
        # Record counts from first ingest
        first_counts = _count_f006(f006_ingested_session, reflected)

        # Extract current state -> delete -> re-ingest
        data_dicts = extract_f006_from_db(f006_ingested_session, reflected)
        delete_f006_data(f006_ingested_session, reflected)
        ingest_f006_v2(f006_ingested_session, reflected, data_dicts)

        # Verify counts match
        second_counts = _count_f006(f006_ingested_session, reflected)
        for table_name in first_counts:
            assert first_counts[table_name] == second_counts[table_name], (
                f'{table_name}: first={first_counts[table_name]}, ' f'second={second_counts[table_name]}'
            )
