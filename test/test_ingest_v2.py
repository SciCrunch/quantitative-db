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
