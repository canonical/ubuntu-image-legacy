"""Allows the package to be run with `python3 -m ubuntu_image`."""

import getpass
import logging
import guacamole

from contextlib import suppress
from guacamole import Command
from ubuntu_image import auth, storeapi
from ubuntu_image.i18n import _


_logger = logging.getLogger("ubuntu-image")


class Login(Command):
    """Authenticate to the Ubuntu store."""

    name = 'login'

    @classmethod
    def register_arguments(cls, parser):
        parser.add_argument(
            'email', metavar=_('EMAIL-ADDRESS'),
            help=_('Email address on Ubuntu SSO'), nargs='?')

    def invoked(self, ctx):
        print(_('Enter your Ubuntu One SSO credentials.'))
        try:
            email = ctx.args.email
            if not email:
                email = input(_('Email: '))
            password = getpass.getpass(_('Password: '))
        except KeyboardInterrupt:
            return
        otp = ''
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
                print(_('Invalid email or password, please try again'))
                password = getpass.getpass(_('Password: '))
            elif code == 'TWOFACTOR_REQUIRED':
                print(_('Two-factor authentication required'))
                otp = input(_('One-time password: '))
            else:
                _logger.warning('Unexpected code in server response: %s', code)
                break
        with suppress(auth.UnsuccessfulAuthenticationError):
            auth.Credentials().remember_sso_response(response)


class Logout(Command):
    """Logout from the Ubuntu store."""

    name = 'logout'

    def invoked(self, ctx):
        with suppress(FileNotFoundError):
            auth.Credentials().forget()
            print(_('You have been logged out'))


class UbuntuImage(guacamole.Command):
    """Top-level command of ubuntu-image.

    Elegant composer of bootable Ubuntu images.
    """
    name = 'ubuntu-image'

    sub_commands = [
        ('login', Login),
        ('logout', Logout),
        ]

    @classmethod
    def register_arguments(cls, parser):
        parser.add_argument(
            '--debug',
            help=_("Enable debugging output"),
            action='store_true',
            default=False)

    def invoked(self, ctx):
        if ctx.args.debug:
            logging.basicConfig(level=logging.DEBUG)
        if not hasattr(ctx.args, 'command1'):
            ctx.parser.print_help()
            return 0


def main(argv):
    UbuntuImage().main(argv)


if __name__ == '__main__':                          # pragma: nocover
    UbuntuImage().main()
