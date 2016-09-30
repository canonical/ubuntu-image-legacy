"""Test the helpers."""

import os

from contextlib import ExitStack
from io import StringIO
from pkg_resources import resource_filename
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import (
    GiB, MiB, as_bool, as_size, run, snap, sparse_copy, transform)
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


class TestHelpers(TestCase):
    def test_m(self):
        self.assertEqual(as_size('25M'), MiB(25))

    def test_g(self):
        self.assertEqual(as_size('30G'), GiB(30))

    def test_bytes(self):
        self.assertEqual(as_size('801'), 801)

    def test_transform(self):
        @transform(ZeroDivisionError, RuntimeError)
        def oops():
            1/0
        self.assertRaises(RuntimeError, oops)

    def test_run(self):
        stderr = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.helpers.sys.__stderr__', stderr))
            resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            run('/bin/false')
        # stdout gets piped to stderr.
        self.assertEqual(stderr.getvalue(),
                         'COMMAND FAILED: /bin/falsefake stdoutfake stderr')

    def test_run_fails_no_output(self):
        stderr = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.helpers.sys.__stderr__', stderr))
            resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProcNoOutput()))
            run('/bin/false')
        # stdout gets piped to stderr.
        self.assertEqual(stderr.getvalue(), 'COMMAND FAILED: /bin/false')

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
        stderr = StringIO()
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.helpers.sys.__stderr__', stderr))
            mock = resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            tmpdir = resources.enter_context(TemporaryDirectory())
            snap(model, tmpdir)
            self.assertEqual(len(mock.call_args_list), 1)
            args, kws = mock.call_args_list[0]
        self.assertEqual(args[0], ['snap', 'prepare-image', model, tmpdir])

    def test_snap_with_channel(self):
        stderr = StringIO()
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.helpers.sys.__stderr__', stderr))
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
        stderr = StringIO()
        model = resource_filename('ubuntu_image.tests.data', 'model.assertion')
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.helpers.sys.__stderr__', stderr))
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
