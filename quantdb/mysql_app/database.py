from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from quantdb.config import Settings

# TODO: get new setting env setup first
# SQLALCHEMY_DATABASE_URL = Settings().MYSQL_URL

# engine = create_engine(SQLALCHEMY_DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: Any = declarative_base()
