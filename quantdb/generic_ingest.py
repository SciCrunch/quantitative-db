"""Schema introspection engine for quantdb.

Provides the :class:`SchemaGraph` class that introspects SQLAlchemy
automap reflected models at runtime to build a FK dependency graph with
topological sort, natural key detection, and table classification.

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

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import Table, UniqueConstraint

if TYPE_CHECKING:
    from quantdb.models import ReflectedModels


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
