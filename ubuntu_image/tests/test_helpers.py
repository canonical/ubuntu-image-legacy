"""Test the helpers."""

import os
import logging

from contextlib import ExitStack
from pkg_resources import resource_filename
from shutil import copytree
from subprocess import run as subprocess_run
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.helpers import (
    GiB, MiB, as_bool, as_size, mkfs_ext4, run, snap, sparse_copy, transform)
from ubuntu_image.testing.helpers import LogCapture
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


class MountMocker:
    def __init__(self, results_dir):
        self.mountpoint = None
        self.results_dir = results_dir

    def run(self, command, *args, **kws):
        if command.startswith('mkfs.ext4'):
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


class TestHelpers(TestCase):
    def test_m(self):
        self.assertEqual(as_size('25M'), MiB(25))

    def test_g(self):
        self.assertEqual(as_size('30G'), GiB(30))

    def test_bytes(self):
        self.assertEqual(as_size('801'), 801)

    def test_size_min_okay(self):
        self.assertEqual(as_size(5, min=4), 5)

    def test_size_value_less_than_min(self):
        self.assertRaises(ValueError, as_size, 3, min=4)

    def test_size_min_inclusive_okay(self):
        self.assertEqual(as_size(3, min=3), 3)

    def test_size_max_okay(self):
        self.assertEqual(as_size(5, max=8), 5)

    def test_size_value_greater_than_max(self):
        self.assertRaises(ValueError, as_size, 10, max=8)

    def test_size_max_exclusive(self):
        self.assertRaises(ValueError, as_size, 10, max=10)

    def test_size_min_max(self):
        self.assertEqual(as_size(5, min=4, max=8), 5)

    def test_size_min_max_outside_range(self):
        self.assertRaises(ValueError, as_size, 3, min=4, max=8)
        self.assertRaises(ValueError, as_size, 10, min=4, max=8)

    def test_transform(self):
        @transform(ZeroDivisionError, RuntimeError)
        def oops():
            1/0
        self.assertRaises(RuntimeError, oops)

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

    def test_sparse_copy(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            sparse_file = os.path.join(tmpdir, 'sparse.dat')
            fp = resources.enter_context(open(sparse_file, 'w'))
            os.truncate(fp.fileno(), 1000000)
            # This file is sparse.
            self.assertEqual(os.stat(sparse_file).st_blocks, 0)
            copied_file = os.path.join(tmpdir, 'copied.dat')
            sparse_copy(sparse_file, copied_file)
            self.assertEqual(os.stat(copied_file).st_blocks, 0)

    def test_copy_symlink(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            sparse_file = os.path.join(tmpdir, 'sparse.dat')
            fp = resources.enter_context(open(sparse_file, 'w'))
            os.truncate(fp.fileno(), 1000000)
            # This file is sparse.
            self.assertEqual(os.stat(sparse_file).st_blocks, 0)
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
            snap(model, tmpdir)
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
            snap(model, tmpdir, channel='edge')
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
            snap(model, tmpdir, extra_snaps=('foo', 'bar'))
            self.assertEqual(len(mock.call_args_list), 1)
            args, kws = mock.call_args_list[0]
        self.assertEqual(
            args[0],
            ['snap', 'prepare-image', '--extra-snaps=foo', '--extra-snaps=bar',
             model, tmpdir])

    def test_mkfs_ext4(self):
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
            mkfs_ext4(img_file, contents_dir)
            # Two files were put in the "mountpoint" directory, but because of
            # above, we have to check them in the results copy.
            with open(os.path.join(mock.results_dir, 'a.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(mock.results_dir, 'b.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'56789')

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
            mkfs_ext4(img_file, contents_dir)
            # Because there were no contents, the `sudo cp` was never called,
            # the mock's shutil.copytree() was also never called, therefore
            # the results_dir was never created.
            self.assertFalse(os.path.exists(results_dir))
