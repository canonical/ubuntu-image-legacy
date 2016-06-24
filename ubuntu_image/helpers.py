"""Useful helper functions."""

import re


__all__ = [
    'GiB',
    'MiB',
    'as_size',
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
