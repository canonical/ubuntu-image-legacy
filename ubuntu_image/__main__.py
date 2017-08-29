"""Allows the package to be run with `python3 -m ubuntu_image`."""

import os
import sys
import logging
import argparse

from contextlib import suppress
from pickle import dump, load
from ubuntu_image import __version__
from ubuntu_image.builder import DoesNotFit, ModelAssertionBuilder
from ubuntu_image.helpers import as_size, get_host_arch, get_host_distro
from ubuntu_image.i18n import _
from ubuntu_image.parser import GadgetSpecificationError


_logger = logging.getLogger('ubuntu-image')


PROGRAM = 'ubuntu-image'


class SimpleHelpFormatter(argparse.HelpFormatter):
    """SimpleHelpFormatter for generating intuitive help infomation.

    It uses fixed-width indentation for each sub command, options.
    It makes some tweaks on help information layout and removes
    redundant symbol for sub-commands prompt.
    """
    def add_usage(self, usage, actions, groups, prefix=None):
        # only show main usage when no subcommand is provided.
        if prefix is None:
            prefix = 'Usage: '
        if len(actions) != 0:
            usage = ('\n  {prog} COMMAND [OPTIONS]...'
                     '\n  {prog} COMMAND --help').format(prog=PROGRAM)
        else:
            usage = ('{prog} ').format(prog=PROGRAM)

        return super(SimpleHelpFormatter, self).add_usage(
            usage, actions, groups, prefix)

    def _format_action(self, action):
        if type(action) == argparse._SubParsersAction:
            # calculate the subcommand max length
            subactions = action._get_subactions()
            invocations = [self._format_action_invocation(a)
                           for a in subactions]
            self._subcommand_max_length = max(len(i) for i in invocations)

        if type(action) == argparse._SubParsersAction._ChoicesPseudoAction:
            # format subcommand help line
            subcommand = self._format_action_invocation(action)
            help_text = self._expand_help(action)
            return ("  {:{width}}\t\t{} \n").format(
                    subcommand, help_text, width=self._subcommand_max_length)
        elif type(action) == argparse._SubParsersAction:
            # eliminate subcommand choices line {cmd1, cmd2}
            msg = ''
            for subaction in action._get_subactions():
                msg += self._format_action(subaction)
            return msg
        else:
            return super(SimpleHelpFormatter, self)._format_action(action)


class SizeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        sizes = {}
        specs = values.split(',')
        # First check for extended syntax by splitting on commas.
        for spec in specs:
            index, colon, size = spec.partition(':')
            if colon != ':':
                if len(specs) != 1:
                    raise argparse.ArgumentError(
                        self,
                        'Invalid multi-volume size specification: {}'.format(
                            spec))
                # Backward compatibility.  Since there was no colon to
                # partition the string on, the size argument will be in the
                # index local variable.
                try:
                    sizes = as_size(index)
                except (KeyError, ValueError):
                    raise argparse.ArgumentError(
                        self, 'Invalid size: {}'.format(values))
                break
            try:
                size = as_size(size)
            except (KeyError, ValueError):
                raise argparse.ArgumentError(
                    self, 'Invalid size: {}'.format(values))
            try:
                index = int(index)
            except (ValueError, TypeError):
                pass
            sizes[index] = size
        setattr(namespace, self.dest, sizes)
        # For display purposes.
        namespace.given_image_size = values


def get_modified_args(subparser, default_subcommand, argv):
    for arg in argv:
        # skip global help option
        if arg in ['-h', '--help']:
            break
    else:
        for sp_name in subparser._name_parser_map.keys():
            if sp_name in argv:
                break
        else:
            # if `snap` subcommand is not given.
            print('Warning: for backwards compatibility, `ubuntu-image` '
                  'fallbacks to `ubuntu-image snap` if no subcommand is given',
                  file=sys.stderr)
            new_argv = list(argv)
            new_argv.insert(0, default_subcommand)
            return new_argv
    return argv


def add_common_args(subcommand):
    common_group = subcommand.add_argument_group(_('Common options'))
    common_group.add_argument(
        '--version', action='version',
        version='{} {}'.format(PROGRAM, __version__))
    common_group.add_argument(
        '-d', '--debug',
        default=False, action='store_true',
        help=_('Enable debugging output'))
    common_group.add_argument(
        '-i', '--image-size',
        default=None, action=SizeAction, metavar='SIZE',
        help=_("""The suggested size of the generated disk image file.  If this
        size is smaller than the minimum calculated size of the image a warning
        will be issued and --image-size will be ignored.  The value is the size
        in bytes, with allowable suffixes 'M' for MiB and 'G' for GiB.  Use an
        extended syntax to define the suggested size for the disk images
        generated by a multi-volume gadget.yaml spec.  See the ubuntu-image(1)
        manpage for details."""))
    common_group.add_argument(
        '--image-file-list',
        default=None, metavar='FILENAME',
        help=_("""Print to this file, a list of the file system paths to
        all the disk images created by the command, if any."""))
    output_group = common_group.add_mutually_exclusive_group()
    output_group.add_argument(
        '-O', '--output-dir',
        default=None, metavar='DIRECTORY',
        help=_("""The directory in which to put generated disk image files.
        The disk image files themselves will be named <volume>.img inside this
        directory, where <volume> is the volume name taken from the
        gadget.yaml file.  Use this option instead of the deprecated
        -o/--output option."""))
    output_group.add_argument(
        '-o', '--output',
        default=None, metavar='FILENAME',
        help=_("""DEPRECATED (use -O/--output-dir instead).  The generated
        disk image file.  If not given, the image will be put in a file called
        disk.img in the working directory (in which case, you probably want to
        specify -w)."""))

    # State machine options.
    inclusive_state_group = subcommand.add_argument_group(
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
    return subcommand


def parseargs(argv=None):
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=_('Generate a bootable disk image.'),
        formatter_class=SimpleHelpFormatter)

    # create two subcommands, "snap" and "classic"
    subparser = parser.add_subparsers(title=_('Command'), dest='cmd')
    snap_cmd = subparser.add_parser(
            'snap',
            help=_("""Create snap-based Ubuntu Core image."""))
    classic_cmd = subparser.add_parser(
            'classic',
            help=_("""Create debian-based Ubuntu Classic image."""))
    argv = get_modified_args(subparser, 'snap', argv)

    snap_cmd = add_common_args(snap_cmd)
    classic_cmd = add_common_args(classic_cmd)

    # Snap-based image options.
    snap_cmd.add_argument(
        'model_assertion', nargs='?',
        help=_("""Path to the model assertion file.  This argument must be
        given unless the state machine is being resumed, in which case it
        cannot be given."""))
    snap_cmd.add_argument(
        '--extra-snaps',
        default=None, action='append',
        help=_("""Extra snaps to install.  This is passed through to `snap
        prepare-image`."""))
    snap_cmd.add_argument(
        '--cloud-init',
        default=None, metavar='USER-DATA-FILE',
        help=_('cloud-config data to be copied to the image'))
    snap_cmd.add_argument(
        '-c', '--channel',
        default=None,
        help=_('The snap channel to use'))

    # Classic-based image options.
    classic_cmd.add_argument(
        'gadget_tree', nargs='?',
        help=_("""Gadget tree.  This is a tree equivalent to an unpacked
        gadget snap at core image build time."""))
    classic_cmd.add_argument(
        '-p', '--project',
        default='ubuntu-cpc', metavar='PROJECT',
        help=_("""Project name to be specified to livecd-rootfs."""))
    classic_cmd.add_argument(
        '-s', '--suite',
        default=get_host_distro(), metavar='SUITE',
        help=_("""Distribution name to be specified to livecd-rootfs."""))
    classic_cmd.add_argument(
        '-a', '--arch',
        default=get_host_arch(), metavar='CPU-ARCHITECTURE',
        help=_("""CPU architecture to be specified to livecd-rootfs.
        default value is builder arch."""))
    classic_cmd.add_argument(
        '--subproject',
        default=None, metavar='SUBPROJECT',
        help=_("""Sub project name to be specified to livecd-rootfs."""))
    classic_cmd.add_argument(
        '--subarch',
        default=None, metavar='SUBARCH',
        help=_("""Sub architecture to be specified to livecd-rootfs."""))
    classic_cmd.add_argument(
        '--with-proposed',
        default=False, action='store_true',
        help=_("""Proposed repo to install, This is passed through to
        livecd-rootfs."""))
    classic_cmd.add_argument(
        '--image-format',
        default='img',
        help=_("""Image format to be specified to livecd-rootfs."""))
    classic_cmd.add_argument(
        '--extra-ppas',
        default=None, action='append',
        help=_("""Extra ppas to install. This is passed through to
        livecd-rootfs."""))

    args = parser.parse_args(argv)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    # The model assertion argument is required unless --resume is given, in
    # which case it cannot be given.
    # if args.cmd == 'snap':
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
    # -o/--output is deprecated and mutually exclusive with -O/--output-dir
    if args.output is not None:
        print('-o/--output is deprecated; use -O/--output-dir instead',
              file=sys.stderr)
    return args


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

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
    # elif args.cmd == 'classic':

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
    except DoesNotFit as error:
        _logger.error(
            'Volume contents do not fit ({}B over): {} [#{}]'.format(
                error.overage, error.part_path, error.part_number))
    except:
        _logger.exception('Crash in state machine')
        return 1
    # It's possible that the state machine didn't crash, but it still didn't
    # complete successfully.  For example, if `snap prepare-image` failed.
    if state_machine.exitcode != 0:
        return state_machine.exitcode
    # Write out the list of images, if there are any.
    if (state_machine.gadget is not None and
            state_machine.done and
            args.image_file_list is not None):
        with open(args.image_file_list, 'w', encoding='utf-8') as fp:
            if args.output is None:
                for name in state_machine.gadget.volumes:
                    path = os.path.join(
                        args.output_dir, '{}.img'.format(name))
                    print(path, file=fp)
            else:
                print(args.output, file=fp)
    # Everything's done, now handle saving state if necessary.
    if pickle_file is not None:
        with open(pickle_file, 'wb') as fp:
            dump(state_machine, fp)
    return 0


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
