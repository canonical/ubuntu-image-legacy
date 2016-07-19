"""Allows the package to be run with `python3 -m ubuntu_image`."""


import os
import sys
import logging
import argparse

from contextlib import suppress
from pickle import dump, load
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
    parser.add_argument('-o', '--output',
                        default=None,
                        help=_('The output file for the disk image'))
    parser.add_argument('-r', '--resume',
                        default=False, action='store_true',
                        help=_("""Continue the state machine from the
                        previously saved state.  It is an error if there is no
                        previous state."""))
    parser.add_argument('model_assertion', nargs='?',
                        help=_('Path to the model assertion'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-u', '--until',
                       default=None, metavar='STEP',
                       help=_("""Run the state machine until the given STEP,
                       non-inclusively.  STEP can be a name or number.
                       Implies --keep.  The state will be saved in a
                       .ubuntu-image.pck file in the current directory, and
                       can be resumed with -r."""))
    group.add_argument('-t', '--thru',
                       default=None, metavar='STEP',
                       help=_("""Run the state machine through the given STEP,
                       inclusively.  STEP can be a name or number.  Implies
                       --keep.  The state will be saved in a .ubuntu-image.pck
                       file in the current directory and can be resumed with
                       -r."""))
    args = parser.parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    # --thru and --until imply --keep
    if args.thru or args.until:
        args.keep = True
    # The model assertion argument is required unless --resume is given, in
    # which case it cannot be given.
    if args.resume and args.model_assertion:
        parser.error('model assertion is not allowed with --resume')
    if not args.resume and args.model_assertion is None:
        parser.error('model assertion is required')
    return args


def main(argv=None):
    args = parseargs(argv)
    pickle_file = os.path.abspath('.ubuntu-image.pck')
    if args.resume:
        with open(pickle_file, 'rb') as fp:
            state_machine = load(fp)
    else:
        state_machine = ModelAssertionBuilder(args)
    # Run the state machine, either to the end or thru/until the named state.
    try:
        if args.thru:
            state_machine.run_thru(args.thru)
        elif args.until:
            state_machine.run_until(args.until)
        else:
            list(state_machine)
    except:
        _logger.exception('Crash in state machine')
        return 1
    # Everything's done, now handle saving state if necessary.
    if args.thru or args.until:
        with open(pickle_file, 'wb') as fp:
            dump(state_machine, fp)
    else:
        with suppress(FileNotFoundError):
            os.remove(pickle_file)
    return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
