from dataclasses import dataclass

import orthauth as oa

from quantdb.utils import dbUri

auth = oa.configure_here('auth-config.py', __name__)


@dataclass
class Settings:
    """Settings for the app."""

    db_params = {k: auth.get(f'db-{k}') for k in ('user', 'host', 'port', 'database')}
    db_params['dbuser'] = db_params.pop('user')
    SQLALCHEMY_DATABASE_URI = dbUri(**db_params)
