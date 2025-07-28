import ast
import uuid

import pandas as pd
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ClauseElement

from quantdb.client import get_session
from quantdb.models import Objects

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
