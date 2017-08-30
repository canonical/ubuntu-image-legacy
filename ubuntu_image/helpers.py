"""Useful helper functions."""

import os
import re
import shutil
import logging

from contextlib import ExitStack, contextmanager
from parted import Device
from subprocess import PIPE, run as subprocess_run
from tempfile import NamedTemporaryFile, TemporaryDirectory


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
    ]


SPACE = ' '
_logger = logging.getLogger('ubuntu-image')


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


def as_size(size, min=0, max=None):
    mo = re.match('(\d+)([a-zA-Z]*)', size)
    if mo is None:
        raise ValueError(size)
    size_in_bytes = mo.group(1)
    value = {
        '': straight_up_bytes,
        'G': GiB,
        'M': MiB,
        }[mo.group(2)](int(size_in_bytes))
    if max is None:
        if value < min:
            raise ValueError('Value outside range: {} < {}'.format(value, min))
    elif not (min <= value < max):
        raise ValueError('Value outside range: {} <= {} < {}'.format(
            min, value, max))
    return value


def get_host_arch():
    proc = run('dpkg --print-architecture', check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def get_host_distro():
    proc = run('lsb_release -c -s', check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


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
        _logger.error('COMMAND FAILED: %s', command)
        if proc.stdout is not None:
            _logger.error(proc.stdout)
        if proc.stderr is not None:
            _logger.error(proc.stderr)
        proc.check_returncode()
    return proc


def snap(model_assertion, root_dir, channel=None, extra_snaps=None):
    snap_cmd = os.environ.get('UBUNTU_IMAGE_SNAP_CMD', 'snap')
    # Create a list of the command arguments to run.  We do it this way rather
    # than just .format() into a template string in order to have a more
    # predictable --and thus more testable-- command string.  Otherwise, we
    # might get spurious extra spaces in the command that is harder to predict.
    arg_list = [snap_cmd, 'prepare-image']
    if channel is not None:
        arg_list.append('--channel={}'.format(channel))
    # Fails if extra_snaps is None or the empty list.
    if extra_snaps:
        arg_list.append(SPACE.join('--extra-snaps={}'.format(extra)
                        for extra in extra_snaps))
    arg_list.extend([model_assertion, root_dir])
    cmd = SPACE.join(arg_list)
    run(cmd, stdout=None, stderr=None, env=os.environ)


def live_build(root_dir, env):
    # First, setup the build tools and workspace.
    config_dir = os.path.join(root_dir, 'auto')
    shutil.copytree('/usr/share/livecd-rootfs/live-build/auto', config_dir)

    # Change the current working directory
    old_working_dir = os.getcwd()
    os.chdir(root_dir)

    # Environment variables list
    env_list = ['%s=%s' % (key, value) for (key, value) in env.items()]

    config_cmd = ['sudo']
    config_cmd.extend(env_list)
    config_cmd.extend(['lb', 'config'])
    run(config_cmd, stdout=None, stderr=None, env=os.environ)

    build_cmd = ['sudo']
    build_cmd.extend(env_list)
    build_cmd.extend(['lb', 'build'])
    run(build_cmd, stdout=None, stderr=None, env=os.environ)

    # Back to previous working directory
    os.chdir(old_working_dir)


def fetch_bootloader_bits():
    apt_cmd = ['sudo', 'apt', 'install', 'shim-signed',
               'grub-pc-bin', 'grub-efi-amd64-signed']

    run(apt_cmd, stdout=None, stderr=None, env=os.environ)


def sparse_copy(src, dst, *, follow_symlinks=True):
    args = ['cp', '--sparse=always', src, dst]
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
    cmd = ('fakeroot-sysv mkfs.ext4 -L {} -O -metadata_csum -T default '
           '-O uninit_bg {} -d {}').format(label, img_file, contents_dir)
    proc = run(cmd, check=False)
    if proc.returncode == 0:
        # We have a new enough e2fsprogs, so we're done.
        return                                      # pragma: noxenial
    run('mkfs.ext4 -L {} -T default -O uninit_bg {}'.format(label, img_file))
    # Only do this if the directory is non-empty.
    if not os.listdir(contents_dir):
        return
    with mount(img_file) as mountpoint:
        # fixme: everything is terrible.
        run('sudo cp -dR --preserve=mode,timestamps {}/* {}'.format(
            contents_dir, mountpoint), shell=True)


def get_default_sector_size():
    with NamedTemporaryFile() as fp:
        # Truncate to zero, so that extending the size in the next call
        # will cause all the bytes to read as zero.  Stevens $4.13
        os.truncate(fp.name, 0)
        os.truncate(fp.name, MiB(1))
        return Device(fp.name).sectorSize
