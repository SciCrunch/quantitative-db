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
from sqlalchemy.orm.base import Mapped

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
        UniqueConstraint(
            'addr_type',
            'addr_field',
            'value_type',
            name='addresses_addr_type_addr_field_value_type_key',
        ),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    addr_type = mapped_column(
        Enum(
            'constant',
            'tabular-header',
            'tabular-alt-header',
            'workbook-sheet-tabular-header',
            'workbook-sheet-tabular-alt-header',
            'json-path-with-types',
            'file-system-extracted',
            'arbitrary-function',
            name='address_type',
        )
    )
    value_type = mapped_column(
        Enum('single', 'multi', name='field_value_type'),
        server_default=text("'single'::field_value_type"),
    )
    addr_field = mapped_column(Text)
    curator_note = mapped_column(Text)

    obj_desc_inst: Mapped[List['ObjDescInst']] = relationship(
        'ObjDescInst',
        uselist=True,
        foreign_keys='[ObjDescInst.addr_desc_inst]',
        back_populates='addresses',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_inst_: Mapped[List['ObjDescInst']] = relationship(
        'ObjDescInst',
        uselist=True,
        foreign_keys='[ObjDescInst.addr_field]',
        back_populates='addresses_field',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_cat: Mapped[List['ObjDescCat']] = relationship(
        'ObjDescCat',
        uselist=True,
        foreign_keys='[ObjDescCat.addr_desc_inst]',
        back_populates='addresses',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_cat_: Mapped[List['ObjDescCat']] = relationship(
        'ObjDescCat',
        uselist=True,
        foreign_keys='[ObjDescCat.addr_field]',
        back_populates='addresses_',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_quant: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        foreign_keys='[ObjDescQuant.addr_aspect]',
        back_populates='addresses_aspect',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_quant_: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        foreign_keys='[ObjDescQuant.addr_desc_inst]',
        back_populates='addresses',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_quant1: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        foreign_keys='[ObjDescQuant.addr_field]',
        back_populates='addresses_field',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_quant2: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        foreign_keys='[ObjDescQuant.addr_unit]',
        back_populates='addresses_unit',
        viewonly=True,
        cascade='all, delete-orphan',
    )


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
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)
    description = mapped_column(Text)

    # aspects: Mapped["Aspects"] = relationship(
    #     "Aspects",
    #     secondary="aspect_parent",
    #     primaryjoin=lambda: Aspects.id == t_aspect_parent.c.id,
    #     secondaryjoin=lambda: Aspects.id == t_aspect_parent.c.parent,
    #     back_populates="aspects_",
    # )
    # aspects_: Mapped["Aspects"] = relationship(
    #     "Aspects",
    #     secondary="aspect_parent",
    #     primaryjoin=lambda: Aspects.id == t_aspect_parent.c.parent,
    #     secondaryjoin=lambda: Aspects.id == t_aspect_parent.c.id,
    #     back_populates="aspects",
    # )
    descriptors_quant: Mapped[List['DescriptorsQuant']] = relationship(
        'DescriptorsQuant',
        uselist=True,
        back_populates='aspects',
        viewonly=True,
        cascade='all, delete-orphan',
        sync_backref=False,
    )


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
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)

    values_cat: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, back_populates='controlled_terms')


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
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)
    description = mapped_column(Text)

    # descriptors_inst: Mapped["DescriptorsInst"] = relationship(
    #     "DescriptorsInst",
    #     secondary="class_parent",
    #     primaryjoin=lambda: DescriptorsInst.id == t_class_parent.c.id,
    #     secondaryjoin=lambda: DescriptorsInst.id == t_class_parent.c.parent,
    #     back_populates="descriptors_inst_",
    # )
    # descriptors_inst_: Mapped["DescriptorsInst"] = relationship(
    #     "DescriptorsInst",
    #     secondary="class_parent",
    #     primaryjoin=lambda: DescriptorsInst.id == t_class_parent.c.parent,
    #     secondaryjoin=lambda: DescriptorsInst.id == t_class_parent.c.id,
    #     back_populates="descriptors_inst",
    # )
    descriptors_cat: Mapped[List['DescriptorsCat']] = relationship(
        'DescriptorsCat', uselist=True, back_populates='descriptors_inst'
    )
    descriptors_quant: Mapped[List['DescriptorsQuant']] = relationship(
        'DescriptorsQuant',
        uselist=True,
        back_populates='descriptors_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_inst: Mapped[List['ObjDescInst']] = relationship(
        'ObjDescInst',
        uselist=True,
        back_populates='descriptors_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_inst: Mapped[List['ValuesInst']] = relationship(
        'ValuesInst',
        uselist=True,
        back_populates='descriptors_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_cat: Mapped[List['ValuesCat']] = relationship(
        'ValuesCat',
        uselist=True,
        back_populates='descriptors_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant',
        uselist=True,
        back_populates='descriptors_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )


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
        # CheckConstraint(
        #     "id_type <> 'package'::remote_id_type OR id_file IS NOT NULL",
        #     name="constraint_objects_remote_id_type_id_package",
        # ),
        # CheckConstraint(
        #     "id_type <> 'quantdb'::remote_id_type OR id_internal IS NOT NULL AND id = id_internal",
        #     name="constraint_objects_remote_id_type_id_internal",
        # ),
        # ForeignKeyConstraint(
        #     ["id_internal"],
        #     ["objects_internal.id"],
        #     name="objects_id_internal_fkey",
        # ),
        PrimaryKeyConstraint('id', name='objects_pkey'),
        Index('idx_objects_id_internal', 'id_internal'),
    )

    id = mapped_column(Uuid)
    id_type = mapped_column(
        Enum(
            'organization',
            'dataset',
            'collection',
            'package',
            'quantdb',
            name='remote_id_type',
        ),
        nullable=False,
    )
    id_file = mapped_column(Integer, nullable=True)
    id_internal = mapped_column(Uuid, nullable=True)

    # objects_internal: Mapped[Optional["ObjectsInternal"]] = relationship(
    #     "ObjectsInternal", foreign_keys=[id_internal], back_populates="objects"
    # )
    objects: Mapped['Objects'] = relationship(
        'Objects',
        secondary='dataset_object',
        primaryjoin=lambda: Objects.id == t_dataset_object.c.dataset,
        secondaryjoin=lambda: Objects.id == t_dataset_object.c.object,
        # back_populates="objects_",
        # cascade="all, delete-orphan",
    )
    objects_: Mapped['Objects'] = relationship(
        'Objects',
        secondary='dataset_object',
        primaryjoin=lambda: Objects.id == t_dataset_object.c.object,
        secondaryjoin=lambda: Objects.id == t_dataset_object.c.dataset,
        # back_populates="objects",
        # cascade="all, delete-orphan",
    )
    # objects_internal_: Mapped[List["ObjectsInternal"]] = relationship(
    #     "ObjectsInternal",
    #     uselist=True,
    #     foreign_keys="[ObjectsInternal.dataset]",
    #     back_populates="objects_",
    # )
    obj_desc_inst: Mapped[List['ObjDescInst']] = relationship(
        'ObjDescInst',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_cat: Mapped[List['ObjDescCat']] = relationship(
        'ObjDescCat',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_quant: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_inst: Mapped[List['ValuesInst']] = relationship(
        'ValuesInst',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_cat: Mapped[List['ValuesCat']] = relationship(
        'ValuesCat',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant',
        uselist=True,
        back_populates='objects',
        viewonly=True,
        cascade='all, delete-orphan',
    )

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


# class ObjectsInternal(Base):
#     __tablename__ = "objects_internal"
#     __table_args__ = (
#         CheckConstraint(
#             "type <> 'path-metadata'::oi_type OR updated_transitive IS NOT NULL AND dataset IS NOT NULL",
#             name="constraint_objects_internal_type_updated_transitive",
#         ),
#         ForeignKeyConstraint(
#             ["dataset"], ["objects.id"], name="constraint_oi_dataset_fk"
#         ),
#         PrimaryKeyConstraint("id", name="objects_internal_pkey"),
#         UniqueConstraint(
#             "dataset",
#             "updated_transitive",
#             name="objects_internal_dataset_updated_transitive_key",
#         ),
#     )

#     id = mapped_column(Uuid, server_default=text("gen_random_uuid()"))
#     type = mapped_column(
#         Enum("path-metadata", "other", name="oi_type"),
#         server_default=text("'other'::oi_type"),
#     )
#     dataset = mapped_column(Uuid)
#     updated_transitive = mapped_column(DateTime)
#     label = mapped_column(Text)
#     curator_note = mapped_column(Text)

# BUG: cycles!
# objects: Mapped[List["Objects"]] = relationship(
#     "Objects",
#     uselist=True,
#     foreign_keys="[Objects.id_internal]",
#     back_populates="objects_internal",
# )
# objects_: Mapped[Optional["Objects"]] = relationship(
#     "Objects", foreign_keys=[dataset], back_populates="objects_internal_"
# )


class Units(Base):
    __tablename__ = 'units'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='units_pkey'),
        UniqueConstraint('iri', name='units_iri_key'),
        UniqueConstraint('label', name='units_label_key'),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
        primary_key=True,
    )
    label = mapped_column(Text, nullable=False)
    iri = mapped_column(Text, nullable=False)

    descriptors_quant: Mapped[List['DescriptorsQuant']] = relationship(
        'DescriptorsQuant', uselist=True, back_populates='units'
    )


t_aspect_parent = Table(
    'aspect_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    ForeignKeyConstraint(['id'], ['aspects.id'], name='aspect_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['aspects.id'], name='aspect_parent_parent_fkey'),
    PrimaryKeyConstraint('id', 'parent', name='aspect_parent_pkey'),
)


t_class_parent = Table(
    'class_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    ForeignKeyConstraint(['id'], ['descriptors_inst.id'], name='class_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['descriptors_inst.id'], name='class_parent_parent_fkey'),
    PrimaryKeyConstraint('id', 'parent', name='class_parent_pkey'),
)


t_dataset_object = Table(
    'dataset_object',
    metadata,
    Column('dataset', Uuid, nullable=False),
    Column('object', Uuid, nullable=False),
    ForeignKeyConstraint(['dataset'], ['objects.id'], name='dataset_object_dataset_fkey'),
    ForeignKeyConstraint(['object'], ['objects.id'], name='dataset_object_object_fkey'),
    PrimaryKeyConstraint('dataset', 'object', name='dataset_object_pkey'),
)


class DescriptorsCat(Base):
    __tablename__ = 'descriptors_cat'
    __table_args__ = (
        ForeignKeyConstraint(
            ['domain'],
            ['descriptors_inst.id'],
            name='descriptors_cat_domain_fkey',
        ),
        PrimaryKeyConstraint('id', name='descriptors_cat_pkey'),
        UniqueConstraint(
            'domain',
            'range',
            'label',
            name='descriptors_cat_domain_range_label_key',
        ),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    domain = mapped_column(Integer)
    range = mapped_column(Enum('open', 'controlled', name='cat_range_type'))
    label = mapped_column(Text)
    description = mapped_column(Text)
    curator_note = mapped_column(Text)

    descriptors_inst: Mapped[Optional['DescriptorsInst']] = relationship(
        'DescriptorsInst', back_populates='descriptors_cat'
    )
    obj_desc_cat: Mapped[List['ObjDescCat']] = relationship(
        'ObjDescCat', uselist=True, back_populates='descriptors_cat'
    )
    values_cat: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, back_populates='descriptors_cat')


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
        ForeignKeyConstraint(['aspect'], ['aspects.id'], name='descriptors_quant_aspect_fkey'),
        ForeignKeyConstraint(
            ['domain'],
            ['descriptors_inst.id'],
            name='descriptors_quant_domain_fkey',
        ),
        ForeignKeyConstraint(['unit'], ['units.id'], name='descriptors_quant_unit_fkey'),
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
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    shape = mapped_column(
        Enum('scalar', name='quant_shape'),
        nullable=False,
        server_default=text("'scalar'::quant_shape"),
    )
    label = mapped_column(Text, nullable=False)
    aggregation_type = mapped_column(
        Enum(
            'instance',
            'function',
            'summary',
            'mean',
            'media',
            'mode',
            'sum',
            'min',
            'max',
            name='quant_agg_type',
        ),
        nullable=False,
        server_default=text("'instance'::quant_agg_type"),
    )
    unit = mapped_column(Integer)
    aspect = mapped_column(Integer, ForeignKey('aspects.id'))
    domain = mapped_column(Integer)
    description = mapped_column(Text)
    curator_note = mapped_column(Text)

    aspects: Mapped[Optional['Aspects']] = relationship(
        'Aspects',
        back_populates='descriptors_quant',
        # viewonly=True,
        # cascade="all, delete-orphan",
    )
    descriptors_inst: Mapped[Optional['DescriptorsInst']] = relationship(
        'DescriptorsInst',
        back_populates='descriptors_quant',
        # viewonly=True,
        # cascade="all, delete-orphan",
    )
    units: Mapped[Optional['Units']] = relationship('Units', back_populates='descriptors_quant')
    obj_desc_quant: Mapped[List['ObjDescQuant']] = relationship(
        'ObjDescQuant',
        uselist=True,
        back_populates='descriptors_quant',
        # viewonly=True,
        # cascade="all, delete-orphan",
    )
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant', uselist=True, back_populates='descriptors_quant'
    )


class ObjDescInst(Base):
    __tablename__ = 'obj_desc_inst'
    __table_args__ = (
        ForeignKeyConstraint(
            ['addr_desc_inst'],
            ['addresses.id'],
            name='obj_desc_inst_addr_desc_inst_fkey',
        ),
        ForeignKeyConstraint(
            ['addr_field'],
            ['addresses.id'],
            name='obj_desc_inst_addr_field_fkey',
        ),
        ForeignKeyConstraint(
            ['desc_inst'],
            ['descriptors_inst.id'],
            name='obj_desc_inst_desc_inst_fkey',
        ),
        ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_inst_object_fkey'),
        PrimaryKeyConstraint('object', 'desc_inst', name='obj_desc_inst_pkey'),
    )

    object = mapped_column(Uuid, nullable=False)
    desc_inst = mapped_column(Integer, nullable=False)
    addr_field = mapped_column(Integer, nullable=False)
    addr_desc_inst = mapped_column(Integer)
    expect = mapped_column(Integer)

    addresses: Mapped[Optional['Addresses']] = relationship(
        'Addresses',
        foreign_keys=[addr_desc_inst],
        back_populates='obj_desc_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    addresses_field: Mapped['Addresses'] = relationship(
        'Addresses',
        foreign_keys=[addr_field],
        back_populates='obj_desc_inst_',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    descriptors_inst: Mapped['DescriptorsInst'] = relationship(
        'DescriptorsInst',
        back_populates='obj_desc_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    objects: Mapped['Objects'] = relationship(
        'Objects',
        back_populates='obj_desc_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_cat: Mapped[List['ValuesCat']] = relationship(
        'ValuesCat',
        uselist=True,
        back_populates='obj_desc_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant',
        uselist=True,
        back_populates='obj_desc_inst',
        viewonly=True,
        cascade='all, delete-orphan',
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
        CheckConstraint("id_sam ~ '^sam-'::text", name='values_inst_id_sam_check'),
        CheckConstraint("id_sub ~ '^sub-'::text", name='values_inst_id_sub_check'),
        CheckConstraint(
            "type <> 'below'::instance_type OR id_sub IS NOT NULL OR id_sam IS NOT NULL",
            name='constraint_values_inst_type_below',
        ),
        CheckConstraint(
            "type <> 'sample'::instance_type OR id_sam IS NOT NULL AND id_sam = id_formal",
            name='constraint_values_inst_type_id_sam',
        ),
        CheckConstraint(
            "type <> 'subject'::instance_type OR id_sub = id_formal AND id_sam IS NULL",
            name='constraint_values_inst_type_id_sub',
        ),
        CheckConstraint(
            "type = 'below'::instance_type AND NOT id_formal ~ '^(sub|sam)-'::text OR type = 'subject'::instance_type AND id_formal ~ '^sub-'::text OR type = 'sample'::instance_type AND id_formal ~ '^sam-'::text",
            name='constraint_values_inst_type_id_formal',
        ),
        ForeignKeyConstraint(['dataset'], ['objects.id'], name='values_inst_dataset_fkey'),
        ForeignKeyConstraint(
            ['desc_inst'],
            ['descriptors_inst.id'],
            name='values_inst_desc_inst_fkey',
        ),
        PrimaryKeyConstraint('id', name='values_inst_pkey'),
        UniqueConstraint('dataset', 'id_formal', name='values_inst_dataset_id_formal_key'),
        Index('idx_values_inst_dataset', 'dataset'),
        Index('idx_values_inst_dataset_id_formal', 'dataset', 'id_formal'),
        Index('idx_values_inst_dataset_id_sam', 'dataset', 'id_sam'),
        Index('idx_values_inst_dataset_id_sub', 'dataset', 'id_sub'),
        Index('idx_values_inst_desc_inst', 'desc_inst'),
        Index('idx_values_inst_id_formal', 'id_formal'),
        Index('idx_values_inst_id_sam', 'id_sam'),
        Index('idx_values_inst_id_sub', 'id_sub'),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    type = mapped_column(Enum('subject', 'sample', 'below', name='instance_type'), nullable=False)
    id_sub = mapped_column(Text, nullable=False)
    desc_inst = mapped_column(Integer)
    dataset = mapped_column(Uuid, ForeignKey('objects.id'))
    id_formal = mapped_column(Text)
    local_identifier = mapped_column(Text)
    id_sam = mapped_column(Text)

    objects: Mapped[Optional['Objects']] = relationship(
        'Objects',
        back_populates='values_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    descriptors_inst: Mapped[Optional['DescriptorsInst']] = relationship(
        'DescriptorsInst',
        back_populates='values_inst',
        viewonly=True,
        # cascade="all, delete-orphan",
        # single_parent=True,
    )
    # values_inst: Mapped["ValuesInst"] = relationship(
    #     "ValuesInst",
    #     secondary="equiv_inst",
    #     primaryjoin=lambda: ValuesInst.id == t_equiv_inst.c.left_thing,
    #     secondaryjoin=lambda: ValuesInst.id == t_equiv_inst.c.right_thing,
    #     back_populates="values_inst_",
    # )
    # values_inst_: Mapped["ValuesInst"] = relationship(
    #     "ValuesInst",
    #     secondary="equiv_inst",
    #     primaryjoin=lambda: ValuesInst.id == t_equiv_inst.c.right_thing,
    #     secondaryjoin=lambda: ValuesInst.id == t_equiv_inst.c.left_thing,
    #     back_populates="values_inst",
    # )
    # values_inst1: Mapped["ValuesInst"] = relationship(
    #     "ValuesInst",
    #     secondary="instance_parent",
    #     primaryjoin=lambda: ValuesInst.id == t_instance_parent.c.id,
    #     secondaryjoin=lambda: ValuesInst.id == t_instance_parent.c.parent,
    #     back_populates="values_inst2",
    # )
    # values_inst2: Mapped["ValuesInst"] = relationship(
    #     "ValuesInst",
    #     secondary="instance_parent",
    #     primaryjoin=lambda: ValuesInst.id == t_instance_parent.c.parent,
    #     secondaryjoin=lambda: ValuesInst.id == t_instance_parent.c.id,
    #     back_populates="values_inst1",
    # )
    values_cat: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, back_populates='values_inst')
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant',
        uselist=True,
        back_populates='values_inst',
        viewonly=True,
        cascade='all, delete-orphan',
    )


t_equiv_inst = Table(
    'equiv_inst',
    metadata,
    Column('left_thing', Integer, nullable=False),
    Column('right_thing', Integer, nullable=False),
    CheckConstraint('left_thing <> right_thing', name='sse_no_self'),
    ForeignKeyConstraint(['left_thing'], ['values_inst.id'], name='equiv_inst_left_thing_fkey'),
    ForeignKeyConstraint(['right_thing'], ['values_inst.id'], name='equiv_inst_right_thing_fkey'),
    PrimaryKeyConstraint('left_thing', 'right_thing', name='equiv_inst_pkey'),
)


t_instance_parent = Table(
    'instance_parent',
    metadata,
    Column('id', Integer, nullable=False),
    Column('parent', Integer, nullable=False),
    ForeignKeyConstraint(['id'], ['values_inst.id'], name='instance_parent_id_fkey'),
    ForeignKeyConstraint(['parent'], ['values_inst.id'], name='instance_parent_parent_fkey'),
    PrimaryKeyConstraint('id', 'parent', name='instance_parent_pkey'),
)


class ObjDescCat(Base):
    __tablename__ = 'obj_desc_cat'
    __table_args__ = (
        ForeignKeyConstraint(
            ['addr_desc_inst'],
            ['addresses.id'],
            name='obj_desc_cat_addr_desc_inst_fkey',
        ),
        ForeignKeyConstraint(
            ['addr_field'],
            ['addresses.id'],
            name='obj_desc_cat_addr_field_fkey',
        ),
        ForeignKeyConstraint(
            ['desc_cat'],
            ['descriptors_cat.id'],
            name='obj_desc_cat_desc_cat_fkey',
        ),
        ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_cat_object_fkey'),
        PrimaryKeyConstraint('object', 'desc_cat', name='obj_desc_cat_pkey'),
    )

    object = mapped_column(Uuid, nullable=False)
    desc_cat = mapped_column(Integer, nullable=False)
    addr_field = mapped_column(Integer, nullable=False)
    addr_desc_inst = mapped_column(Integer)
    expect = mapped_column(Integer)

    addresses: Mapped[Optional['Addresses']] = relationship(
        'Addresses',
        foreign_keys=[addr_desc_inst],
        back_populates='obj_desc_cat',
    )
    addresses_: Mapped['Addresses'] = relationship(
        'Addresses', foreign_keys=[addr_field], back_populates='obj_desc_cat_'
    )
    descriptors_cat: Mapped['DescriptorsCat'] = relationship('DescriptorsCat', back_populates='obj_desc_cat')
    objects: Mapped['Objects'] = relationship('Objects', back_populates='obj_desc_cat')
    values_cat: Mapped[List['ValuesCat']] = relationship('ValuesCat', uselist=True, back_populates='obj_desc_cat')


class ObjDescQuant(Base):
    __tablename__ = 'obj_desc_quant'
    __table_args__ = (
        ForeignKeyConstraint(
            ['addr_aspect'],
            ['addresses.id'],
            name='obj_desc_quant_addr_aspect_fkey',
        ),
        ForeignKeyConstraint(
            ['addr_desc_inst'],
            ['addresses.id'],
            name='obj_desc_quant_addr_desc_inst_fkey',
        ),
        ForeignKeyConstraint(
            ['addr_field'],
            ['addresses.id'],
            name='obj_desc_quant_addr_field_fkey',
        ),
        ForeignKeyConstraint(
            ['addr_unit'],
            ['addresses.id'],
            name='obj_desc_quant_addr_unit_fkey',
        ),
        ForeignKeyConstraint(
            ['desc_quant'],
            ['descriptors_quant.id'],
            name='obj_desc_quant_desc_quant_fkey',
        ),
        ForeignKeyConstraint(['object'], ['objects.id'], name='obj_desc_quant_object_fkey'),
        PrimaryKeyConstraint('object', 'desc_quant', name='obj_desc_quant_pkey'),
    )

    object = mapped_column(Uuid, nullable=False)
    desc_quant = mapped_column(Integer, nullable=False)
    addr_field = mapped_column(Integer, nullable=False)
    addr_unit = mapped_column(Integer)
    addr_aspect = mapped_column(Integer)
    addr_desc_inst = mapped_column(Integer)
    expect = mapped_column(Integer)

    addresses: Mapped[Optional['Addresses']] = relationship(
        'Addresses',
        foreign_keys=[addr_desc_inst],
        back_populates='obj_desc_quant_',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    addresses_aspect: Mapped[Optional['Addresses']] = relationship(
        'Addresses',
        foreign_keys=[addr_aspect],
        back_populates='obj_desc_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    addresses_field: Mapped['Addresses'] = relationship(
        'Addresses',
        foreign_keys=[addr_field],
        back_populates='obj_desc_quant1',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    addresses_unit: Mapped[Optional['Addresses']] = relationship(
        'Addresses',
        foreign_keys=[addr_unit],
        back_populates='obj_desc_quant2',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    descriptors_quant: Mapped['DescriptorsQuant'] = relationship(
        'DescriptorsQuant',
        back_populates='obj_desc_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    objects: Mapped['Objects'] = relationship(
        'Objects',
        back_populates='obj_desc_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_quant: Mapped[List['ValuesQuant']] = relationship(
        'ValuesQuant',
        uselist=True,
        back_populates='obj_desc_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )


class ValuesCat(Base):
    __tablename__ = 'values_cat'
    __table_args__ = (
        CheckConstraint(
            'value_open IS NOT NULL OR value_controlled IS NOT NULL',
            name='constraint_values_cat_some_value',
        ),
        ForeignKeyConstraint(
            ['desc_cat'],
            ['descriptors_cat.id'],
            name='values_cat_desc_cat_fkey',
        ),
        ForeignKeyConstraint(
            ['desc_inst'],
            ['descriptors_inst.id'],
            name='values_cat_desc_inst_fkey',
        ),
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
        ForeignKeyConstraint(
            ['value_controlled'],
            ['controlled_terms.id'],
            name='values_cat_value_controlled_fkey',
        ),
        PrimaryKeyConstraint('id', name='values_cat_pkey'),
        Index('idx_values_cat_desc_cat', 'desc_cat'),
        Index('idx_values_cat_desc_inst', 'desc_inst'),
        Index('idx_values_cat_instance', 'instance'),
        Index('idx_values_cat_object', 'object'),
        Index('idx_values_cat_value_controlled', 'value_controlled'),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    object = mapped_column(Uuid, nullable=False)
    desc_inst = mapped_column(Integer, nullable=False)
    desc_cat = mapped_column(Integer, nullable=False)
    value_open = mapped_column(Text)
    value_controlled = mapped_column(Integer)
    instance = mapped_column(Integer)

    descriptors_cat: Mapped['DescriptorsCat'] = relationship('DescriptorsCat', back_populates='values_cat')
    descriptors_inst: Mapped['DescriptorsInst'] = relationship('DescriptorsInst', back_populates='values_cat')
    values_inst: Mapped[Optional['ValuesInst']] = relationship('ValuesInst', back_populates='values_cat')
    obj_desc_cat: Mapped['ObjDescCat'] = relationship('ObjDescCat', back_populates='values_cat')
    obj_desc_inst: Mapped['ObjDescInst'] = relationship('ObjDescInst', back_populates='values_cat')
    objects: Mapped['Objects'] = relationship('Objects', back_populates='values_cat')
    controlled_terms: Mapped[Optional['ControlledTerms']] = relationship('ControlledTerms', back_populates='values_cat')


class ValuesQuant(Base):
    __tablename__ = 'values_quant'
    __table_args__ = (
        ForeignKeyConstraint(
            ['desc_inst'],
            ['descriptors_inst.id'],
            name='values_quant_desc_inst_fkey',
        ),
        ForeignKeyConstraint(
            ['desc_quant'],
            ['descriptors_quant.id'],
            name='values_quant_desc_quant_fkey',
        ),
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
        PrimaryKeyConstraint('id', name='values_quant_pkey'),
        Index('idx_values_quant_desc_inst', 'desc_inst'),
        Index('idx_values_quant_desc_quant', 'desc_quant'),
        Index('idx_values_quant_instance', 'instance'),
        Index('idx_values_quant_object', 'object'),
    )

    id = mapped_column(
        Integer,
        Identity(
            start=1,
            increment=1,
            minvalue=1,
            maxvalue=2147483647,
            cycle=False,
            cache=1,
        ),
    )
    value = mapped_column(Numeric, nullable=False)
    object = mapped_column(
        Uuid, ForeignKey('objects.id'), nullable=False
    )  # TODO: object is not obj id, but File Obj ID that | should be same
    desc_inst = mapped_column(Integer, nullable=False)
    desc_quant = mapped_column(Integer, nullable=False)
    value_blob = mapped_column(JSONB, nullable=False)
    instance = mapped_column(Integer)
    orig_value = mapped_column(String)
    orig_units = mapped_column(String)

    descriptors_inst: Mapped['DescriptorsInst'] = relationship(
        'DescriptorsInst',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    descriptors_quant: Mapped['DescriptorsQuant'] = relationship(
        'DescriptorsQuant',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    values_inst: Mapped[Optional['ValuesInst']] = relationship(
        'ValuesInst',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )
    obj_desc_inst: Mapped['ObjDescInst'] = relationship(
        'ObjDescInst',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
        # sync_backref=False,
    )
    obj_desc_quant: Mapped['ObjDescQuant'] = relationship(
        'ObjDescQuant',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
        # sync_backref=False,
    )
    objects: Mapped['Objects'] = relationship(
        'Objects',
        back_populates='values_quant',
        viewonly=True,
        cascade='all, delete-orphan',
    )

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


# @event.listens_for(ValuesQuant.descriptors_inst, "set")
# def set_desc_inst_from_descriptor(target, value, oldvalue, initiator):
#     print(target, value, oldvalue, initiator)
#     if value is not None:
#         target.desc_inst = value.id


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


# # Attach the listener to all attributes on the Parent model
# for column in ValuesQuant.__table__.columns:
#     event.listen(getattr(ValuesQuant, column.name), "set", update_all_children)


# @event.listens_for(ValuesQuant.descriptors_inst, "set")
# def update_desc_inst(target, value, oldvalue, initiator):
#     if value is not None:
#         target.desc_inst = value.id


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
