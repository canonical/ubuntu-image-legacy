"""Allows the package to be run with `python3 -m ubuntu_image`."""


import os
import sys
import logging
import argparse

from contextlib import suppress
from pickle import dump, load
from pkg_resources import resource_string as resource_bytes
from ubuntu_image.builder import ModelAssertionBuilder
from ubuntu_image.helpers import as_size
from ubuntu_image.i18n import _
from ubuntu_image.parser import GadgetSpecificationError


_logger = logging.getLogger('ubuntu-image')

# Try to get the version number, which will be different if we're living in a
# snap world or a deb.  Actually, I'd prefer to not even have the -NubuntuY
# version string when we're running from source, but that's trickier, so don't
# worry about it.
__version__ = os.environ.get('SNAP_VERSION')
if __version__ is None:                                      # pragma: nocover
    try:
        __version__ = resource_bytes(
            'ubuntu_image', 'version.txt').decode('utf-8')
    except FileNotFoundError:
        # Probably, setup.py hasn't been run yet to generate the version.txt.
        __version__ = 'dev'


PROGRAM = 'ubuntu-image'


class SizeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        try:
            size = as_size(values)
        except (KeyError, ValueError):
            raise argparse.ArgumentError(
                self, 'Invalid size: {}'.format(values))
        setattr(namespace, self.dest, size)
        # For display purposes.
        namespace.given_image_size = values


def parseargs(argv=None):
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=_('Generate a bootable disk image.'),
        )
    parser.add_argument(
        '--version', action='version',
        version='{} {}'.format(PROGRAM, __version__))
    # Common options.
    common_group = parser.add_argument_group(_('Common options'))
    common_group.add_argument(
        'model_assertion', nargs='?',
        help=_("""Path to the model assertion file.  This argument must be
        given unless the state machine is being resumed, in which case it
        cannot be given."""))
    common_group.add_argument(
        '-d', '--debug',
        default=False, action='store_true',
        help=_('Enable debugging output'))
    common_group.add_argument(
        '-o', '--output',
        default=None, metavar='FILENAME',
        help=_("""The generated disk image file.  If not given, the image will
        be put in a file called disk.img in the working directory (in which
        case, you probably want to specify -w)."""))
    common_group.add_argument(
        '--image-size',
        default=None, action=SizeAction, metavar='SIZE',
        help=_("""The size of the generated disk image file (see
        -o/--output).  If this size is smaller than the minimum calculated
        size of the image a warning will be issued and --image-size will be
        ignored.  The value is the size in bytes, with allowable suffixes 'M'
        for MiB and 'G' for GiB."""))
    # Snap-based image options.
    snap_group = parser.add_argument_group(
        _('Image contents options'),
        _("""Additional options for defining the contents of snap-based
        images."""))
    snap_group.add_argument(
        '--extra-snaps',
        default=None, action='append',
        help=_("""Extra snaps to install.  This is passed through to `snap
        prepare-image`."""))
    snap_group.add_argument(
        '--cloud-init',
        default=None, metavar='USER-DATA-FILE',
        help=_('cloud-config data to be copied to the image'))
    snap_group.add_argument(
        '-c', '--channel',
        default=None,
        help=_('The snap channel to use'))
    # State machine options.
    inclusive_state_group = parser.add_argument_group(
        _('State machine options'),
        _("""Options for controlling the internal state machine.  Other than
        -w, these options are mutually exclusive.  When -u or -t is given, the
        state machine can be resumed later with -r, but -w must be given in
        that case since the state is saved in a .ubuntu-image.pck file in the
        working directory."""))
    inclusive_state_group.add_argument(
        '-w', '--workdir',
        default=None, metavar='DIRECTORY',
        help=_("""The working directory in which to download and unpack all
        the source files for the image.  This directory can exist or not, and
        it is not removed after this program exits.  If not given, a temporary
        working directory is used instead, which *is* deleted after this
        program exits.  Use -w if you want to be able to resume a partial
        state machine run."""))
    state_group = inclusive_state_group.add_mutually_exclusive_group()
    state_group.add_argument(
        '-u', '--until',
        default=None, metavar='STEP',
        help=_("""Run the state machine until the given STEP, non-inclusively.
        STEP can be a name or number."""))
    state_group.add_argument(
        '-t', '--thru',
        default=None, metavar='STEP',
        help=_("""Run the state machine through the given STEP, inclusively.
        STEP can be a name or number."""))
    state_group.add_argument(
        '-r', '--resume',
        default=False, action='store_true',
        help=_("""Continue the state machine from the previously saved state.
        It is an error if there is no previous state."""))
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
    except GadgetSpecificationError as error:
        if args.debug:
            _logger.exception('gadget.yaml parse error')
        else:
            _logger.error('gadget.yaml parse error: {}'.format(error))
            _logger.error('Use --debug for more information')
    except:
        _logger.exception('Crash in state machine')
        return 1
    # It's possible that the state machine didn't crash, but it still didn't
    # complete successfully.  For example, if `snap prepare-image` failed.
    if state_machine.exitcode != 0:
        return state_machine.exitcode
    # Everything's done, now handle saving state if necessary.
    if pickle_file is not None:
        with open(pickle_file, 'wb') as fp:
            dump(state_machine, fp)
    return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
