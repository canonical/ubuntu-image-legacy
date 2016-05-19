"""Test main execution."""

from contextlib import ExitStack
from io import StringIO
from ubuntu_image.__main__ import main
from unittest import TestCase
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

    # XXX: re-enable this when 'ubuntu-image build' is added again
    def _test_require_model(self):
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
