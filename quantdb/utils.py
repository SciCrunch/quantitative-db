import logging
import os
import sys
from datetime import datetime


def makeSimpleLogger(name, level=logging.INFO):
    # TODO use extra ...
    logger = logging.getLogger(name)
    if logger.handlers:  # prevent multiple handlers
        return logger

    logger.setLevel(level)
    ch = logging.StreamHandler()  # FileHander goes to disk
    fmt = '[%(asctime)s] - %(levelname)8s - ' '%(name)14s - ' '%(filename)16s:%(lineno)-4d - ' '%(message)s'
    formatter = logging.Formatter(fmt)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


log = makeSimpleLogger('quantdb')
logd = log.getChild('data')


# from pyontutils.utils_fast import setPS1
def setPS1(script__file__):
    try:
        text = 'Running ' + os.path.basename(script__file__)
        os.sys.stdout.write('\x1b]2;{}\x07\n'.format(text))
    except AttributeError as e:
        log.exception(e)


def dbUri(dbuser, host, port, database):
    if hasattr(sys, 'pypy_version_info'):
        dialect = 'psycopg2cffi'
    else:
        dialect = 'psycopg2'
    return f'postgresql+{dialect}://{dbuser}@{host}:{port}/{database}'


# from pyontutils.utils_fast import isoformat
def isoformat(datetime_instance, timespec='auto'):
    kwargs = {}
    if isinstance(datetime_instance, datetime):
        # don't pass timespec if type is not date not datetime
        kwargs['timespec'] = timespec

    return datetime_instance.isoformat(**kwargs).replace('.', ',').replace('+00:00', 'Z')
