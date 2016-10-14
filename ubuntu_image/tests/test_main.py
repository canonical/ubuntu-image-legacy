"""Test main execution."""

import os
import logging

from contextlib import ExitStack
from io import StringIO
from pickle import load
from pkg_resources import resource_filename
from tempfile import TemporaryDirectory
from ubuntu_image.__main__ import main, parseargs
from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.testing.helpers import (
    CrashingModelAssertionBuilder, DoNothingBuilder,
    EarlyExitLeaveATraceAssertionBuilder, EarlyExitModelAssertionBuilder,
    XXXModelAssertionBuilder)
from unittest import TestCase, skipIf
from unittest.mock import call, patch


class TestParseArgs(TestCase):
    def test_image_size_option_bytes(self):
        args = parseargs(['--image-size', '45', 'model.assertion'])
        self.assertEqual(args.image_size, 45)
        self.assertEqual(args.given_image_size, '45')

    def test_image_size_option_suffixes(self):
        args = parseargs(['--image-size', '45G', 'model.assertion'])
        self.assertEqual(args.image_size, GiB(45))
        self.assertEqual(args.given_image_size, '45G')
        args = parseargs(['--image-size', '45M', 'model.assertion'])
        self.assertEqual(args.image_size, MiB(45))
        self.assertEqual(args.given_image_size, '45M')

    def test_image_size_option_invalid(self):
        # These errors will output to stderr, but that just clouds the test
        # output, so suppress it.
        with patch('argparse._sys.stderr'):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['--image-size', '45Q', 'model.assertion'])
            self.assertRaises(SystemExit,
                              parseargs,
                              ['--image-size', 'BIG', 'model.assertion'])


class TestMain(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Capture builtin print() output.
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._resources.enter_context(
            patch('argparse._sys.stdout', self._stdout))
        # Capture stderr since this is where argparse will spew to.
        self._resources.enter_context(
            patch('argparse._sys.stderr', self._stderr))

    def test_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--help',))
        self.assertEqual(cm.exception.code, 0)
        lines = self._stdout.getvalue().splitlines()
        self.assertTrue(lines[0].startswith('usage: ubuntu-image'),
                        lines[0])

    def test_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                EarlyExitModelAssertionBuilder))
            # Prevent actual main() from running.
            resources.enter_context(patch('ubuntu_image.__main__.main'))
            code = main(('--debug', 'model.assertion'))
        self.assertEqual(code, 0)
        mock.assert_called_once_with(level=logging.DEBUG)

    def test_no_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                EarlyExitModelAssertionBuilder))
            # Prevent actual main() from running.
            resources.enter_context(patch('ubuntu_image.__main__.main'))
            code = main(('model.assertion',))
        self.assertEqual(code, 0)
        mock.assert_not_called()

    def test_state_machine_exception(self):
        with ExitStack() as resources:
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                CrashingModelAssertionBuilder))
            mock = resources.enter_context(patch(
                'ubuntu_image.__main__._logger.exception'))
            code = main(('model.assertion',))
            self.assertEqual(code, 1)
            self.assertEqual(
                mock.call_args_list[-1], call('Crash in state machine'))


class TestMainWithModel(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Capture builtin print() output.
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._resources.enter_context(
            patch('argparse._sys.stdout', self._stdout))
        # Capture stderr since this is where argparse will spew to.
        self._resources.enter_context(
            patch('argparse._sys.stderr', self._stderr))
        # Set up a few other useful things for these tests.
        self._resources.enter_context(
            patch('ubuntu_image.__main__.logging.basicConfig'))
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')

    def test_output(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(tmpdir, 'my-disk.img')
        self.assertFalse(os.path.exists(imgfile))
        main(('--output', imgfile, self.model_assertion))
        self.assertTrue(os.path.exists(imgfile))

    def test_resume_and_model_assertion(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--resume', self.model_assertion))
        self.assertEqual(cm.exception.code, 2)

    def test_no_resume_and_no_model_assertion(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--until', 'whatever'))
        self.assertEqual(cm.exception.code, 2)

    def test_resume_without_workdir(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--resume',))
        self.assertEqual(cm.exception.code, 2)

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_save_resume(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            XXXModelAssertionBuilder))
        workdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(workdir, 'my-disk.img')
        main(('--until', 'prepare_filesystems',
              '--channel', 'edge',
              '--workdir', workdir,
              '--output', imgfile,
              self.model_assertion))
        self.assertTrue(os.path.exists(os.path.join(
            workdir, '.ubuntu-image.pck')))
        self.assertFalse(os.path.exists(imgfile))
        main(('--resume', '--workdir', workdir))
        self.assertTrue(os.path.exists(imgfile))

    def test_until(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        main(('--until', 'populate_rootfs_contents',
              '--channel', 'edge',
              '--workdir', workdir,
              self.model_assertion))
        # The pickle file will tell us how far the state machine got.
        with open(os.path.join(workdir, '.ubuntu-image.pck'), 'rb') as fp:
            pickle_state = load(fp).__getstate__()
        # This is the *next* state to execute.
        self.assertEqual(pickle_state['state'], ['populate_rootfs_contents'])

    def test_thru(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        main(('--thru', 'populate_rootfs_contents',
              '--channel', 'edge',
              '--workdir', workdir,
              self.model_assertion))
        # The pickle file will tell us how far the state machine got.
        with open(os.path.join(workdir, '.ubuntu-image.pck'), 'rb') as fp:
            pickle_state = load(fp).__getstate__()
        # This is the *next* state to execute.
        self.assertEqual(pickle_state['state'], ['calculate_rootfs_size'])

    def test_resume_loads_pickle(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            EarlyExitLeaveATraceAssertionBuilder))
        main(('--until', 'prepare_image',
              '--workdir', workdir,
              self.model_assertion))
        self.assertFalse(os.path.exists(os.path.join(workdir, 'success')))
        main(('--workdir', workdir, '--resume'))
        self.assertTrue(os.path.exists(os.path.join(workdir, 'success')))
