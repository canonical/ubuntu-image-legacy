"""Test main execution."""

import os
import logging

from contextlib import ExitStack
from io import StringIO
from tempfile import NamedTemporaryFile, TemporaryDirectory
from ubuntu_image.__main__ import main
from ubuntu_image.builder import ModelAssertionBuilder
from unittest import TestCase
from unittest.mock import call, patch


class CrashingModelAssertionBuilder(ModelAssertionBuilder):
    def make_temporary_directories(self):
        raise RuntimeError


class EarlyExitModelAssertionBuilder(ModelAssertionBuilder):
    def populate_rootfs_contents(self):
        # Do nothing, but let the state machine exit.
        pass


class DoNothingBuilder(ModelAssertionBuilder):
    def populate_rootfs_contents(self):
        self._next.append(self.calculate_rootfs_size)

    def populate_bootfs_contents(self):
        self._next.append(self.calculate_bootfs_size)


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

    def test_output(self):
        with ExitStack() as resources:
            resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                DoNothingBuilder))
            fp = resources.enter_context(NamedTemporaryFile(
                mode='w', encoding='utf-8'))
            # There is trailing whitespace in this text and it is significant!
            # We do a bogus interpolation to appease pyflakes.
            print("""\
type: model
series: 16
authority-id: my-brand
brand-id: my-brand
model: canonical-pc-amd64
class: general
allowed-modes: classic, developer
required-snaps: {}
architecture: amd64
store: canonical
gadget: canonical-pc
kernel: canonical-pc-linux
core: ubuntu-core
timestamp: 2016-01-02T10:00:00-05:00
body-length: 0

openpgpg 2cln""".format(''), file=fp)
            fp.flush()
            tmpdir = resources.enter_context(TemporaryDirectory())
            imgfile = os.path.join(tmpdir, 'my-disk.img')
            self.assertFalse(os.path.exists(imgfile))
            main(('--output', imgfile, fp.name))
            self.assertTrue(os.path.exists(imgfile))
