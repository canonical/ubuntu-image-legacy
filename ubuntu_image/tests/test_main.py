"""Test main execution."""

import os
import logging

from contextlib import ExitStack
from io import StringIO
from tempfile import TemporaryDirectory
from ubuntu_image.__main__ import main
from unittest import TestCase, skip
from unittest.mock import patch


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
        self.assertTrue(lines[0].startswith('usage: ubuntu-image'))

    @skip("Re-enable this when 'ubuntu-image build' is added again")
    def test_require_model(self):
        # A non-zero exit occurs and an error message is printed if no model
        # positional argument is given.
        with self.assertRaises(SystemExit) as cm:
            main(())
        self.assertEqual(cm.exception.code, 2)
        lines = self._stderr.getvalue().splitlines()
        self.assertEqual(
            lines[-1],
            'ubuntu-image: error: the following arguments are required: '
            'MODEL-ASSERTION')

    def test_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('--debug',))
        self.assertEqual(cm.exception.code, 0)
        mock.assert_called_once_with(level=logging.DEBUG)


class TestLogin(TestCase):
    def setUp(self):
        # Put $XDG_CONFIG_HOME in a temporary directory we can clean up.  This
        # avoids cluttering up the $HOME of the user running these tests.
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        self._xdg_configdir = os.path.join(tmpdir, '.config')
        self._configdir = os.path.join(self._xdg_configdir, 'ubuntu-image')
        self._resources.enter_context(
            patch('xdg.BaseDirectory.xdg_config_home', self._xdg_configdir))
