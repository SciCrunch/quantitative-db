class QuantdbError(Exception):
    """base"""


class UnknownArg(QuantdbError):
    """url query parameter unknown"""


class ArgMissingValue(QuantdbError):
    """url query parameter contained no value"""


class BadValue(QuantdbError):
    """url query parameter contained a malformed value"""
