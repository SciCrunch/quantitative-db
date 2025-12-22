"""
Auto-generated SQLAlchemy models from database schema
Generated: 2025-08-26T15:04:32.086800
Database: quantdb_test_2025_07_28
Host: sparc-nlp.cpmk2alqjf9s.us-west-2.rds.amazonaws.com
"""

import uuid
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    declarative_base,
    foreign,
    mapped_column,
    relationship,
    validates,
)

Base = declarative_base()
metadata = Base.metadata


class Addresses(Base):
    """Addresses of data

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
    """

    __tablename__ = 'addresses'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='addresses_pkey'),
        UniqueConstraint('addr_type', 'addr_field', 'value_type', name='addresses_addr_type_addr_field_value_type_key'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    addr_type = mapped_column(
        Enum(
            'constant',
            'record-index',
            'tabular-header',
            'tabular-alt-header',
            'workbook-sheet-tabular-header',
            'workbook-sheet-tabular-alt-header',
            'json-path-with-types',
            'file-system-extracted',
            'arbitrary-function',
            name='address_type',
        ),
        nullable=False,
    )
    value_type = mapped_column(
        Enum('single', 'multi', name='field_value_type'),
        nullable=False,
        server_default=text("'single'::field_value_type"),
    )
    addr_field = mapped_column(Text)
    curator_note = mapped_column(Text)

    # Relationships
    obj_desc_insts: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
    obj_desc_insts_1: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
    obj_desc_cats: Mapped[List['ObjDescCat']] = relationship('ObjDescCat', uselist=True, viewonly=True)
    obj_desc_cats_1: Mapped[List['ObjDescCat']] = relationship('ObjDescCat', uselist=True, viewonly=True)
    obj_desc_quants: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)
    obj_desc_quants_1: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)
    obj_desc_quants_2: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)
    obj_desc_quants_3: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)


class Aspects(Base):
    """Aspects of data

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
    """

    __tablename__ = 'aspects'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='aspects_pkey'),
        UniqueConstraint('iri', name='aspects_iri_key'),
        UniqueConstraint('label', name='aspects_label_key'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    label = mapped_column(Text, nullable=False)
    description = mapped_column(Text)
    iri = mapped_column(Text, nullable=False)

    # Relationships
    aspect_parents: Mapped[List['AspectParent']] = relationship('AspectParent', uselist=True, viewonly=True)
    aspect_parents_1: Mapped[List['AspectParent']] = relationship('AspectParent', uselist=True, viewonly=True)
    descriptors_quants: Mapped[List['DescriptorsQuant']] = relationship('DescriptorsQuant', uselist=True, viewonly=True)


class ControlledTerms(Base):
    """Controlled terms

    Parameters
    ----------
    id : int
        Unique identifier for the controlled term.
    label : str
        Label of the controlled term.
    iri : str
        IRI of the controlled term.
    """

    __tablename__ = 'controlled_terms'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='controlled_terms_pkey'),
        UniqueConstraint('iri', name='controlled_terms_iri_key'),
        UniqueConstraint('label', name='controlled_terms_label_key'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)

    # Relationships
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)


class DescriptorsCat(Base):
    """Table: descriptors_cat"""

    __tablename__ = 'descriptors_cat'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='descriptors_cat_pkey'),
        UniqueConstraint('domain', 'range', 'label', name='descriptors_cat_domain_range_label_key'),
        ForeignKeyConstraint(['domain'], ['descriptors_inst.id'], name='descriptors_cat_domain_fkey'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    domain = mapped_column(Integer, ForeignKey('descriptors_inst.id'))
    range = mapped_column(Enum('open', 'controlled', name='cat_range_type'))
    label = mapped_column(Text)
    description = mapped_column(Text)
    curator_note = mapped_column(Text)

    # Relationships
    domain_inst: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[domain])
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)
    obj_desc_cats: Mapped[List['ObjDescCat']] = relationship('ObjDescCat', uselist=True, viewonly=True)


class DescriptorsInst(Base):
    """Descriptors Instance

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

    """

    __tablename__ = 'descriptors_inst'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='descriptors_inst_pkey'),
        UniqueConstraint('iri', name='descriptors_inst_iri_key'),
        UniqueConstraint('label', name='descriptors_inst_label_key'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    label = mapped_column(Text, nullable=False)
    description = mapped_column(Text)
    iri = mapped_column(Text, nullable=False)

    # Relationships
    values_quants: Mapped[List['ValuesQuant']] = relationship('ValuesQuant', uselist=True, viewonly=True)
    class_parents: Mapped[List['ClassParent']] = relationship('ClassParent', uselist=True, viewonly=True)
    class_parents_1: Mapped[List['ClassParent']] = relationship('ClassParent', uselist=True, viewonly=True)
    values_insts: Mapped[List['ValuesInst']] = relationship('ValuesInst', uselist=True, viewonly=True)
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)
    obj_desc_insts: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
    descriptors_quants: Mapped[List['DescriptorsQuant']] = relationship('DescriptorsQuant', uselist=True, viewonly=True)
    descriptors_cats: Mapped[List['DescriptorsCat']] = relationship('DescriptorsCat', uselist=True, viewonly=True)


class DescriptorsQuant(Base):
    """
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
    """

    __tablename__ = 'descriptors_quant'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='descriptors_quant_pkey'),
        UniqueConstraint('label', name='descriptors_quant_label_key'),
        UniqueConstraint(
            'unit',
            'aspect',
            'domain',
            'shape',
            'aggregation_type',
            name='descriptors_quant_unit_aspect_domain_shape_aggregation_type_key',
        ),
        ForeignKeyConstraint(['aspect'], ['aspects.id'], name='descriptors_quant_aspect_fkey'),
        ForeignKeyConstraint(['domain'], ['descriptors_inst.id'], name='descriptors_quant_domain_fkey'),
        ForeignKeyConstraint(['unit'], ['units.id'], name='descriptors_quant_unit_fkey'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    shape = mapped_column(
        Enum('scalar', name='quant_shape'), nullable=False, server_default=text("'scalar'::quant_shape")
    )
    unit = mapped_column(Integer, ForeignKey('units.id'))
    aspect = mapped_column(Integer, ForeignKey('aspects.id'))
    domain = mapped_column(Integer, ForeignKey('descriptors_inst.id'))
    label = mapped_column(Text, nullable=False)
    description = mapped_column(Text)
    aggregation_type = mapped_column(
        Enum('instance', 'function', 'summary', 'mean', 'media', 'mode', 'sum', 'min', 'max', name='quant_agg_type'),
        nullable=False,
        server_default=text("'instance'::quant_agg_type"),
    )
    curator_note = mapped_column(Text)

    # Relationships
    aspects: Mapped[Optional['Aspects']] = relationship('Aspects', foreign_keys=[aspect])
    domain_inst: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[domain])
    units: Mapped[Optional['Units']] = relationship('Units', foreign_keys=[unit])
    values_quants: Mapped[List['ValuesQuant']] = relationship('ValuesQuant', uselist=True, viewonly=True)
    obj_desc_quants: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)


class Objects(Base):
    """
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
    """

    __tablename__ = 'objects'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='objects_pkey'),
        ForeignKeyConstraint(['id_internal'], ['objects_internal.id'], name='objects_id_internal_fkey'),
        CheckConstraint(
            "id_type <> 'quantdb'::remote_id_type OR id_internal IS NOT NULL AND id = id_internal",
            name='constraint_objects_remote_id_type_id_internal',
        ),
        CheckConstraint(
            "id_type <> 'package'::remote_id_type OR id_file IS NOT NULL",
            name='constraint_objects_remote_id_type_id_package',
        ),
        Index('idx_objects_id_internal', 'id_internal'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Uuid, nullable=False)
    id_type = mapped_column(
        Enum('organization', 'dataset', 'collection', 'package', 'quantdb', name='remote_id_type'), nullable=False
    )
    id_file = mapped_column(Integer)
    id_internal = mapped_column(Uuid, ForeignKey('objects_internal.id'))

    # Relationships
    id_internal: Mapped[Optional['ObjectsInternal']] = relationship('ObjectsInternal', foreign_keys=[id_internal])
    values_quants: Mapped[List['ValuesQuant']] = relationship('ValuesQuant', uselist=True, viewonly=True)
    values_insts: Mapped[List['ValuesInst']] = relationship('ValuesInst', uselist=True, viewonly=True)
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)
    objects_internals: Mapped[List['ObjectsInternal']] = relationship('ObjectsInternal', uselist=True, viewonly=True)
    obj_desc_insts: Mapped[List['ObjDescInst']] = relationship('ObjDescInst', uselist=True, viewonly=True)
    obj_desc_cats: Mapped[List['ObjDescCat']] = relationship('ObjDescCat', uselist=True, viewonly=True)
    obj_desc_quants: Mapped[List['ObjDescQuant']] = relationship('ObjDescQuant', uselist=True, viewonly=True)
    dataset_objects: Mapped[List['DatasetObject']] = relationship('DatasetObject', uselist=True, viewonly=True)
    dataset_objects_1: Mapped[List['DatasetObject']] = relationship('DatasetObject', uselist=True, viewonly=True)

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
        return self.preprocess_id(id_value)


class ObjectsInternal(Base):
    """Table: objects_internal"""

    __tablename__ = 'objects_internal'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='objects_internal_pkey'),
        UniqueConstraint('dataset', 'updated_transitive', name='objects_internal_dataset_updated_transitive_key'),
        ForeignKeyConstraint(['dataset'], ['objects.id'], name='constraint_oi_dataset_fk'),
        CheckConstraint(
            "type <> 'path-metadata'::oi_type OR updated_transitive IS NOT NULL AND dataset IS NOT NULL",
            name='constraint_objects_internal_type_updated_transitive',
        ),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Uuid, nullable=False, server_default=text('gen_random_uuid()'))
    type = mapped_column(Enum('path-metadata', 'other', name='oi_type'), server_default=text("'other'::oi_type"))
    dataset = mapped_column(Uuid, ForeignKey('objects.id'))
    updated_transitive = mapped_column(DateTime)
    label = mapped_column(Text)
    curator_note = mapped_column(Text)

    # Relationships
    dataset: Mapped[Optional['Objects']] = relationship('Objects', foreign_keys=[dataset])
    objects: Mapped[List['Objects']] = relationship('Objects', uselist=True, viewonly=True)


class Units(Base):
    """Table: units"""

    __tablename__ = 'units'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='units_pkey'),
        UniqueConstraint('iri', name='units_iri_key'),
        UniqueConstraint('label', name='units_label_key'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)

    # Relationships
    descriptors_quants: Mapped[List['DescriptorsQuant']] = relationship('DescriptorsQuant', uselist=True, viewonly=True)


class ValuesCat(Base):
    """Table: values_cat"""

    __tablename__ = 'values_cat'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='values_cat_pkey'),
        UniqueConstraint('object', 'instance', 'desc_cat', name='values_cat_object_instance_desc_cat_key'),
        ForeignKeyConstraint(['desc_cat'], ['descriptors_cat.id'], name='values_cat_desc_cat_fkey'),
        ForeignKeyConstraint(['desc_inst'], ['descriptors_inst.id'], name='values_cat_desc_inst_fkey'),
        ForeignKeyConstraint(['instance'], ['values_inst.id'], name='values_cat_instance_fkey'),
        ForeignKeyConstraint(
            ['object', 'desc_cat'],
            ['obj_desc_cat.object', 'obj_desc_cat.desc_cat'],
            name='values_cat_object_desc_cat_fkey',
        ),
        ForeignKeyConstraint(
            ['object', 'desc_inst'],
            ['obj_desc_inst.object', 'obj_desc_inst.desc_inst'],
            name='values_cat_object_desc_inst_fkey',
        ),
        ForeignKeyConstraint(['object'], ['objects.id'], name='values_cat_object_fkey'),
        ForeignKeyConstraint(['value_controlled'], ['controlled_terms.id'], name='values_cat_value_controlled_fkey'),
        CheckConstraint(
            'value_open IS NOT NULL OR value_controlled IS NOT NULL', name='constraint_values_cat_some_value'
        ),
        Index('idx_values_cat_desc_cat', 'desc_cat'),
        Index('idx_values_cat_desc_inst', 'desc_inst'),
        Index('idx_values_cat_instance', 'instance'),
        Index('idx_values_cat_object', 'object'),
        Index('idx_values_cat_object_instance', 'object', 'instance'),
        Index('idx_values_cat_value_controlled', 'value_controlled'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    value_open = mapped_column(Text)
    value_controlled = mapped_column(Integer, ForeignKey('controlled_terms.id'))
    object = mapped_column(Uuid, ForeignKey('obj_desc_cat.object'), nullable=False)
    desc_inst = mapped_column(Integer, ForeignKey('descriptors_inst.id'), nullable=False)
    desc_cat = mapped_column(Integer, ForeignKey('descriptors_cat.id'), nullable=False)
    instance = mapped_column(Integer, ForeignKey('values_inst.id'))

    # Relationships
    descriptors_cat: Mapped[Optional['DescriptorsCat']] = relationship('DescriptorsCat', foreign_keys=[desc_cat])
    descriptors_inst: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[desc_inst])
    values_inst: Mapped[Optional['ValuesInst']] = relationship('ValuesInst', foreign_keys=[instance])
    objdesccat: Mapped[Optional['ObjDescCat']] = relationship('ObjDescCat', foreign_keys=['object', 'desc_cat'])
    objdescinst: Mapped[Optional['ObjDescInst']] = relationship('ObjDescInst', foreign_keys=['object', 'desc_inst'])
    objects: Mapped[Optional['Objects']] = relationship('Objects', foreign_keys=[object])
    controlled_terms: Mapped[Optional['ControlledTerms']] = relationship(
        'ControlledTerms', foreign_keys=[value_controlled]
    )


class ValuesInst(Base):
    """
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
    """

    __tablename__ = 'values_inst'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='values_inst_pkey'),
        UniqueConstraint('dataset', 'id_formal', name='values_inst_dataset_id_formal_key'),
        ForeignKeyConstraint(['dataset'], ['objects.id'], name='values_inst_dataset_fkey'),
        ForeignKeyConstraint(['desc_inst'], ['descriptors_inst.id'], name='values_inst_desc_inst_fkey'),
        CheckConstraint(
            "type <> 'below'::instance_type OR id_sub IS NOT NULL OR id_sam IS NOT NULL",
            name='constraint_values_inst_type_below',
        ),
        CheckConstraint(
            "type = 'below'::instance_type AND NOT id_formal ~ '^(sub|sam|site)-'::text OR type = 'subject'::instance_type AND id_formal ~ '^sub-'::text OR type = 'sample'::instance_type AND id_formal ~ '^sam-'::text OR type = 'site'::instance_type AND id_formal ~ '^site-'::text",
            name='constraint_values_inst_type_id_formal',
        ),
        CheckConstraint(
            "type <> 'sample'::instance_type OR id_sam IS NOT NULL AND id_sam = id_formal",
            name='constraint_values_inst_type_id_sam',
        ),
        CheckConstraint(
            "type <> 'subject'::instance_type OR id_sub = id_formal AND id_sam IS NULL",
            name='constraint_values_inst_type_id_sub',
        ),
        CheckConstraint("id_sam ~ '^sam-'::text", name='values_inst_id_sam_check'),
        CheckConstraint("id_sub ~ '^sub-'::text", name='values_inst_id_sub_check'),
        Index('idx_values_inst_dataset', 'dataset'),
        Index('idx_values_inst_dataset_id_formal', 'dataset', 'id_formal'),
        Index('idx_values_inst_dataset_id_sam', 'dataset', 'id_sam'),
        Index('idx_values_inst_dataset_id_sub', 'dataset', 'id_sub'),
        Index('idx_values_inst_desc_inst', 'desc_inst'),
        Index('idx_values_inst_id_formal', 'id_formal'),
        Index('idx_values_inst_id_sam', 'id_sam'),
        Index('idx_values_inst_id_sub', 'id_sub'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    type = mapped_column(Enum('subject', 'sample', 'site', 'below', name='instance_type'), nullable=False)
    desc_inst = mapped_column(Integer, ForeignKey('descriptors_inst.id'), nullable=False)
    dataset = mapped_column(Uuid, ForeignKey('objects.id'), nullable=False)
    id_formal = mapped_column(Text)
    local_identifier = mapped_column(Text)
    id_sub = mapped_column(Text, nullable=False)
    id_sam = mapped_column(Text)

    # Relationships
    dataset: Mapped[Optional['Objects']] = relationship('Objects', foreign_keys=[dataset])
    desc_inst: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[desc_inst])
    values_quants: Mapped[List['ValuesQuant']] = relationship('ValuesQuant', uselist=True, viewonly=True)
    instance_parents: Mapped[List['InstanceParent']] = relationship('InstanceParent', uselist=True, viewonly=True)
    instance_parents_1: Mapped[List['InstanceParent']] = relationship('InstanceParent', uselist=True, viewonly=True)
    values_cats: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, viewonly=True)
    equiv_insts: Mapped[List['EquivInst']] = relationship('EquivInst', uselist=True, viewonly=True)
    equiv_insts_1: Mapped[List['EquivInst']] = relationship('EquivInst', uselist=True, viewonly=True)


class ValuesQuant(Base):
    """Table: values_quant"""

    __tablename__ = 'values_quant'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='values_quant_pkey'),
        UniqueConstraint('object', 'instance', 'desc_quant', name='values_quant_object_instance_desc_quant_key'),
        ForeignKeyConstraint(['desc_inst'], ['descriptors_inst.id'], name='values_quant_desc_inst_fkey'),
        ForeignKeyConstraint(['desc_quant'], ['descriptors_quant.id'], name='values_quant_desc_quant_fkey'),
        ForeignKeyConstraint(['instance'], ['values_inst.id'], name='values_quant_instance_fkey'),
        ForeignKeyConstraint(
            ['object', 'desc_inst'],
            ['obj_desc_inst.object', 'obj_desc_inst.desc_inst'],
            name='values_quant_object_desc_inst_fkey',
        ),
        ForeignKeyConstraint(
            ['object', 'desc_quant'],
            ['obj_desc_quant.object', 'obj_desc_quant.desc_quant'],
            name='values_quant_object_desc_quant_fkey',
        ),
        ForeignKeyConstraint(['object'], ['objects.id'], name='values_quant_object_fkey'),
        Index('idx_values_quant_desc_inst', 'desc_inst'),
        Index('idx_values_quant_desc_quant', 'desc_quant'),
        Index('idx_values_quant_instance', 'instance'),
        Index('idx_values_quant_object', 'object'),
        Index('idx_values_quant_object_instance', 'object', 'instance'),
        {'schema': 'quantdb'},
    )

    id = mapped_column(Integer, nullable=False)
    value = mapped_column(Numeric, nullable=False)
    object = mapped_column(Uuid, ForeignKey('obj_desc_inst.object'), nullable=False)
    desc_inst = mapped_column(Integer, ForeignKey('descriptors_inst.id'), nullable=False)
    desc_quant = mapped_column(Integer, ForeignKey('descriptors_quant.id'), nullable=False)
    instance = mapped_column(Integer, ForeignKey('values_inst.id'))
    orig_value = mapped_column(Text)
    orig_units = mapped_column(Text)
    value_blob = mapped_column(JSONB, nullable=False)

    # Relationships
    desc_inst: Mapped[Optional['DescriptorsInst']] = relationship('DescriptorsInst', foreign_keys=[desc_inst])
    desc_quant: Mapped[Optional['DescriptorsQuant']] = relationship('DescriptorsQuant', foreign_keys=[desc_quant])
    instance: Mapped[Optional['ValuesInst']] = relationship('ValuesInst', foreign_keys=[instance])
    objdescinst: Mapped[Optional['ObjDescInst']] = relationship('ObjDescInst', foreign_keys=['object', 'desc_inst'])
    objdescquant: Mapped[Optional['ObjDescQuant']] = relationship('ObjDescQuant', foreign_keys=['object', 'desc_quant'])
    objects: Mapped[Optional['Objects']] = relationship('Objects', foreign_keys=[object])

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
        event.listen(ValuesQuant.descriptors_inst, 'set', ValuesQuant.update_desc_inst)


# Association table: aspect_parent
t_aspect_parent = Table(
    'aspect_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    PrimaryKeyConstraint('id', 'parent', name='aspect_parent_pkey'),
    ForeignKeyConstraint(['id'], ['aspects.id'], name='aspect_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['aspects.id'], name='aspect_parent_parent_fkey'),
    schema='quantdb',
)


# Association table: class_parent
t_class_parent = Table(
    'class_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    PrimaryKeyConstraint('id', 'parent', name='class_parent_pkey'),
    ForeignKeyConstraint(['id'], ['descriptors_inst.id'], name='class_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['descriptors_inst.id'], name='class_parent_parent_fkey'),
    schema='quantdb',
)


# Association table: dataset_object
t_dataset_object = Table(
    'dataset_object',
    metadata,
    Column('dataset', Uuid, nullable=False),
    Column('object', Uuid, nullable=False),
    PrimaryKeyConstraint('dataset', 'object', name='dataset_object_pkey'),
    ForeignKeyConstraint(['dataset'], ['objects.id'], name='dataset_object_dataset_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='dataset_object_object_fkey'),
    schema='quantdb',
)


# Association table: equiv_inst
t_equiv_inst = Table(
    'equiv_inst',
    metadata,
    Column('left_thing', Integer, nullable=False),
    Column('right_thing', Integer, nullable=False),
    PrimaryKeyConstraint('left_thing', 'right_thing', name='equiv_inst_pkey'),
    ForeignKeyConstraint(['left_thing'], ['values_inst.id'], name='equiv_inst_left_thing_fkey'),
    ForeignKeyConstraint(['right_thing'], ['values_inst.id'], name='equiv_inst_right_thing_fkey'),
    schema='quantdb',
)


# Association table: instance_parent
t_instance_parent = Table(
    'instance_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    PrimaryKeyConstraint('id', 'parent', name='instance_parent_pkey'),
    ForeignKeyConstraint(['id'], ['values_inst.id'], name='instance_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['values_inst.id'], name='instance_parent_parent_fkey'),
    schema='quantdb',
)


# Association table: obj_desc_cat
t_obj_desc_cat = Table(
    'obj_desc_cat',
    metadata,
    Column('object', Uuid, nullable=False),
    Column('desc_cat', Integer, nullable=False),
    Column('addr_field', Integer, nullable=False),
    Column('addr_desc_inst', Integer),
    Column('expect', Integer),
    PrimaryKeyConstraint('object', 'desc_cat', name='obj_desc_cat_pkey'),
    ForeignKeyConstraint(['addr_desc_inst'], ['addresses.id'], name='obj_desc_cat_addr_desc_inst_fkey'),
    ForeignKeyConstraint(['addr_field'], ['addresses.id'], name='obj_desc_cat_addr_field_fkey'),
    ForeignKeyConstraint(['desc_cat'], ['descriptors_cat.id'], name='obj_desc_cat_desc_cat_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_cat_object_fkey'),
    schema='quantdb',
)


# Association table: obj_desc_inst
t_obj_desc_inst = Table(
    'obj_desc_inst',
    metadata,
    Column('object', Uuid, nullable=False),
    Column('desc_inst', Integer, nullable=False),
    Column('addr_field', Integer, nullable=False),
    Column('addr_desc_inst', Integer),
    Column('expect', Integer),
    PrimaryKeyConstraint('object', 'desc_inst', name='obj_desc_inst_pkey'),
    ForeignKeyConstraint(['addr_desc_inst'], ['addresses.id'], name='obj_desc_inst_addr_desc_inst_fkey'),
    ForeignKeyConstraint(['addr_field'], ['addresses.id'], name='obj_desc_inst_addr_field_fkey'),
    ForeignKeyConstraint(['desc_inst'], ['descriptors_inst.id'], name='obj_desc_inst_desc_inst_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_inst_object_fkey'),
    schema='quantdb',
)


# Association table: obj_desc_quant
t_obj_desc_quant = Table(
    'obj_desc_quant',
    metadata,
    Column('object', Uuid, nullable=False),
    Column('desc_quant', Integer, nullable=False),
    Column('addr_field', Integer, nullable=False),
    Column('addr_unit', Integer),
    Column('addr_aspect', Integer),
    Column('addr_desc_inst', Integer),
    Column('expect', Integer),
    PrimaryKeyConstraint('object', 'desc_quant', name='obj_desc_quant_pkey'),
    ForeignKeyConstraint(['addr_aspect'], ['addresses.id'], name='obj_desc_quant_addr_aspect_fkey'),
    ForeignKeyConstraint(['addr_desc_inst'], ['addresses.id'], name='obj_desc_quant_addr_desc_inst_fkey'),
    ForeignKeyConstraint(['addr_field'], ['addresses.id'], name='obj_desc_quant_addr_field_fkey'),
    ForeignKeyConstraint(['addr_unit'], ['addresses.id'], name='obj_desc_quant_addr_unit_fkey'),
    ForeignKeyConstraint(['desc_quant'], ['descriptors_quant.id'], name='obj_desc_quant_desc_quant_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_quant_object_fkey'),
    schema='quantdb',
)


# Helper functions for automatic foreign key updates


def update_all_children(target, value, oldvalue, initiator):
    # Loop through all relationships of the target (parent) object
    for relationship_prop in target.__mapper__.relationships:
        related_objects = getattr(target, relationship_prop.key)

        # If there are related objects, update their attributes
        if related_objects is not None:
            # Handle single and multiple relationships
            related_objects = related_objects if isinstance(related_objects, list) else [related_objects]
            for related_obj in related_objects:
                # Update attributes on related objects as needed
                # For demonstration, we'll update an attribute based on parent_value
                if hasattr(related_obj, 'child_value'):
                    related_obj.child_value = f'Updated from parent_value: {value}'
                if hasattr(related_obj, 'other_child_value'):
                    related_obj.other_child_value = f'Updated from parent_value: {value}'


# Helper function to find the foreign key field associated with a relationship
def get_foreign_key_field(model, relationship_key):
    """Get the local foreign key field name for a given relationship key in the model."""
    for constraint in model.__table__.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                # Match the local column to the relationship key
                if element.column.table.name == relationship_key:
                    return element.parent.name
    return None


# General listener function for updating foreign keys dynamically
def update_foreign_key(target, value, oldvalue, initiator):
    if value is not None:
        # Use the initiator key to find the appropriate foreign key field
        relationship_key = initiator.key  # Use initiator.key to get the relationship name
        foreign_key_field = get_foreign_key_field(target.__class__, relationship_key)

        # Set the foreign key field if it exists on the target
        if foreign_key_field and hasattr(target, foreign_key_field):
            # Handle models with composite primary keys that don't have a single 'id' field
            if hasattr(value, 'id'):
                setattr(target, foreign_key_field, value.id)
            else:
                # Skip setting foreign key for models with composite primary keys
                # These relationships will be handled through other means
                pass


# Function to attach the listener to all relationships in a given model
def add_dynamic_listeners(base):
    for cls in base.__subclasses__():
        for relationship_prop in cls.__mapper__.relationships:
            event.listen(getattr(cls, relationship_prop.key), 'set', update_foreign_key)


# Attach listeners to all models in the Base
add_dynamic_listeners(Base)
