#!/usr/bin/env python3
"""
Extract database schema from production database and generate timestamped models file.

***** THIS SCRIPT IS 100% READ-ONLY *****
- NEVER writes to the database
- NEVER modifies any data
- ONLY reads schema metadata using SELECT queries
- Uses quantdb-user which has READ-ONLY permissions

Usage:
    python quantdb/extract_schema.py [--test]

Options:
    --test: Use test database instead of production
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from textwrap import dedent

import sqlalchemy.types as types
from rich import print as rprint

# Rich for beautiful output
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table as RichTable
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from quantdb.config import auth
from quantdb.utils import dbUri, log

console = Console()


def get_python_type(sql_type):
    """Convert SQLAlchemy SQL type to Python type string for models."""
    type_map = {
        types.Integer: 'Integer',
        types.String: 'String',
        types.Text: 'Text',
        types.Boolean: 'Boolean',
        types.DateTime: 'DateTime',
        types.Date: 'Date',
        types.Time: 'Time',
        types.Float: 'Float',
        types.Numeric: 'Numeric',
        types.DECIMAL: 'Numeric',
        types.UUID: 'Uuid',
        types.JSON: 'JSON',
        types.Enum: 'Enum',
    }

    # Handle PostgreSQL specific types
    type_str = str(type(sql_type).__name__)
    if type_str == 'UUID':
        return 'Uuid'
    elif type_str == 'JSONB':
        return 'JSONB'
    elif type_str == 'VARCHAR':
        return f'String({sql_type.length})' if hasattr(sql_type, 'length') and sql_type.length else 'String'
    elif type_str == 'TEXT':
        return 'Text'
    elif type_str == 'INTEGER':
        return 'Integer'
    elif type_str == 'NUMERIC':
        return 'Numeric'
    elif type_str == 'TIMESTAMP':
        return 'DateTime'
    elif isinstance(sql_type, types.Enum):
        return f"Enum({', '.join(repr(e) for e in sql_type.enums)}, name='{sql_type.name}')"

    # Default fallback
    for sql_class, py_type in type_map.items():
        if isinstance(sql_type, sql_class):
            return py_type

    return str(type(sql_type).__name__)


def get_class_docstring(table_name):
    """Get custom docstring for specific tables."""
    docstrings = {
        'addresses': '''"""Addresses of data

    Parameters
    ----------
    id : int
        Unique identifier for the address.
    addr_type : str, optional
        Type of address.
    value_type : str, optional
        Type of value.
    addr_field : str, optional
        Address field.
    curator_note : str, optional
        Curator note.

    Example
    -------
    #/path-metadata/data/#int/dataset_relative_path
    """''',
        'aspects': '''"""Aspects of data

    Parameters
    ----------
    id : int
        Unique identifier for the aspect.
    label : str
        Label of the aspect.
    iri : str
        IRI of the aspect.
    description : str, optional
        Description of the aspect.

    Example
    -------
    label: "distance"
    iri: "http://uri.interlex.org/tgbugs/uris/readable/aspect/distance"
    """''',
        'controlled_terms': '''"""Controlled terms

    Parameters
    ----------
    id : int
        Unique identifier for the controlled term.
    label : str
        Label of the controlled term.
    iri : str
        IRI of the controlled term.
    """''',
        'descriptors_inst': '''"""Descriptors Instance

    Parameters
    ----------
    id : int
        Unique identifier for the descriptor.
    label : str
        Label of the descriptor.
    iri : str
        IRI of the descriptor.
    description : str, optional
        Description of the descriptor.

    """''',
        'objects': '''"""
    Represents an object in the database with various relationships and constraints.

    Attributes
    ----------
    id : Uuid
        Unique identifier for the object.
    id_type : Enum
        Type of the remote ID, can be one of 'organization', 'dataset', 'collection', 'package', or 'quantdb'.
    id_file : Integer
        Identifier for the file associated with the object.
    id_internal : Uuid
        Internal identifier for the object.

    Relationships
    -------------
    objects : Mapped["Objects"]
        Relationship to other objects through the 'dataset_object' table.
    objects_ : Mapped["Objects"]
        Reverse relationship to other objects through the 'dataset_object' table.
    obj_desc_inst : Mapped[List["ObjDescInst"]]
        Relationship to object description instances.
    values_inst : Mapped[List["ValuesInst"]]
        Relationship to value instances.
    obj_desc_cat : Mapped[List["ObjDescCat"]]
        Relationship to object description categories.
    obj_desc_quant : Mapped[List["ObjDescQuant"]]
        Relationship to object description quantities.
    values_cat : Mapped[List["ValuesCat"]]
        Relationship to value categories.
    values_quant : Mapped[List["ValuesQuant"]]
        Relationship to value quantities.

    Constraints
    -----------
    __table_args__ : tuple
        Contains various constraints and indexes for the table:
        - CheckConstraint to ensure 'id_file' is not NULL if 'id_type' is 'package'.
        - CheckConstraint to ensure 'id_internal' is not NULL and 'id' equals 'id_internal' if 'id_type' is 'quantdb'.
        - PrimaryKeyConstraint on 'id'.
        - Index on 'id_internal'.
    """''',
        'descriptors_quant': '''"""
    DescriptorsQuant model representing quantitative descriptors.
    Attributes
    ----------
    id : int
        Primary key of the descriptor.
    shape : str
        Shape of the descriptor, default is 'scalar'.
    label : str
        Label of the descriptor.
    aggregation_type : str
        Type of aggregation, default is 'instance'.
    unit : int
        Foreign key referencing the unit.
    aspect : int
        Foreign key referencing the aspect.
    domain : int
        Foreign key referencing the domain.
    description : str
        Description of the descriptor.
    curator_note : str
        Notes from the curator.
    Relationships
    -------------
    aspects : Optional[Aspects]
        Relationship to the Aspects model.
    descriptors_inst : Optional[DescriptorsInst]
        Relationship to the DescriptorsInst model.
    units : Optional[Units]
        Relationship to the Units model.
    obj_desc_quant : List[ObjDescQuant]
        Relationship to the ObjDescQuant model.
    values_quant : List[ValuesQuant]
        Relationship to the ValuesQuant model.
    """''',
        'values_inst': '''"""
    Represents an instance of values in the database.

    Attributes
    ----------
    id : int
        The primary key of the values instance.
    type : str
        The type of the instance, which can be 'subject', 'sample', or 'below'.
    id_sub : str
        The subject identifier.
    desc_inst : int
        The descriptor instance identifier.
    dataset : UUID
        The dataset identifier.
    id_formal : str
        The formal identifier.
    local_identifier : str
        The local identifier.
    id_sam : str
        The sample identifier.
    objects : Optional[Objects]
        The related objects.
    descriptors_inst : Optional[DescriptorsInst]
        The related descriptor instances.
    values_inst : ValuesInst
        The related values instances through the 'equiv_inst' table.
    values_inst_ : ValuesInst
        The related values instances through the 'equiv_inst' table.
    values_inst1 : ValuesInst
        The related values instances through the 'instance_parent' table.
    values_inst2 : ValuesInst
        The related values instances through the 'instance_parent' table.
    values_cat : List[ValuesCat]
        The related categorical values.
    values_quant : List[ValuesQuant]
        The related quantitative values.

    Relationships
    -------------
    objects : relationship
        Relationship to the Objects table.
    descriptors_inst : relationship
        Relationship to the DescriptorsInst table.
    values_inst : relationship
        Self-referential relationship through the 'equiv_inst' table (left to right).
    values_inst_ : relationship
        Self-referential relationship through the 'equiv_inst' table (right to left).
    values_inst1 : relationship
        Self-referential relationship through the 'instance_parent' table (id to parent).
    values_inst2 : relationship
        Self-referential relationship through the 'instance_parent' table (parent to id).
    values_cat : relationship
        Relationship to the ValuesCat table.
    values_quant : relationship
        Relationship to the ValuesQuant table.
    """''',
    }

    return docstrings.get(table_name, f'"""Table: {table_name}"""')


def get_custom_methods(table_name):
    """Get custom methods for specific tables."""
    if table_name == 'objects':
        return '''
    def __repr__(self):
        return f'<Objects(id={self.id}, id_type={self.id_type})>'

    @staticmethod
    def preprocess_id(id_value: str) -> str:
        """
        Preprocess the id to remove 'N:dataset:' if it exists.

        Parameters
        ----------
        id_value : str
            The original id value.

        Returns
        -------
        str
            The preprocessed id value.
        """
        if isinstance(id_value, str):
            if id_value.startswith('N:dataset:'):
                return id_value.replace('N:dataset:', '')
        # if isinstance(id_value, str):
        #     id_value = uuid.UUID(id_value)
        return id_value

    @validates('id')
    def validate_id(self, key: str, id_value: str) -> str:
        """
        Validate and preprocess the id before storing it.

        Parameters
        ----------
        key : str
            The key being validated.
        id_value : str
            The original id value.

        Returns
        -------
        str
            The preprocessed id value.
        """
        return self.preprocess_id(id_value)'''

    elif table_name == 'values_quant':
        return '''
    @staticmethod
    def update_desc_inst(target: 'ValuesQuant', value, oldvalue, initiator) -> None:
        """
        Automatically update desc_inst when descriptors_inst parent is updated.
        """
        if target.descriptors_inst:
            target.desc_inst = target.descriptors_inst.id

    @staticmethod
    def register_listeners() -> None:
        """
        Register event listeners for the ValuesQuant model.
        """
        event.listen(ValuesQuant.descriptors_inst, 'set', ValuesQuant.update_desc_inst)'''

    return None


def table_to_class_name(table_name):
    """Convert table_name to ClassName."""
    return ''.join(word.capitalize() for word in table_name.split('_'))


def generate_model_class(table_name, table_obj, inspector, all_tables, schema=None):
    """Generate SQLAlchemy model class code from table metadata."""

    # Get table information
    columns = inspector.get_columns(table_name, schema=schema)
    pk_constraint = inspector.get_pk_constraint(table_name, schema=schema)
    foreign_keys = inspector.get_foreign_keys(table_name, schema=schema)
    indexes = inspector.get_indexes(table_name, schema=schema)
    unique_constraints = inspector.get_unique_constraints(table_name, schema=schema)
    check_constraints = inspector.get_check_constraints(table_name, schema=schema)

    # Start building the class
    class_name = table_to_class_name(table_name)

    code_lines = []
    code_lines.append(f'class {class_name}(Base):')

    # Use custom docstring if available
    docstring = get_class_docstring(table_name)
    code_lines.append(f'    {docstring}')
    code_lines.append(f"    __tablename__ = '{table_name}'")

    # Add table args if there are constraints
    table_args = []

    # Primary key constraint
    if pk_constraint and pk_constraint['constrained_columns']:
        pk_cols = ', '.join(f"'{col}'" for col in pk_constraint['constrained_columns'])
        table_args.append(f"        PrimaryKeyConstraint({pk_cols}, name='{pk_constraint['name']}')")

    # Unique constraints
    for uc in unique_constraints:
        if uc['column_names']:
            cols = ', '.join(f"'{col}'" for col in uc['column_names'])
            table_args.append(f"        UniqueConstraint({cols}, name='{uc['name']}')")

    # Foreign key constraints
    for fk in foreign_keys:
        if fk['constrained_columns'] and fk['referred_columns']:
            const_cols = [f"'{col}'" for col in fk['constrained_columns']]
            # Add schema prefix if we have one
            if schema and schema != 'public':
                ref_cols = [f"'{schema}.{fk['referred_table']}.{col}'" for col in fk['referred_columns']]
            else:
                ref_cols = [f"'{fk['referred_table']}.{col}'" for col in fk['referred_columns']]
            table_args.append(
                f"        ForeignKeyConstraint([{', '.join(const_cols)}], [{', '.join(ref_cols)}], name='{fk['name']}')"
            )

    # Check constraints
    for cc in check_constraints:
        if cc['sqltext']:
            # Escape the SQL text properly
            sql_text = str(cc['sqltext']).replace("'", "\\'")
            table_args.append(f"        CheckConstraint('{sql_text}', name='{cc['name']}')")

    # Indexes
    for idx in indexes:
        if idx['column_names'] and not idx['unique']:  # Unique indexes are handled by unique constraints
            cols = ', '.join(f"'{col}'" for col in idx['column_names'])
            table_args.append(f"        Index('{idx['name']}', {cols})")

    # Always add schema to table_args
    if schema and schema != 'public':
        if table_args:
            code_lines.append('    __table_args__ = (')
            # Add comma after each constraint except the last one
            for i, arg in enumerate(table_args):
                if i < len(table_args) - 1:
                    code_lines.append(arg + ',')
                else:
                    code_lines.append(arg + ',')  # Also add comma before schema dict
            code_lines.append(f"        {{'schema': '{schema}'}}")
            code_lines.append('    )')
        else:
            code_lines.append(f"    __table_args__ = {{'schema': '{schema}'}}")
    elif table_args:
        code_lines.append('    __table_args__ = (')
        # Add comma after each constraint except the last one
        for i, arg in enumerate(table_args):
            if i < len(table_args) - 1:
                code_lines.append(arg + ',')
            else:
                code_lines.append(arg)
        code_lines.append('    )')

    code_lines.append('')

    # Add columns
    for column in columns:
        col_name = column['name']
        col_type = get_python_type(column['type'])

        # Build column definition - special handling for Integer with Identity
        positional_args = []  # Type and ForeignKey (positional)
        keyword_args = []     # nullable, primary_key, etc (keyword)

        # Check if this is an auto-incrementing integer primary key
        if column.get('default') is not None and 'nextval' in str(column['default']).lower():
            # Use full Identity specification
            positional_args.append('Integer')
            positional_args.append(
                """Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        )"""
            )
        else:
            positional_args.append(col_type)

        # Check if it's a foreign key (positional arg, comes after type)
        for fk in foreign_keys:
            if col_name in fk['constrained_columns']:
                ref_table = fk['referred_table']
                ref_cols = fk['referred_columns']
                if ref_cols:
                    # Add schema prefix if we have one
                    if schema and schema != 'public':
                        positional_args.append(f"ForeignKey('{schema}.{ref_table}.{ref_cols[0]}')")
                    else:
                        positional_args.append(f"ForeignKey('{ref_table}.{ref_cols[0]}')")
                break

        # Add column constraints (keyword args)
        if column.get('primary_key'):
            keyword_args.append('primary_key=True')
        if column.get('nullable') is False:
            keyword_args.append('nullable=False')
        if column.get('default') is not None and 'nextval' not in str(column.get('default', '')).lower():
            default_val = column['default']
            if default_val:
                keyword_args.append(f'server_default=text({repr(str(default_val))})')

        # Combine positional and keyword args
        col_def_parts = positional_args + keyword_args
        col_def = ', '.join(col_def_parts)
        code_lines.append(f'    {col_name} = mapped_column({col_def})')

    code_lines.append('')

    # Add relationships based on foreign keys
    relationships = generate_relationships(table_name, foreign_keys, inspector, all_tables, schema, columns)
    if relationships:
        code_lines.append('    # Relationships')
        for rel in relationships:
            code_lines.append(f'    {rel}')
        code_lines.append('')

    # Add custom methods for specific tables
    custom_methods = get_custom_methods(table_name)
    if custom_methods:
        code_lines.append(custom_methods)
        code_lines.append('')

    return '\n'.join(code_lines)


def generate_relationships(table_name, foreign_keys, inspector, all_tables, schema=None, columns=None):
    """Generate relationship definitions based on foreign keys."""
    relationships = []
    class_name = table_to_class_name(table_name)

    # Get column names if not provided
    if columns is None:
        columns = inspector.get_columns(table_name, schema=schema)
    column_names = {col['name'] for col in columns}

    # Track which relationships we've already created to avoid duplicates
    seen_relationships = set()

    # Process foreign keys to create relationships
    for fk in foreign_keys:
        if not fk['constrained_columns'] or not fk['referred_table']:
            continue

        referred_table = fk['referred_table']
        referred_class = table_to_class_name(referred_table)

        # Skip if referred table doesn't exist in our schema
        if referred_table not in all_tables:
            continue

        # Determine relationship name based on the foreign key
        fk_cols = fk['constrained_columns']

        # For single column FKs, create a relationship
        if len(fk_cols) == 1:
            fk_col = fk_cols[0]

            # Determine relationship name
            if fk_col.endswith('_id'):
                rel_name = fk_col[:-3]  # Remove _id suffix
            elif fk_col == 'id':
                rel_name = referred_table
            else:
                rel_name = fk_col

            # Check if relationship name conflicts with a column name
            if rel_name in column_names:
                # Common naming patterns for relationships to avoid conflicts
                if rel_name == 'domain':
                    rel_name = 'domain_inst'
                elif rel_name == 'aspect':
                    rel_name = 'aspects'
                elif rel_name == 'unit':
                    rel_name = 'units'
                elif rel_name == 'desc_cat':
                    rel_name = 'descriptors_cat'
                elif rel_name == 'desc_inst':
                    rel_name = 'descriptors_inst'
                elif rel_name == 'desc_quant':
                    rel_name = 'descriptors_quant'
                elif rel_name == 'object':
                    rel_name = 'objects'
                elif rel_name == 'instance':
                    rel_name = 'values_inst'
                elif rel_name == 'value_controlled':
                    rel_name = 'controlled_terms'
                else:
                    # Generic fallback: pluralize or add suffix
                    if referred_table.endswith('s'):
                        rel_name = referred_table
                    else:
                        rel_name = referred_table + 's'

                    # If still conflicts, add _ref suffix
                    if rel_name in column_names:
                        rel_name = fk_col + '_ref'

            # Avoid duplicate relationships
            rel_key = (rel_name, referred_class)
            if rel_key in seen_relationships:
                # Add a suffix to make it unique
                for i in range(1, 10):
                    new_rel_name = f'{rel_name}_{i}'
                    new_rel_key = (new_rel_name, referred_class)
                    if new_rel_key not in seen_relationships:
                        rel_name = new_rel_name
                        rel_key = new_rel_key
                        break

            seen_relationships.add(rel_key)

            # Check if this is a self-referential relationship
            if referred_table == table_name:
                # Self-referential relationship
                relationships.append(
                    f"{rel_name}: Mapped[Optional['{referred_class}']] = relationship("
                    f"'{referred_class}', foreign_keys=[{fk_col}], remote_side='[{referred_class}.id]')"
                )
            else:
                # Regular relationship
                # Determine if it's many-to-one or one-to-one based on unique constraints
                is_unique = False
                unique_constraints = inspector.get_unique_constraints(table_name, schema=schema)
                for uc in unique_constraints:
                    if set(fk_cols).issubset(set(uc['column_names'])):
                        is_unique = True
                        break

                if is_unique:
                    # One-to-one relationship
                    relationships.append(
                        f"{rel_name}: Mapped[Optional['{referred_class}']] = relationship('{referred_class}', foreign_keys=[{fk_col}])"
                    )
                else:
                    # Many-to-one relationship (most common)
                    relationships.append(
                        f"{rel_name}: Mapped[Optional['{referred_class}']] = relationship('{referred_class}', foreign_keys=[{fk_col}])"
                    )

        # For composite foreign keys, create a single relationship
        elif len(fk_cols) > 1:
            # Use the referred table name as the relationship name
            rel_name = referred_table.replace('_', '')

            # Check uniqueness
            rel_key = (rel_name, referred_class)
            if rel_key in seen_relationships:
                for i in range(1, 10):
                    new_rel_name = f'{rel_name}_{i}'
                    new_rel_key = (new_rel_name, referred_class)
                    if new_rel_key not in seen_relationships:
                        rel_name = new_rel_name
                        rel_key = new_rel_key
                        break

            seen_relationships.add(rel_key)

            fk_cols_str = ', '.join(f"'{col}'" for col in fk_cols)
            relationships.append(
                f"{rel_name}: Mapped[Optional['{referred_class}']] = relationship("
                f"'{referred_class}', foreign_keys=[{fk_cols_str}])"
            )

    # Also check for back references (tables that reference this table)
    # This creates the reverse relationships
    for other_table in all_tables:
        if other_table == table_name:
            continue

        other_fks = inspector.get_foreign_keys(other_table, schema=schema)
        for fk in other_fks:
            if fk['referred_table'] == table_name:
                other_class = table_to_class_name(other_table)

                # Determine relationship name for the collection
                rel_name = other_table
                if rel_name.endswith('s'):
                    # Already plural
                    pass
                elif rel_name.endswith('y'):
                    # Change y to ies
                    rel_name = rel_name[:-1] + 'ies'
                else:
                    # Add s for plural
                    rel_name = rel_name + 's'

                # Check uniqueness
                rel_key = (rel_name, other_class)
                if rel_key in seen_relationships:
                    for i in range(1, 10):
                        new_rel_name = f'{rel_name}_{i}'
                        new_rel_key = (new_rel_name, other_class)
                        if new_rel_key not in seen_relationships:
                            rel_name = new_rel_name
                            rel_key = new_rel_key
                            break

                seen_relationships.add(rel_key)

                # This is a one-to-many relationship (this table is referenced by other_table)
                relationships.append(
                    f"{rel_name}: Mapped[List['{other_class}']] = relationship('{other_class}', uselist=True, viewonly=True)"
                )

    return relationships


def extract_schema(use_test_db=False):
    """Extract schema from database and generate models file."""

    timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
    output_filename = f'models_{timestamp}.py'
    output_path = Path('quantdb') / output_filename

    console.print(
        Panel.fit(
            f'[bold cyan]Database Schema Extractor[/bold cyan]\n' f'[yellow]Output: {output_path}[/yellow]',
            border_style='cyan',
        )
    )

    # Database connection
    console.print('\n[cyan]Connecting to database...[/cyan]')

    # Following the pattern from ingest_local.py for proper database connection
    if use_test_db:
        # For test database - following ingest_local.py pattern
        dbkwargs = {
            'dbuser': 'quantdb-test-admin',  # Using admin since test-user lacks permissions
            'host': 'localhost',
            'port': 5432,
            'database': 'quantdb_test',
            # Note: password would come from .pgpass or could be set here for test
        }
    else:
        # For production database - READ-ONLY schema extraction
        # THIS IS READ-ONLY - NEVER WRITES TO DATABASE
        dbkwargs = {
            'dbuser': auth.get('db-user', 'quantdb-user'),  # Read-only production user
            'host': auth.get('db-host', 'sparc-nlp.cpmk2alqjf9s.us-west-2.rds.amazonaws.com'),
            'port': auth.get('db-port', 5432),
            'database': auth.get('db-database', 'quantdb_test_2025_07_28'),  # Use database from config
        }
        # Password will be retrieved from .pgpass automatically

    # Show connection info (without password)
    conn_table = RichTable(title='Database Connection', show_header=True)
    conn_table.add_column('Parameter', style='cyan')
    conn_table.add_column('Value', style='yellow')
    conn_table.add_row('Host', dbkwargs.get('host', 'N/A'))
    conn_table.add_row('Port', str(dbkwargs.get('port', 'N/A')))
    conn_table.add_row('Database', dbkwargs.get('database', 'N/A'))
    conn_table.add_row('User', dbkwargs.get('dbuser', 'N/A'))
    conn_table.add_row('Mode', '[bold yellow]READ-ONLY[/bold yellow]')
    console.print(conn_table)

    try:
        # Create engine with read-only intent
        engine = create_engine(dbUri(**dbkwargs), echo=False)

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text('SELECT version()'))
            version = result.scalar()
            console.print(f'[green]✓ Connected to PostgreSQL[/green]')
            console.print(f'[dim]  Version: {version}[/dim]\n')

        # Create inspector
        inspector = inspect(engine)

        # Get all table names - check both public and quantdb schemas
        table_names = inspector.get_table_names(schema='quantdb')
        if not table_names:
            # Fallback to public schema if quantdb schema doesn't exist
            table_names = inspector.get_table_names(schema='public')
            schema_name = 'public'
        else:
            schema_name = 'quantdb'

        console.print(f"[cyan]Found {len(table_names)} tables in schema '{schema_name}'[/cyan]\n")

        # Start building the models file content
        file_content = []

        # Header
        file_content.append('"""')
        file_content.append(f'Auto-generated SQLAlchemy models from database schema')
        file_content.append(f'Generated: {datetime.now().isoformat()}')
        file_content.append(f'Database: {dbkwargs.get("database", "unknown")}')
        file_content.append(f'Host: {dbkwargs.get("host", "unknown")}')
        file_content.append('"""')
        file_content.append('')

        # Imports
        file_content.append('import uuid')
        file_content.append('from typing import List, Optional')
        file_content.append('')
        file_content.append('from sqlalchemy import (')
        file_content.append('    CheckConstraint,')
        file_content.append('    Column,')
        file_content.append('    DateTime,')
        file_content.append('    Enum,')
        file_content.append('    ForeignKey,')
        file_content.append('    ForeignKeyConstraint,')
        file_content.append('    Identity,')
        file_content.append('    Index,')
        file_content.append('    Integer,')
        file_content.append('    Numeric,')
        file_content.append('    PrimaryKeyConstraint,')
        file_content.append('    String,')
        file_content.append('    Table,')
        file_content.append('    Text,')
        file_content.append('    UniqueConstraint,')
        file_content.append('    Uuid,')
        file_content.append('    event,')
        file_content.append('    text,')
        file_content.append(')')
        file_content.append('from sqlalchemy.dialects.postgresql import JSONB')
        file_content.append('from sqlalchemy.orm import (')
        file_content.append('    Mapped,')
        file_content.append('    declarative_base,')
        file_content.append('    foreign,')
        file_content.append('    mapped_column,')
        file_content.append('    relationship,')
        file_content.append('    validates,')
        file_content.append(')')
        file_content.append('')
        file_content.append('Base = declarative_base()')
        file_content.append('metadata = Base.metadata')
        file_content.append('')
        file_content.append('')

        # Process tables with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn('[progress.description]{task.description}'),
            console=console,
        ) as progress:
            task = progress.add_task(f'Processing {len(table_names)} tables...', total=len(table_names))

            # Group tables by type
            regular_tables = []
            association_tables = []

            for table_name in sorted(table_names):
                progress.update(task, description=f'Processing table: {table_name}')

                # Reflect the table
                table_obj = Table(table_name, MetaData(), autoload_with=engine)

                # Check if it's an association table (typically has only FKs and no other columns)
                columns = inspector.get_columns(table_name, schema=schema_name)
                foreign_keys = inspector.get_foreign_keys(table_name, schema=schema_name)

                # Simple heuristic: if all non-PK columns are FKs, it's likely an association table
                fk_columns = set()
                for fk in foreign_keys:
                    fk_columns.update(fk['constrained_columns'])

                non_fk_columns = [col['name'] for col in columns if col['name'] not in fk_columns]

                # Special case: obj_desc_* tables should be regular ORM classes even if they have many FKs
                if table_name.startswith('obj_desc_'):
                    regular_tables.append(table_name)
                elif len(non_fk_columns) <= 1 and len(foreign_keys) >= 2:
                    # Likely an association table
                    association_tables.append(table_name)
                else:
                    regular_tables.append(table_name)

                progress.advance(task)

            progress.update(task, description='Generating model classes...')

            # Generate regular model classes
            console.print('\n[cyan]Generating model classes...[/cyan]')
            all_tables_set = set(table_names)  # Create a set of all table names for relationship checking
            for table_name in regular_tables:
                try:
                    model_code = generate_model_class(table_name, None, inspector, all_tables_set, schema=schema_name)
                    file_content.append(model_code)
                    file_content.append('')
                    file_content.append('')
                except Exception as e:
                    console.print(f'[yellow]Warning: Could not generate model for {table_name}: {e}[/yellow]')

            # Generate association tables as Table objects
            console.print('[cyan]Generating association tables...[/cyan]')
            for table_name in association_tables:
                file_content.append(f'# Association table: {table_name}')
                file_content.append(f't_{table_name} = Table(')
                file_content.append(f"    '{table_name}',")
                file_content.append('    metadata,')

                # Add columns
                columns = inspector.get_columns(table_name, schema=schema_name)
                for col in columns:
                    col_type = get_python_type(col['type'])
                    nullable = ', nullable=False' if not col.get('nullable', True) else ''
                    file_content.append(f"    Column('{col['name']}', {col_type}{nullable}),")

                # Add constraints
                pk_constraint = inspector.get_pk_constraint(table_name, schema=schema_name)
                if pk_constraint and pk_constraint['constrained_columns']:
                    pk_cols = ', '.join(f"'{col}'" for col in pk_constraint['constrained_columns'])
                    file_content.append(f"    PrimaryKeyConstraint({pk_cols}, name='{pk_constraint['name']}'),")

                foreign_keys = inspector.get_foreign_keys(table_name, schema=schema_name)
                for fk in foreign_keys:
                    if fk['constrained_columns']:
                        const_cols = [f"'{col}'" for col in fk['constrained_columns']]
                        ref_cols = [f"'{fk['referred_table']}.{col}'" for col in fk['referred_columns']]
                        file_content.append(
                            f"    ForeignKeyConstraint([{', '.join(const_cols)}], [{', '.join(ref_cols)}], name='{fk['name']}'),"
                        )

                # Add schema if not public
                if schema_name and schema_name != 'public':
                    file_content.append(f"    schema='{schema_name}'")
                file_content.append(')')
                file_content.append('')
                file_content.append('')

            progress.update(task, completed=len(table_names))

        # Add helper functions at the end
        console.print('[cyan]Adding helper functions...[/cyan]')
        file_content.append('')
        file_content.append('')
        file_content.append('# Helper functions for automatic foreign key updates')
        file_content.append('')
        file_content.append('def update_all_children(target, value, oldvalue, initiator):')
        file_content.append('    # Loop through all relationships of the target (parent) object')
        file_content.append('    for relationship_prop in target.__mapper__.relationships:')
        file_content.append('        related_objects = getattr(target, relationship_prop.key)')
        file_content.append('')
        file_content.append('        # If there are related objects, update their attributes')
        file_content.append('        if related_objects is not None:')
        file_content.append('            # Handle single and multiple relationships')
        file_content.append(
            '            related_objects = related_objects if isinstance(related_objects, list) else [related_objects]'
        )
        file_content.append('            for related_obj in related_objects:')
        file_content.append('                # Update attributes on related objects as needed')
        file_content.append("                # For demonstration, we'll update an attribute based on parent_value")
        file_content.append("                if hasattr(related_obj, 'child_value'):")
        file_content.append("                    related_obj.child_value = f'Updated from parent_value: {value}'")
        file_content.append("                if hasattr(related_obj, 'other_child_value'):")
        file_content.append("                    related_obj.other_child_value = f'Updated from parent_value: {value}'")
        file_content.append('')
        file_content.append('')
        file_content.append('# Helper function to find the foreign key field associated with a relationship')
        file_content.append('def get_foreign_key_field(model, relationship_key):')
        file_content.append('    """Get the local foreign key field name for a given relationship key in the model."""')
        file_content.append('    for constraint in model.__table__.constraints:')
        file_content.append('        if isinstance(constraint, ForeignKeyConstraint):')
        file_content.append('            for element in constraint.elements:')
        file_content.append('                # Match the local column to the relationship key')
        file_content.append('                if element.column.table.name == relationship_key:')
        file_content.append('                    return element.parent.name')
        file_content.append('    return None')
        file_content.append('')
        file_content.append('')
        file_content.append('# General listener function for updating foreign keys dynamically')
        file_content.append('def update_foreign_key(target, value, oldvalue, initiator):')
        file_content.append('    if value is not None:')
        file_content.append('        # Use the initiator key to find the appropriate foreign key field')
        file_content.append(
            '        relationship_key = initiator.key  # Use initiator.key to get the relationship name'
        )
        file_content.append('        foreign_key_field = get_foreign_key_field(target.__class__, relationship_key)')
        file_content.append('')
        file_content.append('        # Set the foreign key field if it exists on the target')
        file_content.append('        if foreign_key_field and hasattr(target, foreign_key_field):')
        file_content.append(
            "            # Handle models with composite primary keys that don't have a single 'id' field"
        )
        file_content.append("            if hasattr(value, 'id'):")
        file_content.append('                setattr(target, foreign_key_field, value.id)')
        file_content.append('            else:')
        file_content.append('                # Skip setting foreign key for models with composite primary keys')
        file_content.append('                # These relationships will be handled through other means')
        file_content.append('                pass')
        file_content.append('')
        file_content.append('')
        file_content.append('# Function to attach the listener to all relationships in a given model')
        file_content.append('def add_dynamic_listeners(base):')
        file_content.append('    for cls in base.__subclasses__():')
        file_content.append('        for relationship_prop in cls.__mapper__.relationships:')
        file_content.append("            event.listen(getattr(cls, relationship_prop.key), 'set', update_foreign_key)")
        file_content.append('')
        file_content.append('')
        file_content.append('# Attach listeners to all models in the Base')
        file_content.append('add_dynamic_listeners(Base)')
        file_content.append('')

        # Write the file
        console.print(f'\n[cyan]Writing models to {output_path}...[/cyan]')
        output_path.write_text('\n'.join(file_content))

        # Show summary
        summary_table = RichTable(title='Extraction Summary', show_header=True)
        summary_table.add_column('Category', style='cyan')
        summary_table.add_column('Count', style='magenta')
        summary_table.add_row('Regular Tables', str(len(regular_tables)))
        summary_table.add_row('Association Tables', str(len(association_tables)))
        summary_table.add_row('Total Tables', str(len(table_names)))
        console.print(summary_table)

        # Show sample of the generated file
        console.print('\n[cyan]Sample of generated file:[/cyan]')
        sample_lines = file_content[:50]  # First 50 lines
        sample_code = '\n'.join(sample_lines)
        syntax = Syntax(sample_code, 'python', theme='monokai', line_numbers=True)
        console.print(syntax)

        console.print(
            Panel.fit(
                f'[bold green]✅ Schema extraction complete![/bold green]\n'
                f'[yellow]Output saved to: {output_path}[/yellow]',
                border_style='green',
            )
        )

        # Also display some statistics about the database
        console.print('\n[cyan]Database Statistics:[/cyan]')
        with engine.connect() as conn:
            # Count rows in each table (be careful with large tables)
            stats_table = RichTable(title='Table Row Counts', show_header=True)
            stats_table.add_column('Table', style='cyan')
            stats_table.add_column('Row Count', style='magenta', justify='right')

            for table_name in sorted(table_names)[:20]:  # Limit to first 20 tables
                try:
                    result = conn.execute(text(f'SELECT COUNT(*) FROM {table_name}'))
                    count = result.scalar()
                    stats_table.add_row(table_name, str(count))
                except Exception as e:
                    stats_table.add_row(table_name, 'Error')

            if len(table_names) > 20:
                stats_table.add_row('...', '...')
                stats_table.add_row(f'({len(table_names) - 20} more tables)', '')

            console.print(stats_table)

        return output_path

    except Exception as e:
        console.print(f'[bold red]Error: {e}[/bold red]')
        raise
    finally:
        if 'engine' in locals():
            engine.dispose()
            console.print('\n[dim]Database connection closed[/dim]')


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Extract database schema and generate SQLAlchemy models (READ-ONLY)')
    parser.add_argument('--test', action='store_true', help='Use test database instead of production')
    args = parser.parse_args()

    try:
        output_file = extract_schema(use_test_db=args.test)
        console.print(f'\n[bold green]Success! Models file created: {output_file}[/bold green]')
        console.print('\n[yellow]To compare with existing models:[/yellow]')
        console.print(f'[dim]diff quantdb/models.py {output_file}[/dim]')
        return 0
    except Exception as e:
        console.print(f'\n[bold red]Failed to extract schema: {e}[/bold red]')
        return 1


if __name__ == '__main__':
    sys.exit(main())
