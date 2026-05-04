"""Tests for MicroCT schema lookup data (sql/inserts_microct.sql).

Verifies:
  - New units (mm, mm2) exist
  - quant_agg_type enum includes 'sd'
  - NerveMorphology descriptors_quant exist with correct FKs
  - GraphML fascicle descriptors_quant exist with correct FKs
  - SummaryMorphology descriptors_quant exist with mm/mm2 units
  - GraphML edge descriptors_cat exist
  - Boolean controlled_terms exist
  - All FK references are valid (no orphans)
  - SQL is idempotent (run twice without error)

Requires:
    - PostgreSQL running on localhost:5432 (trust auth)
    - quantdb_test database restored from production dump
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import text as sql_text

from quantdb.models import ReflectedModels, reflect_models
from quantdb.utils import dbUri

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SQL_DIR = Path(__file__).resolve().parent.parent / 'sql'
_INSERTS_MICROCT = _SQL_DIR / 'inserts_microct.sql'

# ---------------------------------------------------------------------------
# Expected descriptor labels
# ---------------------------------------------------------------------------

NERVE_MORPH_DESCRIPTORS = [
    'nerve cross section area um2',
    'nerve cross section perimeter um',
    'nerve cross section diameter um',
    'nerve cross section centroid-x um',
    'nerve cross section centroid-y um',
    'nerve cross section major axis um',
    'nerve cross section minor axis um',
    'nerve cross section angle degree',
]

FASCICLE_MORPH_DESCRIPTORS = [
    'fascicle cross section area um2',
    'fascicle cross section diameter um',
    'fascicle cross section centroid-0 um',
    'fascicle cross section centroid-1 um',
    'fascicle cross section ellipse major axis um',
    'fascicle cross section ellipse minor axis um',
    'fascicle cross section ellipse angle degree',
]

SUMMARY_MORPH_DESCRIPTORS = [
    'median nerve diameter mm',
    'sd nerve diameter mm',
    'median nerve area mm2',
    'sd nerve area mm2',
    'endoneurial area mm2',
    'fascicle count',
    'avg fascicle diameter mm',
    'sd fascicle diameter mm',
    'min fascicle diameter mm',
    'max fascicle diameter mm',
    'measurement distance mm',
    'measurement frame',
    'global distance mm',
]

EDGE_DESCRIPTORS_CAT = [
    'fascicleEdgeIdentity',
    'fascicleEdgeSplit',
    'fascicleEdgeMerge',
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _psql(*, sql=None, file=None, database='quantdb_test'):
    """Run psql against quantdb_test."""
    cmd = [
        'psql',
        '-U',
        'postgres',
        '-h',
        'localhost',
        '-p',
        '5432',
        '-d',
        database,
        '-v',
        'ON_ERROR_STOP=on',
    ]
    if file is not None:
        cmd.extend(['-f', str(file)])
    elif sql is not None:
        cmd.extend(['-c', sql])
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


@pytest.fixture(scope='module')
def apply_microct_sql(rebuild_database):
    """Apply inserts_microct.sql to quantdb_test once per module."""
    assert _INSERTS_MICROCT.exists(), f'Missing SQL file: {_INSERTS_MICROCT}'
    _psql(file=_INSERTS_MICROCT)


@pytest.fixture(scope='module')
def reflected(apply_microct_sql) -> Generator[ReflectedModels, None, None]:
    """Reflect quantdb_test schema once per module."""
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
    """Provide a fresh session per test."""
    sess = reflected.Session()
    yield sess
    sess.close()


# ---------------------------------------------------------------------------
# VAL-SCHEMA-001: Units mm and mm2 exist
# ---------------------------------------------------------------------------


class TestUnits:
    def test_mm_unit_exists(self, session):
        row = session.execute(sql_text("SELECT id, label FROM quantdb.units WHERE label = 'mm'")).fetchone()
        assert row is not None, "Unit 'mm' not found"
        assert row.label == 'mm'

    def test_mm2_unit_exists(self, session):
        row = session.execute(sql_text("SELECT id, label FROM quantdb.units WHERE label = 'mm2'")).fetchone()
        assert row is not None, "Unit 'mm2' not found"
        assert row.label == 'mm2'


# ---------------------------------------------------------------------------
# VAL-SCHEMA-002: quant_agg_type enum includes sd
# ---------------------------------------------------------------------------


class TestAggType:
    def test_sd_in_quant_agg_type(self, session):
        rows = session.execute(sql_text('SELECT unnest(enum_range(' 'NULL::quantdb.quant_agg_type)) AS val')).fetchall()
        values = [r.val for r in rows]
        assert 'sd' in values, f"'sd' not found in quant_agg_type, got: {values}"


# ---------------------------------------------------------------------------
# VAL-SCHEMA-003: Nerve morphology descriptors_quant exist
# ---------------------------------------------------------------------------


class TestNerveMorphologyDescriptors:
    @pytest.mark.parametrize('label', NERVE_MORPH_DESCRIPTORS)
    def test_nerve_descriptor_exists(self, session, label):
        row = session.execute(
            sql_text('SELECT id, label FROM quantdb.descriptors_quant ' 'WHERE label = :lbl'),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' not found"

    @pytest.mark.parametrize('label', NERVE_MORPH_DESCRIPTORS)
    def test_nerve_descriptor_has_valid_unit(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.unit, u.label AS unit_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.units u ON dq.unit = u.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid unit FK"

    @pytest.mark.parametrize('label', NERVE_MORPH_DESCRIPTORS)
    def test_nerve_descriptor_has_valid_aspect(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.aspect, a.label AS aspect_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.aspects a ON dq.aspect = a.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid aspect FK"

    @pytest.mark.parametrize('label', NERVE_MORPH_DESCRIPTORS)
    def test_nerve_descriptor_has_valid_domain(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.domain, di.label AS domain_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.descriptors_inst di ON dq.domain = di.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid domain FK"
        assert row.domain_label == 'nerve-cross-section'


# ---------------------------------------------------------------------------
# VAL-SCHEMA-004: Fascicle morphology descriptors_quant exist
# ---------------------------------------------------------------------------


class TestFascicleMorphologyDescriptors:
    @pytest.mark.parametrize('label', FASCICLE_MORPH_DESCRIPTORS)
    def test_fascicle_descriptor_exists(self, session, label):
        row = session.execute(
            sql_text('SELECT id, label FROM quantdb.descriptors_quant ' 'WHERE label = :lbl'),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' not found"

    @pytest.mark.parametrize('label', FASCICLE_MORPH_DESCRIPTORS)
    def test_fascicle_descriptor_has_valid_unit(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.unit, u.label AS unit_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.units u ON dq.unit = u.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid unit FK"

    @pytest.mark.parametrize('label', FASCICLE_MORPH_DESCRIPTORS)
    def test_fascicle_descriptor_has_valid_aspect(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.aspect, a.label AS aspect_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.aspects a ON dq.aspect = a.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid aspect FK"

    @pytest.mark.parametrize('label', FASCICLE_MORPH_DESCRIPTORS)
    def test_fascicle_descriptor_has_valid_domain(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.domain, di.label AS domain_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.descriptors_inst di ON dq.domain = di.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid domain FK"
        assert row.domain_label == 'fascicle-cross-section'


# ---------------------------------------------------------------------------
# VAL-SCHEMA-005: Summary morphology descriptors_quant exist in mm/mm2
# ---------------------------------------------------------------------------


class TestSummaryMorphologyDescriptors:
    @pytest.mark.parametrize('label', SUMMARY_MORPH_DESCRIPTORS)
    def test_summary_descriptor_exists(self, session, label):
        row = session.execute(
            sql_text('SELECT id, label FROM quantdb.descriptors_quant ' 'WHERE label = :lbl'),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' not found"

    def test_mm_unit_descriptors(self, session):
        """Summary descriptors with mm should use the mm unit."""
        mm_labels = [lbl for lbl in SUMMARY_MORPH_DESCRIPTORS if 'mm' in lbl and 'mm2' not in lbl]
        for label in mm_labels:
            row = session.execute(
                sql_text(
                    'SELECT u.label AS unit_label '
                    'FROM quantdb.descriptors_quant dq '
                    'JOIN quantdb.units u ON dq.unit = u.id '
                    'WHERE dq.label = :lbl'
                ),
                {'lbl': label},
            ).fetchone()
            assert row is not None, f"Descriptor '{label}' unit FK invalid"
            assert row.unit_label == 'mm', f"Descriptor '{label}' expected unit 'mm', " f"got '{row.unit_label}'"

    def test_mm2_unit_descriptors(self, session):
        """Summary descriptors with mm2 should use the mm2 unit."""
        mm2_labels = [lbl for lbl in SUMMARY_MORPH_DESCRIPTORS if 'mm2' in lbl]
        for label in mm2_labels:
            row = session.execute(
                sql_text(
                    'SELECT u.label AS unit_label '
                    'FROM quantdb.descriptors_quant dq '
                    'JOIN quantdb.units u ON dq.unit = u.id '
                    'WHERE dq.label = :lbl'
                ),
                {'lbl': label},
            ).fetchone()
            assert row is not None, f"Descriptor '{label}' unit FK invalid"
            assert row.unit_label == 'mm2', f"Descriptor '{label}' expected unit 'mm2', " f"got '{row.unit_label}'"

    @pytest.mark.parametrize('label', SUMMARY_MORPH_DESCRIPTORS)
    def test_summary_descriptor_has_valid_aspect(self, session, label):
        row = session.execute(
            sql_text(
                'SELECT dq.aspect, a.label AS aspect_label '
                'FROM quantdb.descriptors_quant dq '
                'JOIN quantdb.aspects a ON dq.aspect = a.id '
                'WHERE dq.label = :lbl'
            ),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor '{label}' has NULL or invalid aspect FK"


# ---------------------------------------------------------------------------
# VAL-SCHEMA-006: GraphML edge descriptors_cat exist
# ---------------------------------------------------------------------------


class TestEdgeDescriptorsCat:
    @pytest.mark.parametrize('label', EDGE_DESCRIPTORS_CAT)
    def test_edge_descriptor_exists(self, session, label):
        row = session.execute(
            sql_text('SELECT id, label, range FROM quantdb.descriptors_cat ' 'WHERE label = :lbl'),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Descriptor_cat '{label}' not found"
        assert row.range == 'controlled', f"Expected range 'controlled', got '{row.range}'"


# ---------------------------------------------------------------------------
# VAL-SCHEMA-007: All new descriptors have valid FK references
# ---------------------------------------------------------------------------


class TestFKIntegrity:
    def test_no_orphan_descriptors_quant_unit(self, session):
        """Every descriptors_quant with non-null unit should have valid FK."""
        rows = session.execute(
            sql_text(
                'SELECT dq.label FROM quantdb.descriptors_quant dq '
                'LEFT JOIN quantdb.units u ON dq.unit = u.id '
                'WHERE dq.unit IS NOT NULL AND u.id IS NULL'
            )
        ).fetchall()
        assert len(rows) == 0, f'Orphan unit FKs: {[r.label for r in rows]}'

    def test_no_orphan_descriptors_quant_aspect(self, session):
        """Every descriptors_quant with non-null aspect has valid FK."""
        rows = session.execute(
            sql_text(
                'SELECT dq.label FROM quantdb.descriptors_quant dq '
                'LEFT JOIN quantdb.aspects a ON dq.aspect = a.id '
                'WHERE dq.aspect IS NOT NULL AND a.id IS NULL'
            )
        ).fetchall()
        assert len(rows) == 0, f'Orphan aspect FKs: {[r.label for r in rows]}'

    def test_no_orphan_descriptors_quant_domain(self, session):
        """Every descriptors_quant with non-null domain has valid FK."""
        rows = session.execute(
            sql_text(
                'SELECT dq.label FROM quantdb.descriptors_quant dq '
                'LEFT JOIN quantdb.descriptors_inst di '
                'ON dq.domain = di.id '
                'WHERE dq.domain IS NOT NULL AND di.id IS NULL'
            )
        ).fetchall()
        assert len(rows) == 0, f'Orphan domain FKs: {[r.label for r in rows]}'

    def test_boolean_controlled_terms_exist(self, session):
        """Boolean controlled terms 'true' and 'false' must exist."""
        for val in ('true', 'false'):
            row = session.execute(
                sql_text('SELECT id FROM quantdb.controlled_terms ' 'WHERE label = :lbl'),
                {'lbl': val},
            ).fetchone()
            assert row is not None, f"Controlled term '{val}' not found"


# ---------------------------------------------------------------------------
# VAL-SCHEMA-008: SQL inserts file is idempotent
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_run_twice_no_errors(self, apply_microct_sql):
        """Running inserts_microct.sql a second time should not error."""
        # First run already done by apply_microct_sql fixture.
        # Run a second time to verify idempotency.
        _psql(file=_INSERTS_MICROCT)


# ---------------------------------------------------------------------------
# Additional: New aspects have valid aspect_parent entries
# ---------------------------------------------------------------------------


class TestNewAspects:
    @pytest.mark.parametrize(
        'label',
        ['major-axis', 'minor-axis', 'count-fascicle', 'area-endoneurial', 'frame-index'],
    )
    def test_new_aspect_exists(self, session, label):
        row = session.execute(
            sql_text('SELECT id, label FROM quantdb.aspects ' 'WHERE label = :lbl'),
            {'lbl': label},
        ).fetchone()
        assert row is not None, f"Aspect '{label}' not found"

    @pytest.mark.parametrize(
        'child,parent',
        [
            ('major-axis', 'length'),
            ('minor-axis', 'length'),
            ('count-fascicle', 'count'),
            ('area-endoneurial', 'area'),
        ],
    )
    def test_aspect_parent_entry(self, session, child, parent):
        row = session.execute(
            sql_text(
                'SELECT ap.id, ap.parent '
                'FROM quantdb.aspect_parent ap '
                'JOIN quantdb.aspects ac ON ap.id = ac.id '
                'JOIN quantdb.aspects ap2 ON ap.parent = ap2.id '
                'WHERE ac.label = :child AND ap2.label = :parent'
            ),
            {'child': child, 'parent': parent},
        ).fetchone()
        assert row is not None, f'aspect_parent entry ({child} -> {parent}) not found'
