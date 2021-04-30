"""Test the helpers."""

import os
import re
import json
import errno
import logging

from collections import OrderedDict
from contextlib import ExitStack
from pkg_resources import resource_filename
from shutil import copytree
from subprocess import DEVNULL, run as subprocess_run
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.helpers import (
     DependencyError, GiB, MiB, PrivilegeError, as_bool, as_size,
     check_root_privilege, get_host_arch, get_host_distro,
     get_qemu_static_for_arch, live_build,
     mkfs_ext4, run, snap, sparse_copy, unsparse_swapfile_ext4)
from ubuntu_image.testing.helpers import (
     LiveBuildMocker, LogCapture, envar)
from unittest import TestCase
from unittest.mock import patch


class FakeProc:
    returncode = 1
    stdout = 'fake stdout'
    stderr = 'fake stderr'

    def check_returncode(self):
        pass


class FakeProcNoOutput:
    returncode = 1
    stdout = None
    stderr = None

    def check_returncode(self):
        pass


def is_sparse(path):
    # LP: #1656371 - Looking at stat().st_blocks won't work on ZFS file
    # systems, since that seems to return 1, whereas on EXT4 it returns 0.
    # Rather than hard code the value based on file system type (which could
    # be different even on other file systems), a more reliable way seems to
    # be to use SEEK_DATA with an offset of 0 to find the first block of data
    # after position 0.  If there is no data, an ENXIO will get raised, at
    # least on any modern Linux kernels we care about.  See lseek(2) for
    # details.
    with open(path, 'r') as fp:
        try:
            os.lseek(fp.fileno(), 0, os.SEEK_DATA)
        except OSError as error:
            # There is no OSError subclass for ENXIO.
            if error.errno != errno.ENXIO:
                raise
            # The expected exception occurred, meaning, there is no data in
            # the file, so it's entirely sparse.
            return True
    # The expected exception did not occur, so there is data in the file.
    return False


class MountMocker:
    def __init__(self, results_dir, contents_dir=None):
        self.mountpoint = None
        self.results_dir = results_dir
        self.preserves_ownership = False
        self.contents_dir = contents_dir
        self.dd_called = False

    def run(self, command, *args, **kws):
        if 'mkfs.ext4' in command:
            if '-d' in command.split():
                # Simulate a failing call on <= Ubuntu 16.04 where mkfs.ext4
                # doesn't yet support the -d optio.n
                return SimpleNamespace(returncode=1)
            # Otherwise, pretend to have created an ext4 file system.
            pass
        elif command.startswith('sudo mount'):
            # We don't want to require sudo for the test suite, so let's not
            # actually do the mount.  Instead, just record the mount point,
            # which will be a temporary directory, so that we can verify its
            # contents later.
            self.mountpoint = command.split()[-1]
            if self.contents_dir:
                subprocess_run('cp {}/* {}'.format(
                    self.contents_dir, self.mountpoint), shell=True,
                    stdout=DEVNULL, stderr=DEVNULL)
        elif command.startswith('sudo umount'):
            # Just ignore the umount command since we never mounted anything,
            # and it's a temporary directory anyway.
            pass
        elif command.startswith('sudo cp'):
            # Pass this command upward, but without the sudo.
            subprocess_run(command[5:], *args, **kws)
            # Now, because mount() called from mkfs_ext4() will cull its own
            # temporary directory, and that tempdir is the mountpoint captured
            # above, copy the entire contents of the mount point directory to
            # a results tempdir that we can check below for a passing grade.
            copytree(self.mountpoint, self.results_dir)
            # We also want to somehow test if, when requested, the cp call has
            # the --preserve=ownership flag present.  There's no other nice
            # way of mocking this as everything else would require root.
            if re.search(r'--preserve=[^ ]*ownership', command):
                self.preserves_ownership = True
        elif command.startswith('dd'):
            # dd is a safe command so we should just run it.
            subprocess_run(command, shell=True, stdout=DEVNULL, stderr=DEVNULL)
            self.dd_called = True


class TestHelpers(TestCase):
    def test_m(self):
        self.assertEqual(as_size('25M'), MiB(25))

    def test_g(self):
        self.assertEqual(as_size('30G'), GiB(30))

    def test_bytes(self):
        self.assertEqual(as_size('801'), 801)

    def test_size_min_okay(self):
        self.assertEqual(as_size('5', min=4), 5)

    def test_size_value_less_than_min(self):
        self.assertRaises(ValueError, as_size, '3', min=4)

    def test_size_min_inclusive_okay(self):
        self.assertEqual(as_size('3', min=3), 3)

    def test_size_max_okay(self):
        self.assertEqual(as_size('5', max=8), 5)

    def test_size_value_greater_than_max(self):
        self.assertRaises(ValueError, as_size, '10', max=8)

    def test_size_max_exclusive(self):
        self.assertRaises(ValueError, as_size, '10', max=10)

    def test_size_min_max(self):
        self.assertEqual(as_size('5', min=4, max=8), 5)

    def test_size_min_max_outside_range(self):
        self.assertRaises(ValueError, as_size, '3', min=4, max=8)
        self.assertRaises(ValueError, as_size, '10', min=4, max=8)

    def test_run(self):
        with ExitStack() as resources:
            log = resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            run('/bin/false')
            self.assertEqual(log.logs, [
                (logging.ERROR, 'COMMAND FAILED: /bin/false'),
                (logging.ERROR, 'fake stdout'),
                (logging.ERROR, 'fake stderr'),
                ])

    def test_run_fails_no_output(self):
        with ExitStack() as resources:
            log = resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProcNoOutput()))
            run('/bin/false')
            self.assertEqual(log.logs, [
                (logging.ERROR, 'COMMAND FAILED: /bin/false'),
                ])

    def test_as_bool(self):
        for value in {'no', 'False', '0', 'DISABLE', 'DiSaBlEd'}:
            self.assertFalse(as_bool(value), value)
        for value in {'YES', 'tRUE', '1', 'eNaBlE', 'enabled'}:
            self.assertTrue(as_bool(value), value)
        self.assertRaises(ValueError, as_bool, 'anything else')

    def test_get_host_arch(self):
        self.assertIsNotNone(get_host_arch())

    def test_get_host_distro(self):
        self.assertIsNotNone(get_host_distro())

    def test_get_qemu_static_for_arch(self):
        executables = {
            'armhf': 'qemu-arm-static',
            'arm64': 'qemu-aarch64-static',
            'ppc64el': 'qemu-ppc64le-static',
            'i386': 'qemu-i386-static',
            'foo': 'qemu-foo-static',
            }
        for arch, static in executables.items():
            self.assertEqual(get_qemu_static_for_arch(arch), static)

    def test_sparse_copy(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            sparse_file = os.path.join(tmpdir, 'sparse.dat')
            fp = resources.enter_context(open(sparse_file, 'w'))
            os.truncate(fp.fileno(), 1000000)
            # This file is sparse.
            self.assertTrue(is_sparse(sparse_file))
            copied_file = os.path.join(tmpdir, 'copied.dat')
            sparse_copy(sparse_file, copied_file)
            self.assertTrue(is_sparse(copied_file))

    def test_copy_symlink(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            sparse_file = os.path.join(tmpdir, 'sparse.dat')
            fp = resources.enter_context(open(sparse_file, 'w'))
            os.truncate(fp.fileno(), 1000000)
            # This file is sparse.
            self.assertTrue(is_sparse(sparse_file))
            # Create a symlink to the sparse file.
            linked_file = os.path.join(tmpdir, 'linked.dat')
            os.symlink(sparse_file, linked_file)
            self.assertTrue(os.path.islink(linked_file))
            copied_link = os.path.join(tmpdir, 'copied.dat')
            sparse_copy(linked_file, copied_link, follow_symlinks=False)
            self.assertTrue(os.path.islink(copied_link))

    def test_snap(self):
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(LogCapture())
            mock = resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            tmpdir = resources.enter_context(TemporaryDirectory())
            tmpworkdir = resources.enter_context(TemporaryDirectory())
            snap(model, tmpdir, tmpworkdir)
            self.assertEqual(len(mock.call_args_list), 1)
            args, kws = mock.call_args_list[0]
        self.assertEqual(args[0], ['snap', 'prepare-image', model, tmpdir])

    def test_snap_with_channel(self):
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(LogCapture())
            mock = resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            tmpdir = resources.enter_context(TemporaryDirectory())
            tmpworkdir = resources.enter_context(TemporaryDirectory())
            snap(model, tmpdir, tmpworkdir, channel='edge')
            self.assertEqual(len(mock.call_args_list), 1)
            args, kws = mock.call_args_list[0]
        self.assertEqual(
            args[0],
            ['snap', 'prepare-image', '--channel=edge', model, tmpdir])

    def test_snap_with_extra_snaps(self):
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(LogCapture())
            mock = resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            tmpdir = resources.enter_context(TemporaryDirectory())
            tmpworkdir = resources.enter_context(TemporaryDirectory())
            snap(model, tmpdir, tmpworkdir,
                 extra_snaps=('foo', 'bar=edge', 'baz=18/beta'))
            self.assertEqual(len(mock.call_args_list), 1)
            args, kws = mock.call_args_list[0]
        self.assertEqual(
            args[0],
            ['snap', 'prepare-image',
             '--snap=foo', '--snap=bar=edge', '--snap=baz=18/beta',
             model, tmpdir])

    def test_snap_with_customization(self):
        # Test all combinations of possible image customization.
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        test_cases = (
            # --cloud-init=XXX
            ({'cloud_init': '/foo/bar/user-data'},
             {'cloud-init-user-data': '/foo/bar/user-data'}),
            # --disable-console-conf
            ({'disable_console_conf': True},
             {'console-conf': 'disabled'}),
            # --cloud-init=XXX --disable-console-conf
            ({'cloud_init': '/foo/bar/user-data',
              'disable_console_conf': True},
             {'cloud-init-user-data': '/foo/bar/user-data',
              'console-conf': 'disabled'}),
        )
        for kwargs, result in test_cases:
            with ExitStack() as resources:
                resources.enter_context(LogCapture())
                mock = resources.enter_context(
                    patch('ubuntu_image.helpers.subprocess_run',
                          return_value=FakeProc()))
                tmpdir = resources.enter_context(TemporaryDirectory())
                tmpworkdir = resources.enter_context(TemporaryDirectory())
                snap(model, tmpdir, tmpworkdir,
                     **kwargs)
                self.assertEqual(len(mock.call_args_list), 1)
                customize_path = os.path.join(tmpworkdir, 'customization')
                self.assertTrue(os.path.exists(customize_path))
                with open(customize_path) as fp:
                    self.assertDictEqual(
                        json.load(fp),
                        result)
                args, kws = mock.call_args_list[0]
            self.assertEqual(
                args[0],
                ['snap', 'prepare-image',
                 '--customize={}'.format(customize_path),
                 model, tmpdir])

    def test_live_build(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'amd64'
            live_build(root_dir, env)
            self.assertEqual(len(mock.call_args_list), 3)
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=amd64',
                 'lb', 'config'])
            self.assertEqual(
                mock.call_args_list[2],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=amd64',
                 'lb', 'build'])

    def test_live_build_with_full_args(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-cpc'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'amd64'
            env['SUBPROJECT'] = 'live'
            env['SUBARCH'] = 'ubuntu-cpc'
            env['PROPOSED'] = 'true'
            env['IMAGEFORMAT'] = 'ext4'
            env['EXTRA_PPAS'] = 'foo1/bar1 foo2'
            live_build(root_dir, env)
            self.assertEqual(len(mock.call_args_list), 3)
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-cpc', 'SUITE=xenial', 'ARCH=amd64',
                 'SUBPROJECT=live', 'SUBARCH=ubuntu-cpc', 'PROPOSED=true',
                 'IMAGEFORMAT=ext4', 'EXTRA_PPAS=foo1/bar1 foo2',
                 'lb', 'config'])
            self.assertEqual(
                mock.call_args_list[2],
                ['sudo',
                 'PROJECT=ubuntu-cpc', 'SUITE=xenial', 'ARCH=amd64',
                 'SUBPROJECT=live', 'SUBARCH=ubuntu-cpc', 'PROPOSED=true',
                 'IMAGEFORMAT=ext4', 'EXTRA_PPAS=foo1/bar1 foo2',
                 'lb', 'build'])

    def test_live_build_env_livecd(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            auto_dir = os.path.join(tmpdir, 'auto')
            os.mkdir(auto_dir)
            with open(os.path.join(auto_dir, 'config'), 'w') as fp:
                fp.write('DUMMY')
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            resources.enter_context(
                envar('UBUNTU_IMAGE_LIVECD_ROOTFS_AUTO_PATH', auto_dir))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'amd64'
            live_build(root_dir, env)
            # Make sure that we had no dpkg -L call made.
            self.assertEqual(len(mock.call_args_list), 2)
            self.assertEqual(
                mock.call_args_list[0],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=amd64',
                 'lb', 'config'])
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=amd64',
                 'lb', 'build'])
            config_path = os.path.join(root_dir, 'auto', 'config')
            self.assertTrue(os.path.exists(config_path))
            with open(os.path.join(config_path), 'r') as fp:
                self.assertEqual(fp.read(), 'DUMMY')

    def test_live_build_cross_build(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            resources.enter_context(
                patch('ubuntu_image.helpers.find_executable',
                      return_value='/usr/bin/qemu-arm-static-fake'))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'armhf'
            live_build(root_dir, env)
            self.assertEqual(len(mock.call_args_list), 3)
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=armhf',
                 'lb', 'config',
                 '--bootstrap-qemu-arch', 'armhf',
                 '--bootstrap-qemu-static', '/usr/bin/qemu-arm-static-fake',
                 '--architectures', 'armhf'])
            self.assertEqual(
                mock.call_args_list[2],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=armhf',
                 'lb', 'build'])

    def test_live_build_cross_build_env_path(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            resources.enter_context(
                patch('ubuntu_image.helpers.find_executable',
                      return_value='/usr/bin/qemu-arm-static'))
            resources.enter_context(
                envar('UBUNTU_IMAGE_QEMU_USER_STATIC_PATH',
                      '/opt/qemu-arm-static'))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'armhf'
            live_build(root_dir, env)
            self.assertEqual(len(mock.call_args_list), 3)
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=armhf',
                 'lb', 'config',
                 '--bootstrap-qemu-arch', 'armhf',
                 '--bootstrap-qemu-static', '/opt/qemu-arm-static',
                 '--architectures', 'armhf'])
            self.assertEqual(
                mock.call_args_list[2],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=armhf',
                 'lb', 'build'])

    def test_live_build_cross_build_no_static(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            resources.enter_context(
                patch('ubuntu_image.helpers.find_executable',
                      return_value=None))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'armhf'
            with self.assertRaises(DependencyError) as cm:
                live_build(root_dir, env)
            self.assertEqual(len(mock.call_args_list), 1)
            self.assertEqual(
                cm.exception.name, 'qemu-arm-static')

    def test_live_build_no_cross_build(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            root_dir = os.path.join(tmpdir, 'root_dir')
            mock = LiveBuildMocker(root_dir)
            resources.enter_context(LogCapture())
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            resources.enter_context(
                patch('ubuntu_image.helpers.get_host_arch',
                      return_value='amd64'))
            resources.enter_context(
                patch('ubuntu_image.helpers.find_executable',
                      return_value='/usr/bin/qemu-arm-static'))
            env = OrderedDict()
            env['PROJECT'] = 'ubuntu-server'
            env['SUITE'] = 'xenial'
            env['ARCH'] = 'armhf'
            live_build(root_dir, env, enable_cross_build=False)
            # Make sure that if we explicity disable cross-building, no
            # cross-build arguments are passed to lb config
            self.assertEqual(len(mock.call_args_list), 3)
            self.assertEqual(
                mock.call_args_list[1],
                ['sudo',
                 'PROJECT=ubuntu-server', 'SUITE=xenial', 'ARCH=armhf',
                 'lb', 'config'])

    def aux_test_mkfs_ext4(self, cmd):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            results_dir = os.path.join(tmpdir, 'results')
            mock = MountMocker(results_dir)
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            # Create a temporary directory and populate it with some stuff.
            contents_dir = resources.enter_context(TemporaryDirectory())
            with open(os.path.join(contents_dir, 'a.dat'), 'wb') as fp:
                fp.write(b'01234')
            with open(os.path.join(contents_dir, 'b.dat'), 'wb') as fp:
                fp.write(b'56789')
            # And a fake image file.
            img_file = resources.enter_context(NamedTemporaryFile())
            mkfs_ext4(img_file, contents_dir, cmd)
            # Two files were put in the "mountpoint" directory, but because of
            # above, we have to check them in the results copy.
            with open(os.path.join(mock.results_dir, 'a.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(mock.results_dir, 'b.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'56789')

    def test_mkfs_ext4_snap(self):
        self.aux_test_mkfs_ext4('snap')

    def test_mkfs_ext4_classic(self):
        self.aux_test_mkfs_ext4('classic')

    def test_mkfs_ext4_no_contents(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            results_dir = os.path.join(tmpdir, 'results')
            mock = MountMocker(results_dir)
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            # Create a temporary directory, but this time without contents.
            contents_dir = resources.enter_context(TemporaryDirectory())
            # And a fake image file.
            img_file = resources.enter_context(NamedTemporaryFile())
            mkfs_ext4(img_file, contents_dir, 'snap')
            # Because there were no contents, the `sudo cp` was never called,
            # the mock's shutil.copytree() was also never called, therefore
            # the results_dir was never created.
            self.assertFalse(os.path.exists(results_dir))

    def test_mkfs_ext4_preserve_ownership(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            results_dir = os.path.join(tmpdir, 'results')
            mock = MountMocker(results_dir)
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            # Create a temporary directory and populate it with some stuff.
            contents_dir = resources.enter_context(TemporaryDirectory())
            with open(os.path.join(contents_dir, 'a.dat'), 'wb') as fp:
                fp.write(b'01234')
            # And a fake image file.
            img_file = resources.enter_context(NamedTemporaryFile())
            mkfs_ext4(img_file, contents_dir, 'snap', preserve_ownership=True)
            with open(os.path.join(mock.results_dir, 'a.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            self.assertTrue(mock.preserves_ownership)

    def test_check_root_privilege(self):
        with ExitStack() as resources:
            mock_geteuid = resources.enter_context(
                patch('os.geteuid', return_value=0))
            resources.enter_context(
                patch('pwd.getpwuid', return_value=['test']))
            check_root_privilege()
            mock_geteuid.assert_called_with()

    def test_check_root_privilege_non_root(self):
        with ExitStack() as resources:
            mock_geteuid = resources.enter_context(
                patch('os.geteuid', return_value=1))
            resources.enter_context(
                patch('pwd.getpwuid', return_value=['test']))
            with self.assertRaises(PrivilegeError) as cm:
                check_root_privilege()
            mock_geteuid.assert_called_with()
            self.assertEqual(
                cm.exception.user_name, 'test')

    def test_unsparse_swapfile_ext4(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            results_dir = os.path.join(tmpdir, 'results')
            os.makedirs(results_dir)
            # Empty swapfile.
            swapfile = os.path.join(results_dir, 'swapfile')
            run('dd if=/dev/zero of={} bs=10M count=1'.format(swapfile),
                stdout=DEVNULL, stderr=DEVNULL)
            # Image file.
            img_file = resources.enter_context(NamedTemporaryFile())
            mock = MountMocker(results_dir, results_dir)
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            # Now the actual test.
            unsparse_swapfile_ext4(img_file)
            self.assertTrue(mock.dd_called)

    def test_unsparse_swapfile_ext4_no_swap(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            results_dir = os.path.join(tmpdir, 'results')
            os.makedirs(results_dir)
            # No swapfile, just some file.
            open(os.path.join(results_dir, 'foobar'), 'w')
            # Image file.
            img_file = resources.enter_context(NamedTemporaryFile())
            mock = MountMocker(results_dir, results_dir)
            resources.enter_context(
                patch('ubuntu_image.helpers.run', mock.run))
            # Now the actual test.
            unsparse_swapfile_ext4(img_file)
            self.assertFalse(mock.dd_called)
