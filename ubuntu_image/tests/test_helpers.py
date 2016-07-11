"""Test the helpers."""


from io import StringIO
from contextlib import ExitStack
from ubuntu_image.helpers import GiB, MiB, as_size, run, transform
from unittest import TestCase
from unittest.mock import patch


class FakeProc:
    returncode = 1
    stdout = 'fake stdout'
    stderr = 'fake stderr'

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
                patch('ubuntu_image.helpers.sys.stderr', stderr))
            resources.enter_context(
                patch('ubuntu_image.helpers.subprocess_run',
                      return_value=FakeProc()))
            run('/bin/false')
        # stdout gets piped to stderr.
        self.assertEqual(stderr.getvalue(), 'fake stdoutfake stderr')
