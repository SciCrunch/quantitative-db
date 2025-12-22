import ast
import uuid

import pandas as pd
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ClauseElement

from quantdb.client import get_session

# Objects model will be imported dynamically when needed
Objects = None

# df = pd.read_csv("data/CadaverVNMorphology_OutputMetrics.csv", index_col=0)
# df = df.T.reset_index(drop=True)
# df["id_sub"] = "sub-" + df.sub_sam
# df.index = df.index + 1
# df.head()


def object_as_dict(obj):
    """
    Convert SQLAlchemy ORM object to a dictionary of attributes.

    Parameters
    ----------
    obj : SQLAlchemy ORM object
        The object to convert to a dictionary.

    Returns
    -------
    dict
        Dictionary containing non-null column attributes of the object.
        UUID objects are converted to strings for consistency.
    """
    result = {}
    for c in inspect(obj).mapper.column_attrs:
        value = getattr(obj, c.key)
        if value is not None:
            # Convert UUID objects to strings for consistency
            if hasattr(value, 'hex') and hasattr(value, 'version'):  # Check if it's a UUID object
                result[c.key] = str(value)
            else:
                result[c.key] = value
    return result


def get_or_create(session, obj, back_populate=None):
    """
    Retrieve an existing instance of the object from the database, or create it if it does not exist.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        The database session to use for querying and committing.
    obj : SQLAlchemy model instance
        The object to retrieve or create.
    back_populate : dict, optional
        Dictionary mapping attribute names to values to back-populate after creation.

    Returns
    -------
    instance : SQLAlchemy model instance
        The retrieved or newly created instance with UUID attributes converted to strings.

    Notes
    -----
    The function will roll back the transaction and attempt to retrieve the object
    if an exception occurs during creation.
    """
    model = obj.__class__
    data = object_as_dict(obj)

    # First, try to find existing object by all attributes
    instance = session.query(model).filter_by(**data).one_or_none()
    if instance:
        # Convert UUID attributes to strings for consistency
        _convert_uuids_to_strings(instance)
        return instance

    # If not found by all attributes, try constraint-based query
    instance = query_by_constraints(session, obj)
    if instance:
        # Convert UUID attributes to strings for consistency
        _convert_uuids_to_strings(instance)
        return instance

    # No existing instance found, create new one
    params = {k: v for k, v in data.items() if not isinstance(v, ClauseElement)}
    instance = model(**params)
    try:
        session.add(instance)
        session.commit()
        if back_populate:
            for attr, value in back_populate.items():
                setattr(instance, attr, value)
            session.commit()
        # Convert UUID attributes to strings for consistency
        _convert_uuids_to_strings(instance)
        return instance
    except Exception:
        # Creation failed, likely due to unique constraint violation
        # Rollback and try to find the existing record again
        session.rollback()

        # Try both approaches to find the existing record
        instance = session.query(model).filter_by(**data).one_or_none()
        if not instance:
            instance = query_by_constraints(session, obj)

        if instance:
            _convert_uuids_to_strings(instance)
            return instance
        else:
            # This shouldn't happen, but if it does, re-raise the original error
            raise


def _convert_uuids_to_strings(obj):
    """
    Convert UUID attributes to strings in-place for an ORM object.

    Parameters
    ----------
    obj : SQLAlchemy ORM object
        The object to modify.
    """
    for c in inspect(obj).mapper.column_attrs:
        value = getattr(obj, c.key)
        if value is not None and hasattr(value, 'hex') and hasattr(value, 'version'):
            setattr(obj, c.key, str(value))


def get_constraint_columns(model):
    """
    Returns the columns of the unique constraints and primary key constraints for a SQLAlchemy model.

    Parameters
    ----------
    model : SQLAlchemy model class
        The SQLAlchemy model class to inspect for constraints.

    Returns
    -------
    list of list of str
        A list of lists, where each inner list contains the column names
        that form a unique constraint or primary key constraint.
    """
    constraints = [
        constraint
        for constraint in model.__mapper__.tables[0].constraints
        if isinstance(constraint, (UniqueConstraint, PrimaryKeyConstraint))
    ]

    return [[c.name for c in list(constraint.columns)] for constraint in constraints]


def query_by_constraints(db, obj):
    """
    Query for an existing object in the database using its unique constraints.

    Parameters
    ----------
    db : sqlalchemy.orm.Session
        The database session to use for querying.
    obj : SQLAlchemy model instance
        The object to find in the database.

    Returns
    -------
    SQLAlchemy model instance or None
        The existing instance if found with UUID attributes converted to strings, None otherwise.
    """
    filter_criteria = object_as_dict(obj)

    existing_obj = None
    for cols in get_constraint_columns(obj.__class__):
        if set(cols) != (set(cols) & set(filter_criteria.keys())):
            continue

        constraint_filter = {key: value for key, value in filter_criteria.items() if key in cols}

        existing_obj = db.query(type(obj)).filter_by(**constraint_filter).first()
        if existing_obj:
            # Convert UUID attributes to strings for consistency
            _convert_uuids_to_strings(existing_obj)
            return existing_obj


def back_populate_tables(db: Session, obj) -> object:
    """
    Recursively back-populates objects in the database,
    retrieving existing objects instead of failing on duplicates.

    Parameters
    ----------
    db : sqlalchemy.orm.Session
        The database session.
    obj : SQLAlchemy model instance
        The ORM model object.

    Returns
    -------
    object
        The ORM model object, with its related objects back-populated and UUID attributes converted to strings.

    Notes
    -----
    This function:
    - Iterates through all relationships of the object
    - Handles both initial population and recursive calls
    - Performs a complete rollback if any commit fails
    - Filters by all primary key columns of the object
    - Handles cases where the child object is not a valid ORM instance
    - Converts UUID attributes to strings for consistency
    """
    mapper = obj.__mapper__  # Get the mapper for the object
    # print(obj)
    try:
        # Iterate through all relationships of the object
        for relationship_prop in mapper.relationships:
            if relationship_prop.direction.name == 'MANYTOONE' or relationship_prop.direction.name == 'MANYTOMANY':
                parent = getattr(obj, relationship_prop.key)
                if parent:
                    filter_criteria = object_as_dict(parent)
                    existing_obj = db.query(type(parent)).filter_by(**filter_criteria).first()
                    if existing_obj:
                        _convert_uuids_to_strings(existing_obj)
                        for key, value in object_as_dict(existing_obj).items():
                            if hasattr(parent, key):
                                setattr(parent, key, value)
                    # print("populated", object_as_dict(parent))
                    setattr(obj, relationship_prop.key, parent)
                    # db.add(parent)
                    # db.commit()
                    back_populate_tables(db, parent)

        # print("object", type(obj))
        filter_criteria = object_as_dict(obj)
        # print(type(obj), filter_criteria)
        existing_obj = db.query(type(obj)).filter_by(**filter_criteria).first()
        # print('filter criteria', filter_criteria)
        # print('found:', existing_obj)

        if not existing_obj:
            existing_obj = query_by_constraints(db, obj)

        # print("filter using", filter_criteria)
        # existing_obj = db.query(type(obj)).filter_by(**filter_criteria).first()
        # print("is existing??", existing_obj)

        if not existing_obj:
            db.add(obj)
            # db.add(obj)
            # db.flush()
            db.commit()
            # db.refresh(obj)
            # print('added new')
        else:
            _convert_uuids_to_strings(existing_obj)
            db.merge(obj)
            db.commit()
            for key, value in object_as_dict(existing_obj).items():
                if hasattr(obj, key):
                    setattr(obj, key, value)
            # print('updated existing')
            # print("after update", object_as_dict(existing_obj))

    except IntegrityError:
        db.rollback()  # Rollback the transaction in case of an error
        # print(f"Error during commit: {e}")
        raise  # Re-raise the exception to indicate failure

    # Convert UUID attributes to strings for consistency in the returned object
    _convert_uuids_to_strings(obj)
    return obj  # Return the object with its related objects back-populated


def get_or_create_dynamic(session, model_class, data: dict, unique_keys: list = None):
    """
    Get or create a record using dynamically reflected models.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        The database session.
    model_class : class
        The automap model class.
    data : dict
        Dictionary of column values.
    unique_keys : list, optional
        List of column names that form the unique constraint.
        If None, tries to find by all provided data.

    Returns
    -------
    tuple
        (instance, created) where instance is the model instance
        and created is True if a new record was created.
    """
    # Convert UUIDs to strings for consistency
    clean_data = {}
    for k, v in data.items():
        if v is not None and hasattr(v, 'hex') and hasattr(v, 'version'):
            clean_data[k] = str(v)
        else:
            clean_data[k] = v

    # Try to find by unique keys if provided
    if unique_keys:
        filter_dict = {k: clean_data[k] for k in unique_keys if k in clean_data}
        instance = session.query(model_class).filter_by(**filter_dict).first()
        if instance:
            return instance, False

    # Try to find by all data
    instance = session.query(model_class).filter_by(**clean_data).first()
    if instance:
        return instance, False

    # Create new instance
    instance = model_class(**clean_data)
    try:
        session.add(instance)
        session.flush()
        return instance, True
    except IntegrityError:
        session.rollback()
        # Race condition - try to find again
        if unique_keys:
            filter_dict = {k: clean_data[k] for k in unique_keys if k in clean_data}
            instance = session.query(model_class).filter_by(**filter_dict).first()
        else:
            instance = session.query(model_class).filter_by(**clean_data).first()
        if instance:
            return instance, False
        raise


def back_populate_with_dependencies(
    session, records: list, models: dict, table_order: list = None, commit_batch: int = 1000
) -> dict:
    """
    Insert records respecting foreign key dependencies.

    This function handles bulk insertion of records across multiple tables,
    automatically resolving foreign key dependencies and using get-or-create
    semantics for idempotent operations.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        The database session.
    records : list
        List of dicts with 'table' and 'data' keys, where 'table' is the
        table name and 'data' is a dict of column values.
    models : dict
        Dictionary mapping table names to model classes (from automap).
    table_order : list, optional
        Pre-computed table insertion order. If None, records are processed
        in the order provided.
    commit_batch : int
        Number of records to process before committing (default: 1000).

    Returns
    -------
    dict
        Dictionary mapping (table_name, unique_key_tuple) to created instances.

    Example
    -------
    >>> records = [
    ...     {'table': 'objects', 'data': {'id': uuid, 'id_type': 'dataset'}},
    ...     {'table': 'values_inst', 'data': {'dataset': uuid, 'id_formal': 'sub-1', ...}},
    ... ]
    >>> results = back_populate_with_dependencies(session, records, models)
    """
    # Group records by table
    by_table = {}
    for rec in records:
        table = rec['table']
        if table not in by_table:
            by_table[table] = []
        by_table[table].append(rec['data'])

    # Determine insertion order
    if table_order:
        ordered_tables = [t for t in table_order if t in by_table]
    else:
        ordered_tables = list(by_table.keys())

    # Track created instances
    created = {}
    count = 0

    for table_name in ordered_tables:
        model = models.get(table_name)
        if model is None:
            continue

        # Get unique constraint columns for this table
        unique_keys = None
        if hasattr(model, '__table__'):
            for constraint in model.__table__.constraints:
                if isinstance(constraint, (UniqueConstraint, PrimaryKeyConstraint)):
                    unique_keys = [c.name for c in constraint.columns]
                    break

        for data in by_table[table_name]:
            instance, is_new = get_or_create_dynamic(session, model, data, unique_keys)

            # Create a key for tracking
            if unique_keys:
                key_vals = tuple(getattr(instance, k, None) for k in unique_keys)
                created[(table_name, key_vals)] = instance
            else:
                created[(table_name, id(data))] = instance

            count += 1
            if count % commit_batch == 0:
                session.commit()

    session.commit()
    return created


def create_all_descriptors_from_yaml(session, models: dict, yaml_config: dict) -> dict:
    """
    Create all descriptors (aspects, units, descriptors_inst, etc.) from YAML config.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        The database session.
    models : dict
        Dictionary mapping table names to model classes.
    yaml_config : dict
        Parsed YAML configuration with aspects, units, descriptors, etc.

    Returns
    -------
    dict
        Dictionary mapping descriptor labels to their database IDs.
    """
    created_ids = {
        'aspects': {},
        'units': {},
        'descriptors_inst': {},
        'descriptors_quant': {},
        'descriptors_cat': {},
        'controlled_terms': {},
        'addresses': {},
    }

    # Create aspects
    Aspects = models.get('aspects')
    if Aspects and 'aspects' in yaml_config:
        for aspect_data in yaml_config['aspects']:
            instance, _ = get_or_create_dynamic(
                session, Aspects, {'label': aspect_data['label'], 'iri': aspect_data['iri']}, unique_keys=['label']
            )
            created_ids['aspects'][aspect_data['label']] = instance.id

    # Create units
    Units = models.get('units')
    if Units and 'units' in yaml_config:
        for unit_data in yaml_config['units']:
            instance, _ = get_or_create_dynamic(
                session, Units, {'label': unit_data['label'], 'iri': unit_data['iri']}, unique_keys=['label']
            )
            created_ids['units'][unit_data['label']] = instance.id

    # Create controlled terms
    ControlledTerms = models.get('controlled_terms')
    if ControlledTerms and 'controlled_terms' in yaml_config:
        for term_data in yaml_config['controlled_terms']:
            instance, _ = get_or_create_dynamic(
                session, ControlledTerms, {'label': term_data['label'], 'iri': term_data['iri']}, unique_keys=['label']
            )
            created_ids['controlled_terms'][term_data['label']] = instance.id

    # Create instance descriptors
    DescriptorsInst = models.get('descriptors_inst')
    if DescriptorsInst and 'descriptors' in yaml_config:
        inst_types = yaml_config['descriptors'].get('instance_types', [])
        for desc_data in inst_types:
            instance, _ = get_or_create_dynamic(
                session, DescriptorsInst, {'label': desc_data['label'], 'iri': desc_data['iri']}, unique_keys=['label']
            )
            created_ids['descriptors_inst'][desc_data['label']] = instance.id

    # Create addresses
    Addresses = models.get('addresses')
    if Addresses and 'addresses' in yaml_config:
        for addr_name, addr_data in yaml_config['addresses'].items():
            instance, _ = get_or_create_dynamic(
                session,
                Addresses,
                {
                    'addr_type': addr_data['addr_type'],
                    'addr_field': addr_data.get('addr_field'),
                    'value_type': addr_data.get('value_type', 'single'),
                },
                unique_keys=['addr_type', 'addr_field', 'value_type'],
            )
            created_ids['addresses'][addr_name] = instance.id

    session.commit()

    # Create quantitative descriptors (depends on aspects, units, descriptors_inst)
    DescriptorsQuant = models.get('descriptors_quant')
    if DescriptorsQuant and 'descriptors' in yaml_config:
        quant_descs = yaml_config['descriptors'].get('quantitative', [])
        for desc_data in quant_descs:
            data = {
                'label': desc_data['label'],
                'shape': desc_data.get('shape', 'scalar'),
                'aggregation_type': desc_data.get('aggregation_type', 'instance'),
            }
            if desc_data.get('domain'):
                data['domain'] = created_ids['descriptors_inst'].get(desc_data['domain'])
            if desc_data.get('aspect'):
                data['aspect'] = created_ids['aspects'].get(desc_data['aspect'])
            if desc_data.get('unit'):
                data['unit'] = created_ids['units'].get(desc_data['unit'])

            instance, _ = get_or_create_dynamic(session, DescriptorsQuant, data, unique_keys=['label'])
            created_ids['descriptors_quant'][desc_data['label']] = instance.id

    # Create categorical descriptors
    DescriptorsCat = models.get('descriptors_cat')
    if DescriptorsCat and 'descriptors' in yaml_config:
        cat_descs = yaml_config['descriptors'].get('categorical', [])
        for desc_data in cat_descs:
            data = {
                'label': desc_data['label'],
                'range': desc_data.get('range', 'controlled'),
            }
            if desc_data.get('domain'):
                data['domain'] = created_ids['descriptors_inst'].get(desc_data['domain'])

            instance, _ = get_or_create_dynamic(session, DescriptorsCat, data, unique_keys=['domain', 'range', 'label'])
            created_ids['descriptors_cat'][desc_data['label']] = instance.id

    session.commit()
    return created_ids


if __name__ == '__main__':

    session = get_session(echo=False)

    object_dataset = Objects(
        id='55c5b69c-a5b8-4881-a105-e4048af26fa5',
        id_type='dataset',
        id_file=None,
        id_internal=None,
    )
    object_package = Objects(
        id='20720c2e-83fb-4454-bef1-1ce6a97fa748',
        id_type='package',
        id_file=1094489,
        id_internal=None,
        objects_=object_dataset,
    )
    back_populate_tables(session, object_package)
