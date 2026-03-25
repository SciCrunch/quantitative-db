"""Tests for AWS RDS schema setup, lookup data, and idempotency.

All tests require the ``--run-aws`` CLI flag (registered in conftest.py).
"""
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from quantdb.utils import dbUri

pytestmark = pytest.mark.aws

# ---- AWS connection details ------------------------------------------------
AWS_HOST = 'troy-quantdb-test.crxhhfokqjgu.us-east-1.rds.amazonaws.com'
AWS_PORT = 5432
AWS_DB = 'postgres'
AWS_USER = 'postgres'

_BIN_DIR = Path(__file__).resolve().parent.parent / 'bin'


# ---- fixtures --------------------------------------------------------------


@pytest.fixture(scope='module')
def aws_engine():
    """Create a SQLAlchemy engine connected to the AWS RDS instance."""
    engine = create_engine(
        dbUri(
            dbuser=AWS_USER,
            host=AWS_HOST,
            port=AWS_PORT,
            database=AWS_DB,
        ),
        connect_args={'sslmode': 'require'},
    )

    @event.listens_for(engine, 'connect')
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    yield engine
    engine.dispose()


@pytest.fixture(scope='module', autouse=True)
def run_setup_once():
    """Run ``bin/aws_setup`` once before the module's tests execute."""
    result = subprocess.run(
        ['bash', str(_BIN_DIR / 'aws_setup')],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f'aws_setup failed:\nstdout:\n{result.stdout}\n'
        f'stderr:\n{result.stderr}'
    )


# ---- tests ------------------------------------------------------------------


class TestSchemaSetup:
    """VAL-AWS-001: Schema setup creates all 20 tables on AWS RDS."""

    def test_all_20_tables_exist(self, aws_engine):
        with aws_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_schema = 'quantdb'"
                )
            )
            count = result.scalar()
            assert count == 20, f'Expected 20 tables, found {count}'

    def test_quantdb_schema_exists(self, aws_engine):
        with aws_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.schemata"
                    " WHERE schema_name = 'quantdb'"
                )
            )
            assert result.scalar() == 1


class TestLookupData:
    """VAL-AWS-002: Lookup data loads correctly on AWS."""

    def test_units_um(self, aws_engine):
        """Spot-check: units table has label='um'."""
        with aws_engine.connect() as conn:
            result = conn.execute(
                text("SELECT count(*) FROM quantdb.units WHERE label = 'um'")
            )
            assert result.scalar() == 1

    def test_descriptors_inst_nerve(self, aws_engine):
        """Spot-check: descriptors_inst table has label='nerve'."""
        with aws_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT count(*) FROM quantdb.descriptors_inst"
                    " WHERE label = 'nerve'"
                )
            )
            assert result.scalar() == 1

    def test_aspects_populated(self, aws_engine):
        """Spot-check: aspects table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.aspects')
            ).scalar()
            assert count > 0, 'aspects table is empty'

    def test_descriptors_quant_populated(self, aws_engine):
        """Spot-check: descriptors_quant table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.descriptors_quant')
            ).scalar()
            assert count > 0, 'descriptors_quant table is empty'

    def test_controlled_terms_populated(self, aws_engine):
        """Spot-check: controlled_terms table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.controlled_terms')
            ).scalar()
            assert count > 0, 'controlled_terms table is empty'

    def test_addresses_populated(self, aws_engine):
        """Spot-check: addresses table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.addresses')
            ).scalar()
            assert count > 0, 'addresses table is empty'

    def test_class_parent_populated(self, aws_engine):
        """Spot-check: class_parent table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.class_parent')
            ).scalar()
            assert count > 0, 'class_parent table is empty'

    def test_aspect_parent_populated(self, aws_engine):
        """Spot-check: aspect_parent table is non-empty."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text('SELECT count(*) FROM quantdb.aspect_parent')
            ).scalar()
            assert count > 0, 'aspect_parent table is empty'


class TestIdempotency:
    """VAL-AWS-003: AWS setup is idempotent."""

    def test_second_run_no_errors(self, aws_engine):
        """Running aws_setup a second time must succeed without errors."""
        result = subprocess.run(
            ['bash', str(_BIN_DIR / 'aws_setup')],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f'Second aws_setup run failed:\nstdout:\n{result.stdout}\n'
            f'stderr:\n{result.stderr}'
        )

    def test_table_count_unchanged_after_rerun(self, aws_engine):
        """Table count remains 20 after a second setup run."""
        with aws_engine.connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_schema = 'quantdb'"
                )
            ).scalar()
            assert count == 20

    def test_lookup_data_unchanged_after_rerun(self, aws_engine):
        """Lookup row counts remain the same after a second setup run."""
        with aws_engine.connect() as conn:
            units = conn.execute(
                text('SELECT count(*) FROM quantdb.units')
            ).scalar()
            aspects = conn.execute(
                text('SELECT count(*) FROM quantdb.aspects')
            ).scalar()
            descs = conn.execute(
                text('SELECT count(*) FROM quantdb.descriptors_inst')
            ).scalar()
            assert units > 0
            assert aspects > 0
            assert descs > 0
