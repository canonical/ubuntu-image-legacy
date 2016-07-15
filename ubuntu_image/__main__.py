"""Allows the package to be run with `python3 -m ubuntu_image`."""


import sys
import logging
import argparse

from pkg_resources import resource_string as resource_bytes
from ubuntu_image.builder import ModelAssertionBuilder
from ubuntu_image.i18n import _


_logger = logging.getLogger('ubuntu-image')
try:
    __version__ = resource_bytes('ubuntu_image', 'version.txt').decode('utf-8')
except FileNotFoundError:                           # pragma: no cover
    # Probably, setup.py hasn't been run yet to generate the version.txt.
    __version__ = 'dev'
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
    parser.add_argument('-k', '--keep',
                        default=False, action='store_true',
                        help=_('Keep (and print) temporary directories'))
    parser.add_argument('-c', '--channel',
                        default=None,
                        help=_('For snap-based images, the channel to use'))
    parser.add_argument('model-assertion', nargs=1,
                        help=_('Path to the model assertion'))
    args = parser.parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    return args


def main(argv=None):
    args = parseargs(argv)
    state_machine = ModelAssertionBuilder(args)
    try:
        list(state_machine)
    except:
        _logger.exception('Crash in state machine')
        return 1
    else:
        return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
