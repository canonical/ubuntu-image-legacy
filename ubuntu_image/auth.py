"""Utilities for working with SSO authentication."""

import os
import fcntl
import logging
import configparser

from contextlib import suppress
from xdg.BaseDirectory import save_config_path


__all__ = ('UnsuccessfulAuthenticationError', 'Credentials')

_logger = logging.getLogger('ubuntu-image')


class UnsuccessfulAuthenticationError(ValueError):
    """Exception raised on unsuccessful SSO authentication."""


class Credentials:
    """Persistent credentials from Ubuntu SSO."""

    #: section name for SSO credentials
    SECTION = 'login.ubuntu.com'

    def __init__(self):
        """Initialize SSO credentials.

        Credentials stored by other sessions are implicitly loaded on
        initialization. The credentials may end up None, valid or valid
        but expired.
        """
        self._credentials = None
        with suppress(FileNotFoundError):
            self._load()

    @property
    def credentials(self):
        """Get the object representing SSO credentials."""
        return self._credentials

    def forget(self):
        """Forget SSO credentials and remove stored copy from disk."""
        self._credentials = None
        with suppress(FileNotFoundError):
            os.unlink(self._credentials_file)

    def remember_sso_response(self, sso_response):
        """Remember credentials passed as a SSO response object.

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
            raise ValueError('SSO response was not successful')
        self._credentials = sso_response.get('body')
        self._save()

    def _save(self):
        """Save SSO credentials to disk."""
        if self._credentials is None:
            return
        parser = configparser.ConfigParser()
        with open(self._credentials_file, 'r+t', encoding='utf-8',
                  opener=_exclusive_private_opener) as stream:
            parser.read_file(stream)
            if not parser.has_section(self.SECTION):
                parser.add_section(self.SECTION)
            # Sort the keys for deterministic contents.
            for key in sorted(self._credentials):
                value = self._credentials[key]
                parser.set(self.SECTION, key, str(value))
            # Overwrite the contents of the ini file with the new contents.
            stream.truncate(0)
            stream.seek(0)
            parser.write(stream)

    def _load(self):
        """Load SSO credentials from disk."""
        parser = configparser.ConfigParser()
        with open(self._credentials_file, 'rt', encoding='utf-8',
                  opener=_shared_opener) as stream:
            parser.read_file(stream)
        if parser.has_section(self.SECTION):
            self._credentials = dict(parser.items(self.SECTION))

    @property
    def _credentials_file(self):
        """Path to per-user file with SSO credentials"""
        return os.path.join(
            save_config_path('ubuntu-image'), 'credentials.ini')


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
