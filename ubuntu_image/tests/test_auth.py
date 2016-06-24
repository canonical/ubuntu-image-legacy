"""Test the auth module."""

import os

from contextlib import ExitStack
from tempfile import TemporaryDirectory
from ubuntu_image.auth import Credentials
from unittest import TestCase
from unittest.mock import patch


class TestCredentials(TestCase):
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

    def test_load_file_missing(self):
        Credentials()
        # The config directory exists now...
        self.assertTrue(os.path.exists(self._configdir))
        # ...but the credentials.ini file does not.
        self.assertFalse(os.path.exists(
            os.path.join(self._configdir, 'credentials.ini')))

    def test_get_credentials(self):
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        os.makedirs(self._configdir)
        with open(ini_file, 'w', encoding='utf-8') as fp:
            print("""\
[login.ubuntu.com]
username: a_user
password: the_password
""", file=fp)
        credentials = Credentials()
        self.assertEqual(credentials.credentials, dict(
            username='a_user',
            password='the_password',
            ))

    def test_forget_credentials(self):
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        os.makedirs(self._configdir)
        with open(ini_file, 'w', encoding='utf-8') as fp:
            print("""\
[login.ubuntu.com]
username: a_user
password: the_password
""", file=fp)
        credentials = Credentials()
        credentials.forget()
        self.assertIsNone(credentials.credentials)
        self.assertFalse(os.path.exists(ini_file))

    def test_forget_credentials_before_they_exist(self):
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        credentials = Credentials()
        credentials.forget()
        self.assertIsNone(credentials.credentials)
        self.assertFalse(os.path.exists(ini_file))

    def test_remember_sso_response(self):
        # Test the basic unpacking of the SSO response, including the saving
        # of that response to the credentials file given that the response
        # contains some credentials.
        credentials = Credentials()
        credentials.remember_sso_response(dict(
            success=True,
            body=dict(
                username='another_user',
                password='some other password',
                )))
        self.assertEqual(credentials.credentials, dict(
            username='another_user',
            password='some other password',
            ))
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        self.assertTrue(os.path.exists(ini_file))
        with open(ini_file, 'r', encoding='utf-8') as fp:
            contents = fp.read()
        self.assertEqual(contents, """\
[login.ubuntu.com]
password = some other password
username = another_user

""")

    def test_remember_sso_response_implicit_failure(self):
        # The SSO response implicitly did not succeed.
        credentials = Credentials()
        self.assertRaises(ValueError, credentials.remember_sso_response, {})
        self.assertIsNone(credentials.credentials)

    def test_remember_sso_response_explicit_failure(self):
        # The SSO response explicitly did not succeed.
        credentials = Credentials()
        self.assertRaises(ValueError,
                          credentials.remember_sso_response,
                          dict(success=False))
        self.assertIsNone(credentials.credentials)

    def test_remember_sso_response_succeeds_but_no_credentials(self):
        # There was no body, so no credentials and nothing to save.
        credentials = Credentials()
        credentials.remember_sso_response(dict(success=True))
        self.assertIsNone(credentials.credentials)
        self.assertFalse(os.path.exists(
            os.path.join(self._configdir, 'credentials.ini')))

    def test_remember_sso_response_succeeds_appends(self):
        # The credentials file already exists but it does not have a login
        # section.  This is appended to the file.
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        os.makedirs(self._configdir)
        with open(ini_file, 'w', encoding='utf-8') as fp:
            print("""\
[other section]
bob: your uncle
""", file=fp)
        credentials = Credentials()
        credentials.remember_sso_response(dict(
            success=True,
            body=dict(
                username='another_user',
                password='some other password',
                )))
        with open(ini_file, 'r', encoding='utf-8') as fp:
            contents = fp.read()
        # The original colon gets turned into an equal.
        self.assertEqual(contents, """\
[other section]
bob = your uncle

[login.ubuntu.com]
password = some other password
username = another_user

""")

    def test_remember_sso_response_succeeds_replaces(self):
        # The credentials file already exists and it does have a login
        # section.  The credentials get overwritten.
        ini_file = os.path.join(self._configdir, 'credentials.ini')
        os.makedirs(self._configdir)
        with open(ini_file, 'w', encoding='utf-8') as fp:
            print("""\
[other section]
bob: your uncle

[login.ubuntu.com]
password = first password
username = anne
""", file=fp)
        credentials = Credentials()
        credentials.remember_sso_response(dict(
            success=True,
            body=dict(
                username='bill',
                password='second password',
                )))
        with open(ini_file, 'r', encoding='utf-8') as fp:
            contents = fp.read()
        # The original colon gets turned into an equal.
        self.assertEqual(contents, """\
[other section]
bob = your uncle

[login.ubuntu.com]
password = second password
username = bill

""")

    def test_exclusive_open_goes_negative(self):
        # Don't use -1 as the return value because of:
        # http://bugs.python.org/issue27066
        self._resources.enter_context(
            patch('ubuntu_image.auth.os.open',
                  return_value=-2))
        self.assertRaises((OSError, ValueError), Credentials)

    def test_exclusive_open_goes_negative_during_save(self):
        # See above.
        credentials = Credentials()
        self._resources.enter_context(
            patch('ubuntu_image.auth.os.open',
                  return_value=-2))
        self.assertRaises((OSError, ValueError),
                          credentials.remember_sso_response,
                          dict(
                              success=True,
                              body=dict(
                                  username='bill',
                                  password='second password',
                                  )))
