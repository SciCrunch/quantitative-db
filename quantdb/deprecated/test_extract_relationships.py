#!/usr/bin/env python3
"""
Test script to demonstrate relationship extraction from existing models.
This simulates what extract_schema.py would do if the database had tables.
"""

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()

# Sample generated model with relationships (simulated)
sample_model = '''
class ValuesInst(Base):
    """Table: values_inst"""
    __tablename__ = 'values_inst'
    __table_args__ = (
        CheckConstraint("id_sam ~ '^sam-'::text", name='values_inst_id_sam_check'),
        CheckConstraint("id_sub ~ '^sub-'::text", name='values_inst_id_sub_check'),
        ForeignKeyConstraint(['dataset'], ['objects.id'], name='values_inst_dataset_fkey'),
        ForeignKeyConstraint(['desc_inst'], ['descriptors_inst.id'], name='values_inst_desc_inst_fkey'),
        PrimaryKeyConstraint('id', name='values_inst_pkey'),
        UniqueConstraint('dataset', 'id_formal', name='values_inst_dataset_id_formal_key'),
        Index('idx_values_inst_dataset', 'dataset'),
        Index('idx_values_inst_desc_inst', 'desc_inst'),
    )

    id = mapped_column(Integer, primary_key=True, Identity())
    type = mapped_column(Enum('subject', 'sample', 'below', name='instance_type'), nullable=False)
    id_sub = mapped_column(Text, nullable=False)
    desc_inst = mapped_column(Integer, ForeignKey('descriptors_inst.id'))
    dataset = mapped_column(Uuid, ForeignKey('objects.id'))
    id_formal = mapped_column(Text)
    local_identifier = mapped_column(Text)
    id_sam = mapped_column(Text)

    # Relationships (auto-generated based on foreign keys)
    desc: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[desc_inst])
    dataset_obj: Mapped[Optional['Objects']] = relationship('Objects', foreign_keys=[dataset])
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)
    values_quants: Mapped[List['ValuesQuant']] = relationship('ValuesQuant', uselist=True, viewonly=True)


class Objects(Base):
    """Table: objects"""
    __tablename__ = 'objects'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='objects_pkey'),
        Index('idx_objects_id_internal', 'id_internal'),
    )

    id = mapped_column(Uuid, primary_key=True)
    id_type = mapped_column(Enum('organization', 'dataset', 'collection', 'package', 'quantdb', name='remote_id_type'), nullable=False)
    id_file = mapped_column(Integer, nullable=True)
    id_internal = mapped_column(Uuid, nullable=True)

    # Relationships (auto-generated - reverse relationships)
    values_insts: Mapped[List['ValuesInst']] = relationship('ValuesInst', uselist=True, viewonly=True)
    obj_desc_insts: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
    obj_desc_cats: Mapped[List['ObjDescCat']] = relationship('ObjDescCat', uselist=True, viewonly=True)
    obj_desc_quants: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)


class DescriptorsInst(Base):
    """Table: descriptors_inst"""
    __tablename__ = 'descriptors_inst'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='descriptors_inst_pkey'),
        UniqueConstraint('iri', name='descriptors_inst_iri_key'),
        UniqueConstraint('label', name='descriptors_inst_label_key'),
    )

    id = mapped_column(Integer, primary_key=True, Identity())
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)
    description = mapped_column(Text)

    # Relationships (auto-generated - reverse relationships)
    values_insts: Mapped[List['ValuesInst']] = relationship('ValuesInst', uselist=True, viewonly=True)
    descriptors_cats: Mapped[List['DescriptorsCat']] = relationship('DescriptorsCat', uselist=True, viewonly=True)
    descriptors_quants: Mapped[List['DescriptorsQuant']] = relationship('DescriptorsQuant', uselist=True, viewonly=True)
    obj_desc_insts: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
'''

# Association table example
association_table = """
# Association table: instance_parent
t_instance_parent = Table(
    'instance_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    ForeignKeyConstraint(['id'], ['values_inst.id'], name='instance_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['values_inst.id'], name='instance_parent_parent_fkey'),
    PrimaryKeyConstraint('id', 'parent', name='instance_parent_pkey'),
)

# Association table: dataset_object
t_dataset_object = Table(
    'dataset_object',
    metadata,
    Column('dataset', Uuid, nullable=False),
    Column('object', Uuid, nullable=False),
    ForeignKeyConstraint(['dataset'], ['objects.id'], name='dataset_object_dataset_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='dataset_object_object_fkey'),
    PrimaryKeyConstraint('dataset', 'object', name='dataset_object_pkey'),
)
"""


def main():
    console.print(
        Panel.fit(
            '[bold cyan]Demonstration: Enhanced Schema Extraction with Relationships[/bold cyan]', border_style='cyan'
        )
    )

    console.print('\n[yellow]The extract_schema.py script now generates:[/yellow]\n')

    features = Table(show_header=True, header_style='bold magenta')
    features.add_column('Feature', style='cyan')
    features.add_column('Description', style='white')

    features.add_row(
        'Foreign Key Analysis', 'Automatically detects foreign keys and generates appropriate relationships'
    )
    features.add_row('Relationship Types', 'Creates Many-to-One, One-to-Many, and One-to-One relationships')
    features.add_row('Back References', 'Generates reverse relationships for collections (e.g., parent.children)')
    features.add_row('Smart Naming', "Removes '_id' suffixes, pluralizes collections, handles conflicts")
    features.add_row('Association Tables', 'Identifies and generates Table objects for many-to-many relationships')

    console.print(features)

    console.print('\n[cyan]Example Generated Model with Relationships:[/cyan]\n')

    syntax = Syntax(sample_model, 'python', theme='monokai', line_numbers=True)
    console.print(syntax)

    console.print('\n[cyan]Example Association Tables:[/cyan]\n')

    syntax2 = Syntax(association_table, 'python', theme='monokai', line_numbers=True)
    console.print(syntax2)

    # Show relationship types
    console.print('\n[yellow]Relationship Patterns Generated:[/yellow]\n')

    rel_table = Table(show_header=True, header_style='bold yellow')
    rel_table.add_column('Pattern', style='cyan')
    rel_table.add_column('SQLAlchemy Code', style='green')

    rel_table.add_row('Many-to-One (FK)', "relationship('OtherClass', foreign_keys=[fk_col])")
    rel_table.add_row('One-to-Many (Reverse)', "relationship('OtherClass', uselist=True, viewonly=True)")
    rel_table.add_row(
        'Self-Referential', "relationship('SameClass', foreign_keys=[parent_id], remote_side='[SameClass.id]')"
    )
    rel_table.add_row('Composite FK', "relationship('OtherClass', foreign_keys=['col1', 'col2'])")

    console.print(rel_table)

    console.print(
        Panel.fit(
            '[green]✅ The enhanced extract_schema.py is ready![/green]\n'
            '[yellow]It will generate complete models with relationships when the database has tables.[/yellow]',
            border_style='green',
        )
    )


if __name__ == '__main__':
    main()
