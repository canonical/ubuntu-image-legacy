"""Useful helper functions."""

import re
import sys

from subprocess import PIPE, run as subprocess_run


__all__ = [
    'GiB',
    'MiB',
    'as_size',
    'run',
    'transform',
    ]


def GiB(count):
    return count * 2**30


def MiB(count):
    return count * 2**20


def straight_up_bytes(count):
    return count


def as_size(size):
    mo = re.match('(\d+)([a-zA-Z]*)', size)
    assert mo is not None, 'Invalid size: {}'.format(size)
    size_in_bytes = mo.group(1)
    return {
        '': straight_up_bytes,
        'G': GiB,
        'M': MiB,
        }[mo.group(2)](int(size_in_bytes))


def transform(caught_excs, new_exc):
    """Transform any caught exceptions into a new exception.

    This is a decorator which runs the decorated function, catching all
    specified exceptions.  If one of those exceptions occurs, it is
    transformed (i.e. re-raised) into a new exception.  The original exception
    is retained via exception chaining.

    :param caught_excs: The exception or exceptions to catch.
    :type caught_excs: A single exception, or a tuple of exceptions.
    :param new_exc: The new exception to re-raise.
    :type new_exc: An exception.
    """
    def outer(func):
        def inner(*args, **kws):
            try:
                return func(*args, **kws)
            except caught_excs as exception:
                raise new_exc from exception
        return inner
    return outer


def run(command, *, check=True, **args):
    if 'shell' not in args:
        command = command.split()
    proc = subprocess_run(
        command,
        stdout=PIPE, stderr=PIPE,
        universal_newlines=True,
        **args)
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        proc.check_returncode()
    return proc
