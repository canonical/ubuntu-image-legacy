"""Useful helper functions."""

import re
import sys

from subprocess import PIPE, run as subprocess_run


__all__ = [
    'GiB',
    'MiB',
    'as_bool',
    'as_size',
    'run',
    'snap',
    'transform',
    ]


def GiB(count):
    return count * 2**30


def MiB(count):
    return count * 2**20


def as_bool(value):
    if value.lower() in {
            'no',
            'false',
            '0',
            'disable',
            'disabled',
            }:
        return False
    if value.lower() in {
            'yes',
            'true',
            '1',
            'enable',
            'enabled',
            }:
        return True
    raise ValueError(value)


def straight_up_bytes(count):
    return count


def as_size(size):
    # Check for int-ness and just return what you get if so.  YAML parsers
    # will turn values like '108' into ints automatically, but voluptuous will
    # always try to coerce the value to an as_size.
    if isinstance(size, int):
        return size
    mo = re.match('(\d+)([a-zA-Z]*)', size)
    if mo is None:
        raise ValueError(size)
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
    runnable_command = (
        command.split() if 'shell' not in args
        else command)
    proc = subprocess_run(
        runnable_command,
        stdout=PIPE, stderr=PIPE,
        universal_newlines=True,
        **args)
    if check and proc.returncode != 0:
        sys.stderr.write('COMMAND FAILED: {}'.format(command))
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        proc.check_returncode()
    return proc


def snap(model_assertion, root_dir, channel=None):   # pragma: notravis
    raw_cmd = 'snap prepare-image {} {} {}'
    cmd = raw_cmd.format(
        '' if channel is None else '--channel={}'.format(channel),
        model_assertion,
        root_dir)
    # This environment variable is a temporary workaround to prevent `snap
    # prepare-image` from failing with an unverified signature on the
    # model.assertion.  We obviously can't sign it with the real root keys,
    # and there's no other way to inject testing data.
    #
    # $PATH is needed because without it `snap prepare-image` can't find
    # /usr/bin/squashfs.  This is currently unexplained.
    env = dict(UBUNTU_IMAGE_SKIP_COPY_UNVERIFIED_MODEL='1',
               PATH='/usr/bin')
    run(cmd, env=env)
