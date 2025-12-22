"""Backward-compatible client module wrapping automap_client."""
from quantdb.automap_client import get_automap_session


def get_session(echo: bool = True, test: bool = False):
    """Get a SQLAlchemy session (drops models for compatibility)."""
    session, _ = get_automap_session(test=test, echo=echo)
    return session
