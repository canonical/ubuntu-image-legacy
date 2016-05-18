import configparser
import fcntl
import getpass
import logging
import os

from guacamole import Command
from xdg.BaseDirectory import save_config_path

from ubuntu_image import storeapi
from ubuntu_image.i18n import _

_logger = logging.getLogger("ubuntu-image")

__all__ = ('UnsuccessfulAuthenticationError', 'Credentials', 'Login', 'Logout')


"""Utilities for working with SSO authentication."""


class UnsuccessfulAuthenticationError(ValueError):

    """Exception raised on unsuccessful SSO authentication."""


class Credentials:

    """Persistent credentials from Ubuntu SSO."""

    def __init__(self):
        """
        Initialize SSO credentials.

        Credentials stored by other sessions are implicitly loaded on
        initialization. The credentials may end up None, valid or valid but
        expired.
        """
        self._creds = None
        try:
            self._load()
        except FileNotFoundError:
            pass

    def get(self):
        """Get the object representing SSO credentials."""
        return self._creds

    def remember_sso_response(self, sso_response):
        """
        Remember credentials passed as a SSO response object.

        @param sso_response:
            Dictionary with response data, decoded from the SSO response.
        @raises UnsuccessfulAuthenticationError:
            If the SSO response represents a failed authentication attempt
            that does not contain valid credentials.

        After calling this method, the :meth:`creds` property can be used to
        subsequently access credentials. Other instances can gain access to the
        same credentials by calling :meth:`load()`.

        .. note::
            The created file is readable only to the current user.
            Credentials are store in plain text.
        """
        if not sso_response.get('success', False):
            raise ValueError("SSO response was not successful")
        self._creds = sso_response.get('body')
        self._save()

    def forget(self):
        """Forget SSO credentials and remove stored copy from disk."""
        self._creds = None
        os.unlink(self._creds_file)

    def _save(self):
        """Save SSO credentials to disk."""
        if self._creds is None:
            return

        stream = open(self._creds_file, 'r+t', encoding='utf-8',
                      opener=_exclusive_private_opener)
        parser = configparser.ConfigParser()
        with stream:
            parser.read_file(stream)
            if not parser.has_section(self._location):
                parser.add_section(self._location)
            for key, value in self._creds.items():
                parser.set(self._location, key, str(value))
            stream.truncate()
            parser.write(stream)

    def _load(self):
        """Load SSO credentials from disk."""
        stream = open(self._creds_file, 'rt', encoding='utf-8',
                      opener=_shared_opener)
        parser = configparser.ConfigParser()
        with stream:
            parser.read_file(stream)
        if parser.has_section(self._location):
            self._creds = dict(parser.items(self._location))

    @property
    def _creds_file(self):
        """Path to per-user file with SSO credentials"""
        return os.path.join(save_config_path('ubuntu-image'),
                            'credentials.ini')

    #: section name for SSO credentials
    _location = 'login.ubuntu.com'


def _exclusive_private_opener(fname, flags):
    """Opener using exclusive (advisory) lock and 0600 permissions."""
    flags |= os.O_CREAT
    fd = os.open(fname, flags, 0o600)
    if fd > 0:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _shared_opener(fname, flags):
    """Opener using shared (advisory) lock."""
    fd = os.open(fname, flags, 0o600)
    if fd > 0:
        fcntl.flock(fd, fcntl.LOCK_SH)
    return fd


class Login(Command):

    """Authenticate to the Ubuntu store."""

    name = 'login'

    @classmethod
    def register_arguments(cls, parser):
        parser.add_argument(
            'email', metavar=_('EMAIL-ADDRESS'),
            help=_("Email address on Ubuntu SSO"), nargs='?')

    def invoked(self, ctx):
        print(_("Enter your Ubuntu One SSO credentials."))
        try:
            email = ctx.args.email
            if not email:
                email = input(_("Email: "))
            password = getpass.getpass(_("Password: "))
        except KeyboardInterrupt:
            return
        otp = ""
        while True:
            _logger.info('Authenticating against Ubuntu One SSO.')
            response = storeapi.login(
                email, password, token_name='ubuntu-image', otp=otp)
            success = response.get('success', False)
            if success:
                _logger.info('Login successful.')
                break
            body = response.get('body')
            if body is None:
                raise Exception('Server response does not contain body')
            code = body.get('code')
            _logger.info('Login failed %s: (%s)', code, body.get('message'))
            if code == 'INVALID_CREDENTIALS':
                print(_("Invalid email or password, please try again"))
                password = getpass.getpass(_("Password: "))
            elif code == 'TWOFACTOR_REQUIRED':
                print(_("Two-factor authentication required"))
                otp = input(_("One-time password: "))
            else:
                _logger.warning("Unexpected code in server response: %s", code)
                break
        try:
            Credentials().remember_sso_response(response)
        except UnsuccessfulAuthenticationError:
            pass


class Logout(Command):

    """Logout from the Ubuntu store."""

    name = 'logout'

    def invoked(self, ctx):
        try:
            Credentials().forget()
        except FileNotFoundError:
            pass
        else:
            print(_("You have been logged out"))
