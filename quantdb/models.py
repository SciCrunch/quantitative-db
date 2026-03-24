"""SQLAlchemy automap_base ORM reflection for the quantdb schema.

Reflects all 20 tables from the ``quantdb`` PostgreSQL schema into ORM
classes with CamelCase naming conventions.  Uses SQLAlchemy 2.0
``automap_base`` for zero-boilerplate model generation from the live
database schema.

This module is standalone -- importable without Flask -- and purely
additive to the existing raw-SQL patterns in the codebase.

Examples:
    >>> _snake_to_camel('values_quant')
    'ValuesQuant'

    >>> _snake_to_camel('obj_desc_inst')
    'ObjDescInst'

    >>> _snake_to_camel('objects_internal')
    'ObjectsInternal'
"""
from __future__ import annotations

import doctest
import os
import sys
import warnings
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import MetaData, Table, create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.automap import (
    automap_base,
    name_for_collection_relationship,
    name_for_scalar_relationship,
)
from sqlalchemy.orm import Session, sessionmaker

from quantdb.utils import dbUri

if TYPE_CHECKING:
    from quantdb.generic_ingest import SchemaGraph

# Suppress automap overlapping-relationship warnings.  These are caused by
# the partially-overlapping composite FKs in values_quant / values_cat
# (which reference both objects AND obj_desc_* via shared columns) and are
# harmless for read-only ORM access.
warnings.filterwarnings('ignore', message=r'.*overlaps.*', module=r'sqlalchemy')


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def _snake_to_camel(name: str) -> str:
    """Convert a snake_case table name to a CamelCase class name.

    Args:
        name: The snake_case table name (e.g., ``'values_quant'``).

    Returns:
        CamelCase version of the name (e.g., ``'ValuesQuant'``).

    Examples:
        >>> _snake_to_camel('values_quant')
        'ValuesQuant'
        >>> _snake_to_camel('objects_internal')
        'ObjectsInternal'
        >>> _snake_to_camel('dataset_object')
        'DatasetObject'
        >>> _snake_to_camel('obj_desc_inst')
        'ObjDescInst'
        >>> _snake_to_camel('equiv_inst')
        'EquivInst'
        >>> _snake_to_camel('objects')
        'Objects'
        >>> _snake_to_camel('controlled_terms')
        'ControlledTerms'
        >>> _snake_to_camel('aspect_parent')
        'AspectParent'
    """
    return ''.join(word.capitalize() for word in name.split('_'))


def _camel_classname_for_table(
    base: type,
    tablename: str,
    table: Table,
) -> str:
    """Generate CamelCase class names for automap ``prepare()``.

    Passed to ``AutomapBase.prepare(classname_for_table=...)``.

    Args:
        base: The automap base class (unused, required by SQLAlchemy API).
        tablename: The snake_case table name from the database.
        table: The reflected SQLAlchemy ``Table`` object (unused).

    Returns:
        CamelCase class name for the ORM model.

    Examples:
        >>> _camel_classname_for_table(None, 'values_quant', None)
        'ValuesQuant'
        >>> _camel_classname_for_table(None, 'objects', None)
        'Objects'
    """
    return _snake_to_camel(tablename)


def _disambiguated_scalar_name(
    base: type,
    local_cls: type,
    referred_cls: type,
    constraint: Any,
) -> str:
    """Name scalar relationships, disambiguating multi-FK references.

    When two FK columns on the same table both point to the same referred
    table (e.g., ``class_parent.id`` and ``class_parent.parent`` both
    reference ``descriptors_inst``), the default automap naming would
    collide.  This callback appends ``_via_<fk_col>`` to the name when
    ambiguity is detected.

    Args:
        base: The automap base class.
        local_cls: The ORM class being configured.
        referred_cls: The ORM class on the other side of the FK.
        constraint: The ``ForeignKeyConstraint`` describing the FK.

    Returns:
        A unique relationship attribute name.
    """
    referred_name = referred_cls.__name__.lower()
    if len(constraint.column_keys) == 1:
        fk_col = constraint.column_keys[0]
        if fk_col != referred_name and fk_col != 'id':
            return f'{referred_name}_via_{fk_col}'
    return name_for_scalar_relationship(
        base, local_cls, referred_cls, constraint,
    )


def _disambiguated_collection_name(
    base: type,
    local_cls: type,
    referred_cls: type,
    constraint: Any,
) -> str:
    """Name collection relationships, disambiguating multi-FK references.

    Mirror of :func:`_disambiguated_scalar_name` for the collection
    (one-to-many) side.

    Args:
        base: The automap base class.
        local_cls: The ORM class being configured.
        referred_cls: The ORM class on the other side of the FK.
        constraint: The ``ForeignKeyConstraint`` describing the FK.

    Returns:
        A unique relationship attribute name.
    """
    referred_name = referred_cls.__name__.lower()
    if len(constraint.column_keys) == 1:
        fk_col = constraint.column_keys[0]
        if fk_col != referred_name and fk_col != 'id':
            return f'{referred_name}_via_{fk_col}_collection'
    return name_for_collection_relationship(
        base, local_cls, referred_cls, constraint,
    )


# ---------------------------------------------------------------------------
# Engine creation
# ---------------------------------------------------------------------------


def get_connection_kwargs(test: bool = True) -> dict[str, Any]:
    """Get database connection keyword arguments from orthauth config.

    Args:
        test: If ``True`` (default), use ``test-db-*`` auth variables.
              If ``False``, use ``db-*`` auth variables for production.

    Returns:
        Dict with keys: ``dbuser``, ``host``, ``port``, ``database``.

    Raises:
        RuntimeError: If orthauth configuration is missing or incomplete.
    """
    from quantdb.config import auth

    prefix = 'test-db' if test else 'db'
    try:
        kwargs: dict[str, Any] = {
            k: auth.get(f'{prefix}-{k}')
            for k in ('user', 'host', 'port', 'database')
        }
    except Exception as e:
        raise RuntimeError(
            f'Failed to load orthauth config with prefix {prefix!r}: {e}'
        ) from e

    kwargs['dbuser'] = kwargs.pop('user')
    return kwargs


def create_engine_quantdb(
    test: bool = True,
    echo: bool = False,
) -> Engine:
    """Create a SQLAlchemy engine configured for the quantdb database.

    Uses orthauth config and ``dbUri`` for connection string generation.
    Sets ``search_path`` to ``quantdb, public`` on every new connection via
    an event listener, matching the role-level config in ``postgres.sql``.

    Args:
        test: If ``True`` (default), connect to the test database
              (``quantdb_test``). If ``False``, connect to production.
        echo: If ``True``, enable SQLAlchemy SQL logging. Default ``False``.

    Returns:
        A configured SQLAlchemy ``Engine`` instance.

    Raises:
        RuntimeError: If database connection cannot be established.
    """
    kwargs = get_connection_kwargs(test=test)
    engine = create_engine(dbUri(**kwargs), echo=echo)

    @event.listens_for(engine, 'connect')
    def _set_search_path(
        dbapi_connection: Any,
        connection_record: Any,
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute('SET search_path TO quantdb, public')
        cursor.close()

    return engine


# ---------------------------------------------------------------------------
# Reflected models container
# ---------------------------------------------------------------------------

#: Tables where ALL columns participate in the PK *and* are FKs.
#: automap treats these as many-to-many association tables and silently
#: skips ORM class generation.  We pre-declare them before ``prepare()``.
_ASSOCIATION_TABLE_NAMES: list[str] = [
    'dataset_object',
    'equiv_inst',
    'class_parent',
    'instance_parent',
    'aspect_parent',
]


class ReflectedModels(NamedTuple):
    """Container for reflected automap ORM classes and session factory.

    Attributes:
        engine: The SQLAlchemy Engine used for reflection.
        Session: A ``sessionmaker`` bound to the engine.
        Base: The automap ``Base`` class.  Access any class via
              ``Base.classes.<CamelCaseName>`` (except pre-declared
              association-table classes; use the NamedTuple fields for
              those).
        ObjectsInternal: ORM class for ``objects_internal``.
        Objects: ORM class for ``objects``.
        DatasetObject: ORM class for ``dataset_object``.
        Units: ORM class for ``units``.
        Aspects: ORM class for ``aspects``.
        DescriptorsInst: ORM class for ``descriptors_inst``.
        DescriptorsCat: ORM class for ``descriptors_cat``.
        DescriptorsQuant: ORM class for ``descriptors_quant``.
        ValuesInst: ORM class for ``values_inst``.
        ValuesQuant: ORM class for ``values_quant``.
        ValuesCat: ORM class for ``values_cat``.
        ControlledTerms: ORM class for ``controlled_terms``.
        Addresses: ORM class for ``addresses``.
        ObjDescInst: ORM class for ``obj_desc_inst``.
        ObjDescQuant: ORM class for ``obj_desc_quant``.
        ObjDescCat: ORM class for ``obj_desc_cat``.
        EquivInst: ORM class for ``equiv_inst``.
        ClassParent: ORM class for ``class_parent``.
        InstanceParent: ORM class for ``instance_parent``.
        AspectParent: ORM class for ``aspect_parent``.
        schema_graph: :class:`~quantdb.generic_ingest.SchemaGraph`
                      instance built during reflection, or ``None``.
    """

    engine: Engine
    Session: sessionmaker[Session]
    Base: type
    ObjectsInternal: type
    Objects: type
    DatasetObject: type
    Units: type
    Aspects: type
    DescriptorsInst: type
    DescriptorsCat: type
    DescriptorsQuant: type
    ValuesInst: type
    ValuesQuant: type
    ValuesCat: type
    ControlledTerms: type
    Addresses: type
    ObjDescInst: type
    ObjDescQuant: type
    ObjDescCat: type
    EquivInst: type
    ClassParent: type
    InstanceParent: type
    AspectParent: type
    schema_graph: SchemaGraph | None = None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def reflect_models(
    engine: Engine | None = None,
    test: bool = True,
    echo: bool = False,
) -> ReflectedModels:
    """Reflect the quantdb schema and return ORM classes with CamelCase names.

    This is the primary entry point.  It connects to the database,
    reflects all tables in the ``quantdb`` schema, and generates ORM
    classes using SQLAlchemy's ``automap_base``.

    Five tables (``dataset_object``, ``equiv_inst``, ``class_parent``,
    ``instance_parent``, ``aspect_parent``) are pre-declared because
    automap would otherwise treat them as many-to-many association
    tables and skip class generation.

    Args:
        engine: An existing SQLAlchemy ``Engine``.  If ``None``, one is
                created via orthauth config.
        test: If ``True`` (default) and *engine* is ``None``, connect to
              the test database.  Ignored when *engine* is provided.
        echo: If ``True`` and *engine* is ``None``, enable SQL logging.
              Ignored when *engine* is provided.

    Returns:
        A :class:`ReflectedModels` NamedTuple containing the engine,
        session factory, Base class, and all 20 reflected ORM classes.

    Raises:
        RuntimeError: If reflection fails or the schema has no tables.
    """
    if engine is None:
        engine = create_engine_quantdb(test=test, echo=echo)

    metadata = MetaData(schema='quantdb')
    metadata.reflect(bind=engine)

    if not metadata.tables:
        raise RuntimeError(
            'No tables found in quantdb schema. '
            'Is the database initialized?'
        )

    Base = automap_base(metadata=metadata)

    # Pre-declare classes for all-FK+PK association tables that automap
    # would silently skip.  They get mapped but are NOT added to
    # ``Base.classes`` -- we retrieve them from ``_assoc`` instead.
    _assoc: dict[str, type] = {}
    for table_name in _ASSOCIATION_TABLE_NAMES:
        table_key = f'quantdb.{table_name}'
        if table_key in metadata.tables:
            class_name = _snake_to_camel(table_name)
            cls = type(class_name, (Base,), {
                '__tablename__': table_name,
                '__table__': metadata.tables[table_key],
            })
            _assoc[class_name] = cls

    Base.prepare(
        classname_for_table=_camel_classname_for_table,
        name_for_scalar_relationship=_disambiguated_scalar_name,
        name_for_collection_relationship=_disambiguated_collection_name,
    )

    SessionFactory = sessionmaker(bind=engine)

    def _get(name: str) -> type:
        """Retrieve a class from Base.classes or the pre-declared dict."""
        try:
            return getattr(Base.classes, name)
        except AttributeError:
            return _assoc[name]

    result = ReflectedModels(
        engine=engine,
        Session=SessionFactory,
        Base=Base,
        ObjectsInternal=_get('ObjectsInternal'),
        Objects=_get('Objects'),
        DatasetObject=_get('DatasetObject'),
        Units=_get('Units'),
        Aspects=_get('Aspects'),
        DescriptorsInst=_get('DescriptorsInst'),
        DescriptorsCat=_get('DescriptorsCat'),
        DescriptorsQuant=_get('DescriptorsQuant'),
        ValuesInst=_get('ValuesInst'),
        ValuesQuant=_get('ValuesQuant'),
        ValuesCat=_get('ValuesCat'),
        ControlledTerms=_get('ControlledTerms'),
        Addresses=_get('Addresses'),
        ObjDescInst=_get('ObjDescInst'),
        ObjDescQuant=_get('ObjDescQuant'),
        ObjDescCat=_get('ObjDescCat'),
        EquivInst=_get('EquivInst'),
        ClassParent=_get('ClassParent'),
        InstanceParent=_get('InstanceParent'),
        AspectParent=_get('AspectParent'),
    )

    # Build the schema introspection graph
    from quantdb.generic_ingest import SchemaGraph
    schema_graph = SchemaGraph.from_reflected(result)
    return result._replace(schema_graph=schema_graph)


# ---------------------------------------------------------------------------
# Doctest infrastructure (docstring-test skill pattern)
# ---------------------------------------------------------------------------


def _should_skip_tests() -> bool:
    """Check whether to skip doctests.

    Returns:
        ``True`` if ``--skip-tests`` flag or ``DOCSTR_SKIP_TEST`` env var
        is set.
    """
    if os.environ.get('DOCSTR_SKIP_TEST', '').strip() in ('1', 'true', 'yes'):
        return True

    if '--skip-tests' in sys.argv:
        sys.argv.remove('--skip-tests')
        return True

    return False


def _wants_test_only() -> bool:
    """Check if script was invoked with ``--test`` or ``--tests`` flag.

    Returns:
        ``True`` if test-only mode was requested.
    """
    for flag in ('--test', '--tests'):
        if flag in sys.argv:
            sys.argv.remove(flag)
            return True
    return False


def _run_doctests() -> int:
    """Execute module doctests and return exit code.

    Returns:
        ``0`` if all tests passed, ``1`` otherwise.
    """
    results = doctest.testmod(verbose='-v' in sys.argv)
    if results.failed:
        print(f'\n\u2717 {results.failed}/{results.attempted} doctests failed.')
        return 1
    print(f'\n\u2713 All {results.attempted} doctests passed.')
    return 0


if __name__ == '__main__':
    if _wants_test_only():
        sys.exit(_run_doctests())

    if not _should_skip_tests():
        exit_code = _run_doctests()
        if exit_code != 0:
            print('Aborting: Fix failing doctests before running.')
            sys.exit(exit_code)
        print()
