"""Test main execution."""

import os
import logging

from contextlib import ExitStack
from io import StringIO
from tempfile import TemporaryDirectory
from ubuntu_image.__main__ import main
from unittest import TestCase, skip
from unittest.mock import call, patch


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

    def test_keyboard_interrupt(self):
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.input', side_effect=KeyboardInterrupt))
            mock = resources.enter_context(patch('builtins.print'))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login',))
        mock.assert_called_once_with('Enter your Ubuntu One SSO credentials.')
        self.assertEqual(cm.exception.code, 0)
        self.assertFalse(os.path.exists(
            os.path.join(self._configdir, 'credentials.ini')))

    def test_no_email(self):
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.input', return_value='anne@example.com'))
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      return_value=dict(success=True)))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login',))
        mock.assert_called_once_with(
            'anne@example.com', 'mypassword',
            token_name='ubuntu-image', otp='')
        self.assertEqual(cm.exception.code, 0)

    def test_email(self):
        with ExitStack() as resources:
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      return_value=dict(success=True)))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login', 'bill@example.com'))
        mock.assert_called_once_with(
            'bill@example.com', 'mypassword',
            token_name='ubuntu-image', otp='')
        self.assertEqual(cm.exception.code, 0)

    def test_email_no_success(self):
        with ExitStack() as resources:
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      return_value=dict(success=False)))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login', 'bill@example.com'))
        # Failure, because the server response contained no body.
        self.assertEqual(cm.exception.code, 1)

    def test_body_invalid_credentials(self):
        with ExitStack() as resources:
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      side_effect=[
                          # The first time login() is called, we mimic invalid
                          # credentials.
                          dict(success=False,
                               body=dict(code='INVALID_CREDENTIALS')),
                          # The second time login() is called, we mimic a
                          # successful login.
                          dict(success=True),
                          ]))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login', 'bill@example.com'))
        self.assertEqual(cm.exception.code, 0)

    def test_body_two_factor(self):
        with ExitStack() as resources:
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      side_effect=[
                          # The first time login() is called, we mimic invalid
                          # credentials.
                          dict(success=False,
                               body=dict(code='TWOFACTOR_REQUIRED')),
                          # The second time login() is called, we mimic a
                          # successful login.
                          dict(success=True),
                          ]))
            resources.enter_context(
                patch('builtins.input', return_value='OTP'))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login', 'bill@example.com'))
        # Failure, because the server response contained no body.
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(len(mock.call_args_list), 2)
        # The second call included the two factor authorization code.
        self.assertEqual(mock.call_args_list[1],
                         call('bill@example.com', 'mypassword',
                              otp='OTP', token_name='ubuntu-image'))

    def test_body_bad_code(self):
        with ExitStack() as resources:
            resources.enter_context(patch('builtins.print'))
            resources.enter_context(
                patch('ubuntu_image.__main__.getpass.getpass',
                      return_value='mypassword'))
            resources.enter_context(
                patch('ubuntu_image.__main__.storeapi.login',
                      return_value=dict(success=False,
                                        body=dict(code='UNEXPECTED_CODE'))))
            mock = resources.enter_context(
                patch('ubuntu_image.__main__._logger.warning'))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('login', 'bill@example.com'))
        # Failure, because of the unexpected response.
        self.assertEqual(cm.exception.code, 1)
        mock.assert_called_once_with(
            'Unexpected code in server response: %s', 'UNEXPECTED_CODE')


class TestLogout(TestCase):
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

    def test_logout(self):
        with ExitStack() as resources:
            mock = resources.enter_context(patch('builtins.print'))
            cm = resources.enter_context(self.assertRaises(SystemExit))
            main(('logout',))
        self.assertEqual(cm.exception.code, 0)
        mock.assert_called_once_with('You have been logged out')
