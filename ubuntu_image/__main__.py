"""Allows the package to be run with `python3 -m ubuntu_image`."""


import sys
import logging
import argparse

from pkg_resources import resource_string as resource_bytes
from ubuntu_image.i18n import _


_logger = logging.getLogger("ubuntu-image")
__version__ = resource_bytes('ubuntu_image', 'version.txt').decode('utf-8')
PROGRAM = 'ubuntu-image'


def parseargs(argv=None):
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=_('Generate a bootable disk image.'),
        )
    parser.add_argument('--version', action='version',
                        version='{} {}'.format(PROGRAM, __version__))
    parser.add_argument('-d', '--debug',
                        default=False, action='store_true',
                        help=_('Enable debugging output'))
    args = parser.parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    return args


def main(argv=None):
    parseargs(argv)
    return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
