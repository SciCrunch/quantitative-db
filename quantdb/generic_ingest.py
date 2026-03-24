"""Schema introspection and deep upsert engine for quantdb.

Provides the :class:`SchemaGraph` class that introspects SQLAlchemy
automap reflected models at runtime to build a FK dependency graph with
topological sort, natural key detection, and table classification.

Also provides the core FK resolution and deep upsert primitives:

- :func:`get_or_create` — race-condition-safe row upsert by natural key
- :func:`resolve_fk_value` — resolve human-readable FK values to PKs
- :func:`deep_upsert` — recursively resolve all FK columns and upsert

Examples:
    >>> from quantdb.models import reflect_models
    >>> from sqlalchemy import create_engine
    >>> from quantdb.utils import dbUri
    >>> engine = create_engine(dbUri('quantdb-test-user', 'localhost', 5432, 'quantdb_test'))
    >>> m = reflect_models(engine=engine)  # doctest: +SKIP
    >>> 'units' in m.schema_graph.tables  # doctest: +SKIP
    True
"""
from __future__ import annotations

import uuid as _uuid_mod
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy import Table, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from quantdb.models import ReflectedModels


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: Cache key: ``(table_name, frozenset_of_natural_key_items)``.
CacheKey = tuple[str, frozenset]

#: Transaction-scoped cache mapping :data:`CacheKey` to resolved PK values.
FKCache = dict[CacheKey, Any]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class FKInfo(NamedTuple):
    """Metadata for a single FK column on a table.

    Attributes:
        column: Local FK column name.
        target_table: Name of the referenced table.
        target_column: Name of the referenced column.
        target_model: ORM class for the target table, or ``None``.
        target_natural_key: Natural key columns of the target table.
    """

    column: str
    target_table: str
    target_column: str
    target_model: type | None
    target_natural_key: list[str] | None


@dataclass
class TableInfo:
    """Per-table metadata from schema introspection.

    Attributes:
        name: Table name (snake_case).
        model: ORM class mapped to this table, or ``None``.
        pk_cols: Primary key column names.
        pk_is_auto: Whether the PK is auto-generated (IDENTITY or UUID
            server default).
        fk_map: FK column name → :class:`FKInfo` for single-column FKs.
        unique_constraints: Unique constraint column tuples (excluding PK).
        natural_key: Columns forming the best natural key for lookups.
        topo_level: Level in the topological sort (0 = root).
        is_lookup: Whether this is a pre-populated lookup table.
    """

    name: str
    model: type | None
    pk_cols: list[str]
    pk_is_auto: bool
    fk_map: dict[str, FKInfo]
    unique_constraints: list[tuple[str, ...]]
    natural_key: list[str]
    topo_level: int
    is_lookup: bool


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_model_map(models: ReflectedModels) -> dict[str, type]:
    """Build a mapping from table name to ORM class.

    Iterates the :class:`ReflectedModels` NamedTuple fields to find
    fields that carry an ORM class (those with a ``__table__`` attribute).

    Args:
        models: Reflected automap models.

    Returns:
        Dict mapping snake_case table names to ORM classes.
    """
    model_map: dict[str, type] = {}
    skip = {'engine', 'Session', 'Base', 'schema_graph'}
    for field_name in models._fields:
        if field_name in skip:
            continue
        model_cls = getattr(models, field_name)
        if hasattr(model_cls, '__table__'):
            model_map[model_cls.__table__.name] = model_cls
    return model_map


def _compute_natural_key(table: Table) -> list[str]:
    """Determine the natural key columns for a table.

    Prefers the shortest unique constraint, with a tie-break that
    favours constraints containing a ``label`` column.  Falls back to
    the primary key columns when no ``UniqueConstraint`` exists.

    Args:
        table: A reflected SQLAlchemy ``Table``.

    Returns:
        List of column names forming the natural key.
    """
    unique_cols: list[tuple[str, ...]] = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            cols = tuple(c.name for c in constraint.columns)
            if cols:
                unique_cols.append(cols)

    if not unique_cols:
        # Fall back to PK columns
        return [c.name for c in table.primary_key.columns]

    # Prefer fewer columns, then prefer containing 'label'
    unique_cols.sort(key=lambda cs: (len(cs), 'label' not in cs))
    return list(unique_cols[0])


def _get_unique_constraints(table: Table) -> list[tuple[str, ...]]:
    """Get all unique constraint column tuples (excluding PK).

    Args:
        table: A reflected SQLAlchemy ``Table``.

    Returns:
        List of column-name tuples for each ``UniqueConstraint``.
    """
    result: list[tuple[str, ...]] = []
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            cols = tuple(c.name for c in constraint.columns)
            if cols:
                result.append(cols)
    return result


def _is_pk_auto(table: Table) -> bool:
    """Check if the table's primary key is auto-generated.

    Auto-generated means either ``GENERATED BY DEFAULT AS IDENTITY``
    (integer serial) or a UUID column with a server default like
    ``gen_random_uuid()``.

    Args:
        table: A reflected SQLAlchemy ``Table``.

    Returns:
        ``True`` if the PK is auto-generated, ``False`` otherwise.
        Composite PKs always return ``False``.
    """
    pk_cols = list(table.primary_key.columns)
    if len(pk_cols) != 1:
        return False
    pk_col = pk_cols[0]
    # Check for IDENTITY (PostgreSQL GENERATED BY DEFAULT AS IDENTITY)
    if getattr(pk_col, 'identity', None) is not None:
        return True
    # Check for server default (e.g., gen_random_uuid())
    if pk_col.server_default is not None:
        return True
    return False


def _detect_circular_deps(
    dep_graph: dict[str, set[str]],
) -> set[frozenset[str]]:
    """Detect pairwise circular dependencies in the FK graph.

    Scans for table pairs ``(A, B)`` where A depends on B **and** B
    depends on A.

    Args:
        dep_graph: Table name → set of table names it depends on.

    Returns:
        Set of frozensets, each containing two mutually-dependent tables.
    """
    circular: set[frozenset[str]] = set()
    for table_a, deps_a in dep_graph.items():
        for table_b in deps_a:
            if table_b in dep_graph and table_a in dep_graph[table_b]:
                circular.add(frozenset([table_a, table_b]))
    return circular


def _break_cycles(
    dep_graph: dict[str, set[str]],
    circular_deps: set[frozenset[str]],
) -> dict[str, set[str]]:
    """Break circular dependencies by removing one edge per cycle.

    For each cycle ``{A, B}`` (sorted alphabetically), removes the edge
    from the second table to the first.  For ``objects <-> objects_internal``,
    this removes ``objects_internal → objects``, preserving the DDL
    creation order where ``objects_internal`` is created first.

    Args:
        dep_graph: Original dependency graph.
        circular_deps: Cycles to break.

    Returns:
        New acyclic dependency graph (deep copy).
    """
    acyclic = {k: set(v) for k, v in dep_graph.items()}
    for cycle in circular_deps:
        tables = sorted(cycle)
        # Remove edge from alphabetically-later → earlier
        acyclic[tables[1]].discard(tables[0])
    return acyclic


def _kahn_topo_sort(
    dep_graph: dict[str, set[str]],
) -> tuple[list[str], dict[str, int]]:
    """Topological sort via Kahn's algorithm.

    Processes the graph level-by-level (BFS) so that tables at the same
    depth share a ``topo_level`` value.

    Args:
        dep_graph: Acyclic dependency graph (table → set of dependencies).

    Returns:
        Tuple of ``(ordered_table_names, table_to_level_mapping)``.

    Raises:
        RuntimeError: If the graph contains an undetected cycle.
    """
    # in_degree[A] = number of A's dependencies still in the graph
    in_degree: dict[str, int] = {}
    for node in dep_graph:
        in_degree[node] = sum(1 for dep in dep_graph[node] if dep in dep_graph)

    # reverse_graph: dependency → set of dependents
    reverse_graph: dict[str, set[str]] = {node: set() for node in dep_graph}
    for node, deps in dep_graph.items():
        for dep in deps:
            if dep in dep_graph:
                reverse_graph[dep].add(node)

    # BFS level-by-level
    queue = deque(sorted(n for n in dep_graph if in_degree[n] == 0))
    topo_order: list[str] = []
    topo_levels: dict[str, int] = {}
    level = 0

    while queue:
        next_queue: deque[str] = deque()
        while queue:
            node = queue.popleft()
            topo_order.append(node)
            topo_levels[node] = level
            for dependent in sorted(reverse_graph.get(node, set())):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)
        queue = next_queue
        level += 1

    if len(topo_order) != len(dep_graph):
        missing = set(dep_graph) - set(topo_order)
        raise RuntimeError(f'Topological sort incomplete; unresolved tables: {missing}')

    return topo_order, topo_levels


# ---------------------------------------------------------------------------
# SchemaGraph
# ---------------------------------------------------------------------------


class SchemaGraph:
    """FK dependency graph for the quantdb schema.

    Built once at reflect time by introspecting ``Base.metadata``.
    Provides topological ordering, FK column mapping, natural key
    detection, circular dependency detection, and table classification.

    Attributes:
        tables: Mapping of table name → :class:`TableInfo`.
        topo_order: Table names in topological insert order.
        circular_deps: Set of frozensets identifying circular
            dependencies (e.g., ``{frozenset({'objects',
            'objects_internal'})}``).
    """

    def __init__(
        self,
        tables: dict[str, TableInfo],
        topo_order: list[str],
        circular_deps: set[frozenset[str]],
    ) -> None:
        self.tables = tables
        self.topo_order = topo_order
        self.circular_deps = circular_deps

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_reflected(cls, models: ReflectedModels) -> SchemaGraph:
        """Build the schema graph from reflected automap models.

        Introspects ``Base.metadata`` to discover FK relationships,
        compute topological sort via Kahn's algorithm, detect natural
        keys from unique constraints, classify tables as lookup vs
        create, and find circular dependencies.

        Args:
            models: A :class:`~quantdb.models.ReflectedModels` instance
                from :func:`~quantdb.models.reflect_models`.

        Returns:
            A fully populated :class:`SchemaGraph`.
        """
        metadata = models.Base.metadata
        model_map = _build_model_map(models)

        # Collect all tables from reflected metadata
        tables_by_name: dict[str, Table] = {}
        for _full_name, table in metadata.tables.items():
            tables_by_name[table.name] = table

        # 1. Compute natural keys for all tables
        natural_keys: dict[str, list[str]] = {name: _compute_natural_key(tbl) for name, tbl in tables_by_name.items()}

        # 2. Build FK dependency graph and per-table fk_maps
        dep_graph: dict[str, set[str]] = {}
        fk_maps: dict[str, dict[str, FKInfo]] = {}

        for name, table in tables_by_name.items():
            deps: set[str] = set()
            fk_map: dict[str, FKInfo] = {}

            for fkc in table.foreign_key_constraints:
                target_table_name = fkc.referred_table.name
                if target_table_name in tables_by_name:
                    deps.add(target_table_name)

                # Only build FKInfo for single-column FK constraints
                if len(fkc.columns) == 1:
                    col_name = list(fkc.column_keys)[0]
                    target_col = list(fkc.elements)[0].column.name
                    fk_map[col_name] = FKInfo(
                        column=col_name,
                        target_table=target_table_name,
                        target_column=target_col,
                        target_model=model_map.get(target_table_name),
                        target_natural_key=natural_keys.get(
                            target_table_name,
                        ),
                    )

            dep_graph[name] = deps
            fk_maps[name] = fk_map

        # 3. Detect circular dependencies
        circular_deps = _detect_circular_deps(dep_graph)

        # 4. Break cycles and run topological sort
        acyclic = _break_cycles(dep_graph, circular_deps)
        topo_order, topo_levels = _kahn_topo_sort(acyclic)

        # 5. Determine which tables participate in cycles
        tables_in_cycles: set[str] = set()
        for cycle in circular_deps:
            tables_in_cycles.update(cycle)

        # 6. Build TableInfo for every table
        table_infos: dict[str, TableInfo] = {}
        for name, table in tables_by_name.items():
            table_infos[name] = TableInfo(
                name=name,
                model=model_map.get(name),
                pk_cols=[c.name for c in table.primary_key.columns],
                pk_is_auto=_is_pk_auto(table),
                fk_map=fk_maps[name],
                unique_constraints=_get_unique_constraints(table),
                natural_key=natural_keys[name],
                topo_level=topo_levels[name],
                is_lookup=(topo_levels[name] == 0 and name not in tables_in_cycles),
            )

        return cls(
            tables=table_infos,
            topo_order=topo_order,
            circular_deps=circular_deps,
        )


# ---------------------------------------------------------------------------
# get_or_create
# ---------------------------------------------------------------------------


def get_or_create(
    session: Session,
    Model: type,
    natural_key_cols: list[str],
    data: dict[str, Any],
) -> tuple[Any, bool]:
    """Find or create a row by natural key.

    Race-condition-safe: uses a SAVEPOINT so that an
    ``IntegrityError`` during flush rolls back only the attempted
    INSERT, then retries the SELECT.

    IDENTITY / server-default PK columns are **excluded** from the
    INSERT data so that the database generates them.

    Natural-key columns present in *data* with a ``None`` value use
    ``IS NULL`` semantics in the existence-check filter.  Columns listed
    in *natural_key_cols* but **absent** from *data* (i.e. the caller
    relies on a server default) are omitted from the filter entirely.

    Args:
        session: An open SQLAlchemy ``Session``.
        Model: The reflected ORM model class for the target table.
        natural_key_cols: Column names forming the natural key (from
            ``TableInfo.natural_key``).
        data: Column name → value mapping.  Must contain at least the
            columns needed for creation.

    Returns:
        ``(instance, created)`` where *created* is ``True`` when a new
        row was inserted.

    Raises:
        ValueError: If no filterable columns can be derived from
            *natural_key_cols* and *data*.
    """
    table = Model.__table__
    pk_col_names = {c.name for c in table.primary_key.columns}

    # -- build WHERE clause from natural key columns present in *data* --
    filters = []
    for col_name in natural_key_cols:
        if col_name not in data:
            # Server-default column omitted by caller → skip in filter
            continue
        value = data[col_name]
        col = table.c[col_name]
        if value is None:
            filters.append(col.is_(None))
        else:
            filters.append(col == value)

    if not filters:
        raise ValueError(
            f'No filter columns available for {table.name} ' f'natural key {natural_key_cols}',
        )

    # -- attempt lookup --
    stmt = select(Model).where(*filters)
    instance = session.execute(stmt).scalar_one_or_none()
    if instance is not None:
        return instance, False

    # -- build INSERT data, excluding auto-generated PK columns --
    create_data: dict[str, Any] = {}
    for col_name, value in data.items():
        col = table.c.get(col_name)
        if col is None:
            continue
        # Exclude IDENTITY or server-default PK columns
        if col_name in pk_col_names:
            if getattr(col, 'identity', None) is not None:
                continue
            if col.server_default is not None:
                continue
        create_data[col_name] = value

    # -- create with SAVEPOINT for race-condition safety --
    try:
        with session.begin_nested():
            instance = Model(**create_data)
            session.add(instance)
            session.flush()
        return instance, True
    except IntegrityError:
        # Concurrent insert won the race — retry the SELECT
        instance = session.execute(stmt).scalar_one()
        return instance, False


# ---------------------------------------------------------------------------
# resolve_fk_value
# ---------------------------------------------------------------------------


def resolve_fk_value(
    session: Session,
    schema: SchemaGraph,
    table_name: str,
    col_name: str,
    value: Any,
    cache: FKCache,
) -> Any:
    """Resolve a FK column value to the target table's PK.

    Resolution strategy depends on the Python type of *value*:

    ``str``
        If the target PK is UUID, attempt to parse the string as a UUID
        and return it directly.  Otherwise perform a single-column
        natural key lookup on the target table.

    ``dict``
        Composite natural key lookup.  Any nested FK columns within the
        dict are recursively resolved first.

    ``int`` / ``UUID`` / ``None``
        Passed through unchanged (already resolved or NULL).

    All resolved values are stored in *cache* to prevent redundant
    queries within the same transaction.

    Args:
        session: An open SQLAlchemy ``Session``.
        schema: The :class:`SchemaGraph` for FK metadata.
        table_name: Source table name (e.g. ``'descriptors_quant'``).
        col_name: FK column name on the source table (e.g. ``'unit'``).
        value: The value to resolve (``str``, ``dict``, ``int``,
            ``UUID``, or ``None``).
        cache: Transaction-scoped :data:`FKCache`.

    Returns:
        The target table's PK value (``int``, ``UUID``, or ``None``).

    Raises:
        ValueError: If the target row cannot be found.
    """
    # -- pass through already-resolved types --
    if value is None or isinstance(value, (int, _uuid_mod.UUID)):
        return value

    fk_info = schema.tables[table_name].fk_map[col_name]
    target_table = fk_info.target_table
    target_model = fk_info.target_model
    target_pk_col = fk_info.target_column
    target_natural_key = fk_info.target_natural_key

    if target_model is None:
        raise ValueError(
            f'No ORM model for target table {target_table!r} ' f'(FK {table_name}.{col_name})',
        )

    target_table_obj = target_model.__table__
    pk_col = target_table_obj.c[target_pk_col]

    # -- string value --
    if isinstance(value, str):
        # If target PK is UUID, try parsing the string directly
        if isinstance(pk_col.type, PGUUID):
            try:
                return _uuid_mod.UUID(value)
            except ValueError:
                pass  # not a UUID — fall through to natural key lookup

        # Single-column natural key lookup
        if not target_natural_key or len(target_natural_key) != 1:
            raise ValueError(
                f'Cannot resolve string value for {table_name}.{col_name}: '
                f'target {target_table} natural key is {target_natural_key}',
            )
        nk_col_name = target_natural_key[0]
        cache_key: CacheKey = (
            target_table,
            frozenset({(nk_col_name, value)}),
        )
        if cache_key in cache:
            return cache[cache_key]

        nk_col = target_table_obj.c[nk_col_name]
        stmt = select(pk_col).where(nk_col == value)
        result = session.execute(stmt).scalar_one_or_none()
        if result is None:
            raise ValueError(
                f'No {target_table} row with {nk_col_name}={value!r}',
            )
        cache[cache_key] = result
        return result

    # -- dict value (composite natural key) --
    if isinstance(value, dict):
        target_info = schema.tables[target_table]

        # Recursively resolve any nested FK columns
        resolved_dict: dict[str, Any] = {}
        for k, v in value.items():
            if k in target_info.fk_map:
                resolved_dict[k] = resolve_fk_value(
                    session,
                    schema,
                    target_table,
                    k,
                    v,
                    cache,
                )
            else:
                resolved_dict[k] = v

        # Build cache key from the resolved values
        cache_key = (
            target_table,
            frozenset(resolved_dict.items()),
        )
        if cache_key in cache:
            return cache[cache_key]

        # Build filter from the target's natural key columns
        filters = []
        for nk_col_name in target_info.natural_key:
            if nk_col_name not in resolved_dict:
                continue
            val = resolved_dict[nk_col_name]
            col = target_table_obj.c[nk_col_name]
            if val is None:
                filters.append(col.is_(None))
            else:
                filters.append(col == val)

        if not filters:
            raise ValueError(
                f'No matching natural key columns in dict for ' f'{target_table}: {resolved_dict}',
            )

        stmt = select(pk_col).where(*filters)
        result = session.execute(stmt).scalar_one_or_none()
        if result is None:
            raise ValueError(
                f'No {target_table} row matching {resolved_dict}',
            )
        cache[cache_key] = result
        return result

    # -- other types: pass through unchanged --
    return value


# ---------------------------------------------------------------------------
# deep_upsert helpers
# ---------------------------------------------------------------------------

#: Tables whose INSERT triggers call ``check_desc_inst_exists()``,
#: requiring at least one ``obj_desc_inst`` row for the object.
_TABLES_NEEDING_OBJ_DESC_INST: frozenset[str] = frozenset(
    {
        'obj_desc_quant',
        'obj_desc_cat',
        'values_quant',
        'values_cat',
    }
)

#: Default ``addresses.id`` used when auto-creating ``obj_desc_inst``
#: rows.  ``id=1`` is the ``(constant, '', single)`` address.
_DEFAULT_ADDR_FIELD: int = 1


def _infer_desc_inst(
    session: Session,
    schema: SchemaGraph,
    resolved: dict[str, Any],
) -> int | None:
    """Try to derive a ``desc_inst`` integer from related FK data.

    For tables like ``obj_desc_quant`` (which have ``desc_quant`` but no
    ``desc_inst``), look up the ``domain`` column of the referenced
    ``descriptors_quant`` row.  Similarly for ``obj_desc_cat``.

    Falls back to the first available ``descriptors_inst.id`` if no
    domain is found.

    Args:
        session: An open SQLAlchemy ``Session``.
        schema: The :class:`SchemaGraph` for model lookup.
        resolved: Resolved data dict (FK columns already integers/UUIDs).

    Returns:
        An integer ``descriptors_inst.id`` or ``None``.
    """
    # Try from descriptors_quant.domain
    desc_quant_id = resolved.get('desc_quant')
    if desc_quant_id is not None:
        dq_info = schema.tables.get('descriptors_quant')
        if dq_info is not None and dq_info.model is not None:
            dq_table = dq_info.model.__table__
            stmt = select(dq_table.c.domain).where(dq_table.c.id == desc_quant_id)
            domain_id = session.execute(stmt).scalar_one_or_none()
            if domain_id is not None:
                return domain_id

    # Try from descriptors_cat.domain
    desc_cat_id = resolved.get('desc_cat')
    if desc_cat_id is not None:
        dc_info = schema.tables.get('descriptors_cat')
        if dc_info is not None and dc_info.model is not None:
            dc_table = dc_info.model.__table__
            stmt = select(dc_table.c.domain).where(dc_table.c.id == desc_cat_id)
            domain_id = session.execute(stmt).scalar_one_or_none()
            if domain_id is not None:
                return domain_id

    # Fall back to the first descriptors_inst row
    di_info = schema.tables.get('descriptors_inst')
    if di_info is not None and di_info.model is not None:
        di_table = di_info.model.__table__
        stmt = select(di_table.c.id).limit(1)
        return session.execute(stmt).scalar_one_or_none()

    return None


def _ensure_obj_desc_inst(
    session: Session,
    schema: SchemaGraph,
    object_uuid: Any,
    desc_inst_id: int,
    cache: FKCache,
) -> None:
    """Ensure at least one ``obj_desc_inst`` row exists for *object_uuid*.

    The ``check_desc_inst_exists()`` trigger on ``obj_desc_quant``,
    ``obj_desc_cat``, ``values_quant``, and ``values_cat`` requires that
    ``obj_desc_inst`` contains a row matching ``NEW.object``.  This
    helper creates a minimal row when none exists, using the provided
    *desc_inst_id* and a default ``addr_field``.

    Args:
        session: An open SQLAlchemy ``Session``.
        schema: The :class:`SchemaGraph` for model lookup.
        object_uuid: UUID of the object that must exist in
            ``obj_desc_inst``.
        desc_inst_id: ``descriptors_inst.id`` to use for the new row.
        cache: Transaction-scoped :data:`FKCache` (unused but accepted
            for interface consistency).
    """
    odi_info = schema.tables.get('obj_desc_inst')
    if odi_info is None or odi_info.model is None:
        return

    ODI = odi_info.model
    odi_table = ODI.__table__

    # Check if ANY obj_desc_inst row exists for this object
    stmt = select(ODI).where(odi_table.c.object == object_uuid).limit(1)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return

    # Create a minimal row with the default constant address
    odi = ODI(
        object=object_uuid,
        desc_inst=desc_inst_id,
        addr_field=_DEFAULT_ADDR_FIELD,
    )
    session.add(odi)
    session.flush()


# ---------------------------------------------------------------------------
# deep_upsert
# ---------------------------------------------------------------------------


def deep_upsert(
    session: Session,
    Model: type,
    schema: SchemaGraph,
    data: dict[str, Any],
    cache: FKCache | None = None,
) -> Any:
    """Recursively resolve FK columns and upsert a row.

    1. Every FK column whose value is a ``str`` or ``dict`` is resolved
       to the target table's PK via :func:`resolve_fk_value`.
    2. Trigger-ordering prerequisites are satisfied automatically:
       tables that fire ``check_desc_inst_exists()`` get a minimal
       ``obj_desc_inst`` row created first.
    3. The row is inserted or looked up via :func:`get_or_create`.

    ENUM columns are accepted as plain strings — SQLAlchemy and
    PostgreSQL handle the conversion transparently.

    Args:
        session: An open SQLAlchemy ``Session``.
        Model: The reflected ORM model class for the target table.
        schema: The :class:`SchemaGraph` for FK metadata.
        data: Column name → value mapping.  FK columns may contain
            ``str`` (single natural key), ``dict`` (composite natural
            key), ``int``/``UUID`` (pre-resolved), or ``None``.
        cache: Optional transaction-scoped :data:`FKCache`.  When
            ``None`` a fresh cache is created.  Pass a shared cache
            across :func:`deep_upsert` calls to prevent redundant
            queries.

    Returns:
        The ORM instance (existing or newly created).
    """
    if cache is None:
        cache = {}

    table_name = Model.__table__.name
    table_info = schema.tables[table_name]

    # -- 1. Resolve all FK columns --
    resolved: dict[str, Any] = dict(data)
    for col_name in list(resolved.keys()):
        if col_name in table_info.fk_map and resolved[col_name] is not None:
            resolved[col_name] = resolve_fk_value(
                session,
                schema,
                table_name,
                col_name,
                resolved[col_name],
                cache,
            )

    # -- 2. Auto-ensure trigger-ordering prerequisites --
    if table_name in _TABLES_NEEDING_OBJ_DESC_INST:
        object_uuid = resolved.get('object')
        if object_uuid is not None:
            # Derive desc_inst from the resolved data or fall back to a
            # reasonable default: the data's own desc_inst column, or
            # the domain of the referenced desc_quant/desc_cat, or the
            # first available descriptors_inst row.
            desc_inst_id = resolved.get('desc_inst')
            if desc_inst_id is None:
                desc_inst_id = _infer_desc_inst(session, schema, resolved)
            if desc_inst_id is not None:
                _ensure_obj_desc_inst(
                    session,
                    schema,
                    object_uuid,
                    desc_inst_id,
                    cache,
                )

    # -- 3. get_or_create by natural key --
    instance, _created = get_or_create(
        session,
        Model,
        table_info.natural_key,
        resolved,
    )
    return instance
