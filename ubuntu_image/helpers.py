"""Useful helper functions."""

import os
import re
import sys

from contextlib import ExitStack, contextmanager
from subprocess import PIPE, run as subprocess_run
from tempfile import TemporaryDirectory


__all__ = [
    'GiB',
    'MiB',
    'SPACE',
    'as_bool',
    'as_size',
    'mkfs_ext4',
    'run',
    'snap',
    'sparse_copy',
    'transform',
    ]


SPACE = ' '


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
        command.split() if isinstance(command, str) and 'shell' not in args
        else command)
    stdout = args.pop('stdout', PIPE)
    stderr = args.pop('stderr', PIPE)
    proc = subprocess_run(
        runnable_command,
        stdout=stdout, stderr=stderr,
        universal_newlines=True,
        **args)
    if check and proc.returncode != 0:
        sys.__stderr__.write('COMMAND FAILED: {}\n'.format(command))
        # Use the real stdout and stderr; the obvious attributes might be
        # mocked out.
        if proc.stdout is not None:
            sys.__stderr__.write(proc.stdout)
        if proc.stderr is not None:
            sys.__stderr__.write(proc.stderr)
        proc.check_returncode()
    return proc


def snap(model_assertion, root_dir, channel=None, extra_snaps=None):
    snap_cmd = os.environ.get('UBUNTU_IMAGE_SNAP_CMD', 'snap')
    raw_cmd = '{} prepare-image {} {} {} {}'
    cmd = raw_cmd.format(
        snap_cmd,
        ('' if channel is None else '--channel={}'.format(channel)),
        ('' if extra_snaps is None
         else SPACE.join('--extra-snaps={}'.format(extra)
                         for extra in extra_snaps)),
        model_assertion,
        root_dir)
    run(cmd, stdout=None, stderr=None, env=os.environ)


def sparse_copy(src, dst, *, follow_symlinks=True):
    args = ['cp', '-p', '--sparse=always', src, dst]
    if not follow_symlinks:
        args.append('-P')
    run(args)


@contextmanager
def mount(img):
    with ExitStack() as resources:
        tmpdir = resources.enter_context(TemporaryDirectory())
        mountpoint = os.path.join(tmpdir, 'root-mount')
        os.makedirs(mountpoint)
        run('sudo mount -oloop {} {}'.format(img, mountpoint))
        resources.callback(run, 'sudo umount {}'.format(mountpoint))
        yield mountpoint


def mkfs_ext4(img_file, contents_dir, label='writable'):
    """Encapsulate the `mkfs.ext4` invocation.

    As of e2fsprogs 1.43.1, mkfs.ext4 supports a -d option which allows
    you to populate the ext4 partition at creation time, with the
    contents of an existing directory.  Unfortunately, we're targeting
    Ubuntu 16.04, which has e2fsprogs 1.42.X without the -d flag.  In
    that case, we have to sudo loop mount the ext4 file system and
    populate it that way.  Which sucks because sudo.
    """
    cmd = ('mkfs.ext4 -L {} -O -metadata_csum -T default -O uninit_bg {} '
           '-d {}').format(label, img_file, contents_dir)
    proc = run(cmd, check=False)
    if proc.returncode == 0:
        # We have a new enough e2fsprogs, so we're done.
        return
    run('mkfs.ext4 -L {} -T default -O uninit_bg {}'.format(label, img_file))
    # Only do this if the directory is non-empty.
    if not os.listdir(contents_dir):
        return
    with mount(img_file) as mountpoint:
        # fixme: everything is terrible.
        run('sudo cp -dR --preserve=mode,timestamps {}/* {}'.format(
            contents_dir, mountpoint), shell=True)
