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
except FileNotFoundError:                           # pragma: nocover
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
    parser.add_argument('-c', '--channel',
                        default=None,
                        help=_('For snap-based images, the channel to use'))
    parser.add_argument('-w', '--workdir',
                        default=None,
                        help=_("""The working directory in which to download
                        and unpack all the source files for the image.  This
                        directory can exist or not, and it is not removed
                        after this program exits.  If not given, a temporary
                        working directory is used instead, which *is* deleted
                        after this program exits."""))
    parser.add_argument('--cloud-init',
                        default=None,
                        help=_("cloud-config data to be copied in the image"))
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
                       The state will be saved in a .ubuntu-image.pck file in
                       the working directory, and can be resumed with -r.  Use
                       -w if you want to resume the process later."""))
    group.add_argument('-t', '--thru',
                       default=None, metavar='STEP',
                       help=_("""Run the state machine through the given STEP,
                       inclusively.  STEP can be a name or number.  The state
                       will be saved in a .ubuntu-image.pck file in the
                       working directory and can be resumed with -r.  Use -w
                       if you want to resume the process later."""))
    args = parser.parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    # The model assertion argument is required unless --resume is given, in
    # which case it cannot be given.
    if args.resume and args.model_assertion:
        parser.error('model assertion is not allowed with --resume')
    if not args.resume and args.model_assertion is None:
        parser.error('model assertion is required')
    if args.resume and args.workdir is None:
        parser.error('--resume requires --workdir')
    # --until and --thru can take an int.
    with suppress(ValueError, TypeError):
        args.thru = int(args.thru)
    with suppress(ValueError, TypeError):
        args.until = int(args.until)
    return args


def main(argv=None):
    args = parseargs(argv)
    if args.workdir:
        os.makedirs(args.workdir, exist_ok=True)
        pickle_file = os.path.join(args.workdir, '.ubuntu-image.pck')
    else:
        pickle_file = None
    if args.resume:
        with open(pickle_file, 'rb') as fp:
            state_machine = load(fp)
        state_machine.workdir = args.workdir
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
    if pickle_file is not None:
        with open(pickle_file, 'wb') as fp:
            dump(state_machine, fp)
    return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
