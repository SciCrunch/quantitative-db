"""
Automap-based database client for dynamic model reflection.

This module provides a session factory that uses SQLAlchemy's automap_base
to dynamically reflect database models, eliminating the need for hardcoded
ORM classes that must be kept in sync with the database schema.
"""

import warnings
from functools import lru_cache
from typing import Any, Dict, Tuple

from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.exc import SAWarning
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session

# Suppress SQLAlchemy automap warnings
warnings.filterwarnings('ignore', category=SAWarning)

from quantdb.config import auth
from quantdb.utils import dbUri


def _name_for_collection(base, local_cls, referred_cls, constraint):
    """Custom naming for collection relationships to avoid conflicts."""
    if local_cls.__name__ == referred_cls.__name__:
        if constraint.name:
            return constraint.name.replace('_fkey', '') + '_collection'
        return 'child_collection'
    if constraint.name:
        return constraint.name.replace('_fkey', '_collection')
    return referred_cls.__name__.lower() + '_collection'


def reflect_models(engine, schema: str = 'quantdb') -> Tuple[Any, Dict[str, Any]]:
    """
    Dynamically reflect database models using automap.

    Parameters
    ----------
    engine : sqlalchemy.Engine
        SQLAlchemy engine connected to the database.
    schema : str
        Database schema name (default: 'quantdb').

    Returns
    -------
    tuple
        (Base, models) where Base is the automap base and models is a
        dictionary mapping table names to model classes.
    """
    metadata = MetaData()

    # Try reflecting with schema first, then without
    try:
        metadata.reflect(bind=engine, schema=schema)
    except Exception:
        metadata.reflect(bind=engine)

    Base = automap_base(metadata=metadata)

    try:
        Base.prepare(autoload_with=engine, name_for_collection_relationship=_name_for_collection)
    except Exception:
        # Fallback without custom naming
        Base = automap_base(metadata=metadata)
        Base.prepare(autoload_with=engine)

    # Build models dictionary with both class names and table names as keys
    models = {}
    for cls_name in dir(Base.classes):
        if cls_name.startswith('_'):
            continue
        try:
            cls = getattr(Base.classes, cls_name)
            models[cls_name] = cls
            if hasattr(cls, '__table__'):
                models[cls.__table__.name] = cls
        except AttributeError:
            continue

    # Also include raw tables for association tables
    for table_name, table in Base.metadata.tables.items():
        clean_name = table_name.split('.')[-1] if '.' in table_name else table_name
        if clean_name not in models:
            models[f't_{clean_name}'] = table

    return Base, models


def get_automap_session(
    test: bool = False, echo: bool = False, schema: str = 'quantdb'
) -> Tuple[Session, Dict[str, Any]]:
    """
    Get a SQLAlchemy session with dynamically reflected models.

    Parameters
    ----------
    test : bool
        If True, connect to test database.
    echo : bool
        If True, SQLAlchemy will log all statements.
    schema : str
        Database schema name (default: 'quantdb').

    Returns
    -------
    tuple
        (session, models) where session is the SQLAlchemy session and
        models is a dictionary mapping table names to model classes.
    """
    if test:
        dbkwargs = {
            'dbuser': 'quantdb-test-admin',
            'host': 'localhost',
            'port': 5432,
            'database': auth.get('test-db-database') or 'quantdb_test',
            'password': 'tom-is-cool',
        }
    else:
        dbkwargs = {k: auth.get(f'db-{k}') for k in ('user', 'host', 'port', 'database')}
        dbkwargs['dbuser'] = dbkwargs.pop('user')

    engine = create_engine(dbUri(**dbkwargs))
    engine.echo = echo

    Base, models = reflect_models(engine, schema)
    session = Session(engine)

    return session, models


def get_table_dependencies(models: Dict[str, Any]) -> Dict[str, set]:
    """
    Get foreign key dependencies for all tables.

    Parameters
    ----------
    models : dict
        Dictionary of model classes from reflect_models().

    Returns
    -------
    dict
        Dictionary mapping table names to sets of table names they depend on.
    """
    dependencies = {}

    for name, model in models.items():
        if name.startswith('t_') or not hasattr(model, '__table__'):
            continue

        table = model.__table__
        deps = set()

        for fk in table.foreign_keys:
            ref_table = fk.column.table.name
            if ref_table != table.name:  # Exclude self-references
                deps.add(ref_table)

        dependencies[table.name] = deps

    return dependencies


def topological_sort_tables(dependencies: Dict[str, set]) -> list:
    """
    Topologically sort tables based on foreign key dependencies.

    Handles cycles gracefully by skipping back-edges.

    Parameters
    ----------
    dependencies : dict
        Dictionary from get_table_dependencies().

    Returns
    -------
    list
        List of table names in insertion order (dependencies first).
    """
    result = []
    visited = set()
    temp_mark = set()

    def visit(node):
        if node in temp_mark:
            # Cycle detected - skip this edge
            return
        if node in visited:
            return

        temp_mark.add(node)

        for dep in dependencies.get(node, set()):
            if dep in dependencies:
                visit(dep)

        temp_mark.remove(node)
        visited.add(node)
        result.append(node)

    for node in dependencies:
        if node not in visited:
            visit(node)

    return result


def get_insert_order(models: Dict[str, Any]) -> list:
    """
    Get the correct insertion order for tables.

    Parameters
    ----------
    models : dict
        Dictionary of model classes from reflect_models().

    Returns
    -------
    list
        List of table names in the order they should be inserted.
    """
    deps = get_table_dependencies(models)
    return topological_sort_tables(deps)
