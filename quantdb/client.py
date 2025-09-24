from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy import text

from quantdb.config import auth
from quantdb.utils import dbUri


def get_session(echo: bool = True, test: bool = False) -> Session:
    """
    Get a SQLAlchemy session for the main or test database.

    Parameters
    ----------
    echo : bool, optional
        If True, SQLAlchemy will log all statements.
    test : bool, optional
        If True, connect to the test database (quantdb_test or as configured).

    Returns
    -------
    session : sqlalchemy.orm.Session
        The database session.
    """
    # pull in the db connection info
    if test:
        # For testing, ALWAYS use local postgres instance regardless of main db config
        dbkwargs = {
            "dbuser": "quantdb-test-admin",
            "host": "localhost",  # FORCE localhost for all testing
            "port": 5432,
            "database": auth.get("test-db-database") or "quantdb_test",
            "password": "tom-is-cool",  # Use hardcoded password for test database
        }
    else:
        # For non-test, use regular database configuration
        dbkwargs = {k: auth.get(f"db-{k}") for k in ("user", "host", "port", "database")}
        dbkwargs["dbuser"] = dbkwargs.pop("user")
    print(dbkwargs)
    engine = create_engine(dbUri(**dbkwargs))  # type: ignore
    engine.echo = echo
    print(engine, dbkwargs)
    session = Session(engine)
    return session


if __name__ == "__main__":
    session = get_session(echo=False)
    print(session.execute(text("SELECT * FROM information_schema.tables")).fetchall())
