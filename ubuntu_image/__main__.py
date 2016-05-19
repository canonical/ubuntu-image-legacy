"""Allows the package to be run with `python3 -m ubuntu_image`."""

import logging
import guacamole

from ubuntu_image import auth
from ubuntu_image.i18n import _


_logger = logging.getLogger("ubuntu-image")


class UbuntuImage(guacamole.Command):
    """Top-level command of ubuntu-image.

    Elegant composer of bootable Ubuntu images.
    """
    name = 'ubuntu-image'

    sub_commands = [
        ('login', auth.Login),
        ('logout', auth.Logout),
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


if __name__ == '__main__':
    UbuntuImage().main()
