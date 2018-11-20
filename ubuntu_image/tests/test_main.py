"""Test main execution."""

import os
import logging
import argparse

from contextlib import ExitStack, contextmanager
from io import StringIO
from mmap import mmap
from pickle import load
from pkg_resources import resource_filename
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.__main__ import get_modified_args, main, parseargs
from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.hooks import supported_hooks
from ubuntu_image.testing.helpers import (
    CallLBLeaveATraceClassicBuilder, CrashingModelAssertionBuilder,
    DoNothingBuilder, EarlyExitLeaveATraceAssertionBuilder,
    EarlyExitLeaveATraceClassicBuilder, EarlyExitModelAssertionBuilder,
    LogCapture, XXXModelAssertionBuilder, envar)
from ubuntu_image.testing.nose import NosePlugin
from unittest import TestCase, skipIf
from unittest.mock import call, patch


# For forcing a test failure.
def check_returncode(*args, **kws):
    raise CalledProcessError(1, 'failing command')


@contextmanager
def chdir(new_dir):
    here = os.getcwd()
    try:
        os.chdir(new_dir)
        yield
    finally:
        os.chdir(here)


class BadGadgetModelAssertionBuilder(XXXModelAssertionBuilder):
    gadget_yaml = 'bad-gadget.yaml'


class TestGetModifiedArgs(TestCase):
    def test_image_with_help(self):
        parser = argparse.ArgumentParser(add_help=False)
        # create one subcommand, "snap"
        subparser = parser.add_subparsers(dest='cmd')
        subparser.add_parser('snap')
        argv = get_modified_args(subparser, 'snap', ['--help'])
        self.assertEqual(['--help'], argv)

    def test_image_without_subcommand(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            parser = argparse.ArgumentParser(add_help=False)
            # create one subcommand, "snap"
            subparser = parser.add_subparsers(dest='cmd')
            subparser.add_parser('snap')
            argv = get_modified_args(
                    subparser, 'snap',
                    ['-o', 'abc.img', '-i', '45', 'model.assertion'])
            self.assertEqual(
                    ['snap', '-o', 'abc.img', '-i', '45', 'model.assertion'],
                    argv)

    def test_image_with_subcommand(self):
        parser = argparse.ArgumentParser(add_help=False)
        # create one subcommand, "snap"
        subparser = parser.add_subparsers(dest='cmd')
        subparser.add_parser('snap')
        argv = get_modified_args(
                subparser, 'snap',
                ['snap', '-d', '-o', 'pc_amd64.img', 'model.assertion'])
        self.assertEqual(
                ['snap', '-d', '-o', 'pc_amd64.img', 'model.assertion'],
                argv)

    def test_image_with_multiple_subcommand(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            parser = argparse.ArgumentParser(add_help=False)
            # create two subcommands, "snap" and "classic"
            subparser = parser.add_subparsers(dest='cmd')
            subparser.add_parser('snap')
            subparser.add_parser('classic')
            argv = get_modified_args(
                    subparser, 'classic',
                    ['-d', '-o', 'pc_amd64.img', 'model.assertion'])
            self.assertEqual(
                    ['classic', '-d', '-o', 'pc_amd64.img', 'model.assertion'],
                    argv)


class TestParseArgs(TestCase):
    def test_image_size_option_bytes(self):
        args = parseargs(['snap', '--image-size', '45', 'model.assertion'])
        self.assertEqual(args.image_size, 45)
        self.assertEqual(args.given_image_size, '45')

    def test_image_size_option_bytes_without_subcommand(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            args = parseargs(['--image-size', '45', 'model.assertion'])
            self.assertEqual(args.image_size, 45)
            self.assertEqual(args.given_image_size, '45')

    def test_image_size_option_suffixes(self):
        args = parseargs(['snap', '--image-size', '45G', 'model.assertion'])
        self.assertEqual(args.image_size, GiB(45))
        self.assertEqual(args.given_image_size, '45G')
        args = parseargs(['snap', '--image-size', '45M', 'model.assertion'])
        self.assertEqual(args.image_size, MiB(45))
        self.assertEqual(args.given_image_size, '45M')

    def test_image_size_option_invalid(self):
        # These errors will output to stderr, but that just clouds the test
        # output, so suppress it.
        with patch('argparse._sys.stderr'):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['snap', '--image-size', '45Q',
                               'model.assertion'])
            self.assertRaises(SystemExit,
                              parseargs,
                              ['snap', '--image-size', 'BIG',
                               'model.assertion'])

    def test_output_dir_mutually_exclusive_with_output(self):
        # You can't use -O/--output-dir and -o/--output at the same time.
        with patch('argparse._sys.stderr'):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['-o', '/tmp/disk.img', '-O', '/tmp'])

    def test_output_is_deprecated(self):
        # -o/--output is deprecated.
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            parseargs(['-o', '/tmp/disk.img', 'model.assertion'])
        lines = stderr.getvalue().splitlines()
        self.assertTrue(
                lines[0].startswith('Warning: for backwards compatibility'),
                lines[0])
        self.assertEqual(
                lines[1],
                '-o/--output is deprecated; use -O/--output-dir instead')

    def test_multivolume_image_size(self):
        args = parseargs(['snap', '-i', '0:4G,sdcard:2G,1:4G',
                          'model.assertion'])
        self.assertEqual(args.image_size, {
            0: GiB(4),
            'sdcard': GiB(2),
            1: GiB(4),
            })

    def test_multivolume_no_colon(self):
        with patch('argparse._sys.stderr'):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['snap', '-i', '0:2G,4G,1:8G',
                               'model.assertion'])

    def test_multivolume_bad_size(self):
        with patch('argparse._sys.stderr'):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['snap', '-i', '0:2G,1:4BIG,2:8G',
                               'model.assertion'])

    def test_hooks_directory_single(self):
        args = parseargs(
            ['snap', '--hooks-directory', '/foo/bar', 'model.assertion'])
        self.assertListEqual(args.hooks_directory, ['/foo/bar'])

    def test_hooks_directory_multiple(self):
        args = parseargs(
            ['snap', '--hooks-directory', '/foo/bar,/foo/baz,~/bar',
             'model.assertion'])
        self.assertListEqual(
            args.hooks_directory, ['/foo/bar', '/foo/baz', '~/bar'])

    def test_classic_gadget_tree_required(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['classic'])
        line = stderr.getvalue()
        self.assertIn('gadget tree is required', line)

    def test_classic_project_or_filesystem_required(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['classic', 'tree_url'])
        line = stderr.getvalue()
        self.assertIn('project or filesystem is required', line)

    def test_classic_project_and_filesystem_exclusive(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['classic', 'tree_url', '--project',
                               'ubuntu-cpc', '--filesystem', 'fsdir'])
        line = stderr.getvalue()
        self.assertIn('project and filesystem are mutually exclusive', line)

    def test_classic_resume_gadget_tree(self):
        stderr = StringIO()
        with patch('sys.stderr', stderr):
            self.assertRaises(SystemExit,
                              parseargs,
                              ['classic', '--resume', 'tree_url'])
        line = stderr.getvalue()
        self.assertIn('gadget tree is not allowed with --resume', line)


class TestMain(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Capture builtin print() output.
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._resources.enter_context(
            patch('argparse._sys.stdout', self._stdout))
        # Capture stderr since this is where argparse will spew to.
        self._resources.enter_context(
            patch('argparse._sys.stderr', self._stderr))

    def test_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--help',))
        self.assertEqual(cm.exception.code, 0)
        lines = self._stdout.getvalue().splitlines()
        self.assertTrue(lines[0].startswith('Usage'),
                        lines[0])
        self.assertTrue(lines[1].startswith('  ubuntu-image'),
                        lines[1])

    def test_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                EarlyExitModelAssertionBuilder))
            # Prevent actual main() from running.
            resources.enter_context(patch('ubuntu_image.__main__.main'))
            code = main(('--debug', 'model.assertion'))
        self.assertEqual(code, 0)
        mock.assert_called_once_with(level=logging.DEBUG)

    def test_no_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                EarlyExitModelAssertionBuilder))
            # Prevent actual main() from running.
            resources.enter_context(patch('ubuntu_image.__main__.main'))
            code = main(('model.assertion',))
        self.assertEqual(code, 0)
        mock.assert_not_called()

    def test_state_machine_exception(self):
        with ExitStack() as resources:
            resources.enter_context(patch(
                'ubuntu_image.__main__.ModelAssertionBuilder',
                CrashingModelAssertionBuilder))
            mock = resources.enter_context(patch(
                'ubuntu_image.__main__._logger.exception'))
            code = main(('model.assertion',))
            self.assertEqual(code, 1)
            self.assertEqual(
                mock.call_args_list[-1], call('Crash in state machine'))

    def test_state_machine_snap_command_fails(self):
        # The `snap prepare-image` command fails and main exits with non-zero.
        #
        # This tests needs to run the actual snap() helper function, not
        # the testsuite-wide mock.  This is appropriate since we're
        # mocking it ourselves here.
        if NosePlugin.snap_mocker is not None:
            NosePlugin.snap_mocker.patcher.stop()
            self._resources.callback(NosePlugin.snap_mocker.patcher.start)
        self._resources.enter_context(patch(
            'ubuntu_image.helpers.subprocess_run',
            return_value=SimpleNamespace(
                returncode=1,
                stdout='command stdout',
                stderr='command stderr',
                check_returncode=check_returncode,
                )))
        self._resources.enter_context(LogCapture())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            XXXModelAssertionBuilder))
        workdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(workdir, 'my-disk.img')
        code = main(('--until', 'prepare_filesystems',
                     '--channel', 'edge',
                     '--workdir', workdir,
                     '--output', imgfile,
                     'model.assertion'))
        self.assertEqual(code, 1)

    def test_no_arguments(self):
        with self.assertRaises(SystemExit) as cm:
            main(())
        self.assertEqual(cm.exception.code, 2)
        lines = self._stderr.getvalue().splitlines()
        self.assertTrue(
                lines[0].startswith('Warning: for backwards compatibility'),
                lines[0])
        self.assertTrue(lines[1], 'Usage:')
        self.assertEqual(
                lines[2],
                '  ubuntu-image COMMAND [OPTIONS]...')

    def test_with_none(self):
        with self.assertRaises(SystemExit) as cm:
            main((None))    # code coverage __main__.py 308-309
        self.assertEqual(cm.exception.code, 2)

    def test_snap_subcommand_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(('snap', '--help',))
        self.assertEqual(cm.exception.code, 0)
        lines = self._stdout.getvalue().splitlines()
        self.assertTrue(
              lines[0].startswith('usage: ubuntu-image snap'),
              lines[0])

    def test_classic_subcommand_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(('classic', '--help',))
        self.assertEqual(cm.exception.code, 0)
        lines = self._stdout.getvalue().splitlines()
        self.assertTrue(
              lines[0].startswith('usage: ubuntu-image classic'),
              lines[0])


class TestMainWithGadget(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Capture builtin print() output.
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._resources.enter_context(
            patch('argparse._sys.stdout', self._stdout))
        # Capture stderr since this is where argparse will spew to.
        self._resources.enter_context(
            patch('argparse._sys.stderr', self._stderr))
        # Set up a few other useful things for these tests.
        self._resources.enter_context(
            patch('ubuntu_image.__main__.logging.basicConfig'))
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')
        self.classic_gadget_tree = resource_filename(
            'ubuntu_image.tests.data', 'gadget_tree')

    def test_output_without_subcommand(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(tmpdir, 'my-disk.img')
        self.assertFalse(os.path.exists(imgfile))
        main(('--output', imgfile, self.model_assertion))
        self.assertTrue(os.path.exists(imgfile))

    def test_output(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(tmpdir, 'my-disk.img')
        self.assertFalse(os.path.exists(imgfile))
        main(('snap', '--output', imgfile, self.model_assertion))
        self.assertTrue(os.path.exists(imgfile))

    def test_output_directory(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        outputdir = os.path.join(tmpdir, 'images')
        main(('snap', '--output-dir', outputdir, self.model_assertion))
        self.assertTrue(os.path.exists(os.path.join(outputdir, 'pc.img')))

    def test_output_directory_multiple_images(self):
        class Builder(DoNothingBuilder):
            gadget_yaml = 'gadget-multi.yaml'
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            Builder))
        # Quiet the test suite.
        self._resources.enter_context(patch(
            'ubuntu_image.parser._logger.warning'))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        outputdir = os.path.join(tmpdir, 'images')
        main(('snap', '-O', outputdir, self.model_assertion))
        for name in ('first', 'second', 'third', 'fourth'):
            image_path = os.path.join(outputdir, '{}.img'.format(name))
            self.assertTrue(os.path.exists(image_path))

    def test_output_directory_multiple_images_image_file_list(self):
        class Builder(DoNothingBuilder):
            gadget_yaml = 'gadget-multi.yaml'
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            Builder))
        # Quiet the test suite.
        self._resources.enter_context(patch(
            'ubuntu_image.parser._logger.warning'))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        outputdir = os.path.join(tmpdir, 'images')
        image_file_list = os.path.join(tmpdir, 'ifl.txt')
        main(('snap', '-O', outputdir,
              '--image-file-list', image_file_list,
              self.model_assertion))
        with open(image_file_list, 'r', encoding='utf-8') as fp:
            img_files = set(line.rstrip() for line in fp.readlines())
        self.assertEqual(
            img_files,
            set(os.path.join(outputdir, '{}.img'.format(filename))
                for filename in ('first', 'second', 'third', 'fourth'))
            )

    def test_output_image_file_list(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        # Quiet the test suite.
        self._resources.enter_context(patch(
            'ubuntu_image.parser._logger.warning'))
        tmpdir = self._resources.enter_context(TemporaryDirectory())
        output = os.path.join(tmpdir, 'pc.img')
        image_file_list = os.path.join(tmpdir, 'ifl.txt')
        main(('snap', '-o', output,
              '--image-file-list', image_file_list,
              self.model_assertion))
        with open(image_file_list, 'r', encoding='utf-8') as fp:
            img_files = set(line.rstrip() for line in fp.readlines())
        self.assertEqual(img_files, {output})

    def test_tmp_okay_for_classic_snap(self):
        # For reference see:
        # http://snapcraft.io/docs/reference/env
        self._resources.enter_context(envar('SNAP_NAME', 'crack-pop'))
        self._resources.enter_context(chdir('/tmp'))
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        code = main(('snap', '--output-dir', '/tmp/images',
                     '--extra-snaps', '/tmp/extra.snap',
                     '/tmp/model.assertion'))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists('/tmp/images/pc.img'))

    def test_resume_and_model_assertion(self):
        with self.assertRaises(SystemExit) as cm:
            main(('snap', '--resume', self.model_assertion))
        self.assertEqual(cm.exception.code, 2)

    def test_resume_and_model_assertion_without_subcommand(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--resume', self.model_assertion))
        self.assertEqual(cm.exception.code, 2)

    def test_no_resume_and_no_model_assertion(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--until', 'whatever'))
        self.assertEqual(cm.exception.code, 2)

    def test_resume_without_workdir(self):
        with self.assertRaises(SystemExit) as cm:
            main(('snap', '--resume'))
        self.assertEqual(cm.exception.code, 2)

    def test_resume_without_workdir_without_subcommand(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--resume',))
        self.assertEqual(cm.exception.code, 2)

    def test_resume_and_gadget_tree(self):
        with self.assertRaises(SystemExit) as cm:
            main(('classic', '--resume', self.classic_gadget_tree))
        self.assertEqual(cm.exception.code, 2)

    def test_no_resume_and_no_gadget_tree(self):
        with self.assertRaises(SystemExit) as cm:
            main(('classic', '--until', 'whatever'))
        self.assertEqual(cm.exception.code, 2)

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_save_resume(self):
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            XXXModelAssertionBuilder))
        workdir = self._resources.enter_context(TemporaryDirectory())
        imgfile = os.path.join(workdir, 'my-disk.img')
        main(('--until', 'prepare_filesystems',
              '--channel', 'edge',
              '--workdir', workdir,
              '--output', imgfile,
              self.model_assertion))
        self.assertTrue(os.path.exists(os.path.join(
            workdir, '.ubuntu-image.pck')))
        self.assertFalse(os.path.exists(imgfile))
        main(('snap', '--resume', '--workdir', workdir))
        self.assertTrue(os.path.exists(imgfile))

    def test_until(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        main(('snap', '--until', 'populate_rootfs_contents',
              '--channel', 'edge',
              '--workdir', workdir,
              self.model_assertion))
        # The pickle file will tell us how far the state machine got.
        with open(os.path.join(workdir, '.ubuntu-image.pck'), 'rb') as fp:
            pickle_state = load(fp).__getstate__()
        # This is the *next* state to execute.
        self.assertEqual(pickle_state['state'], ['populate_rootfs_contents'])

    def test_thru(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        main(('snap', '--thru', 'populate_rootfs_contents',
              '--workdir', workdir,
              '--channel', 'edge',
              self.model_assertion))
        # The pickle file will tell us how far the state machine got.
        with open(os.path.join(workdir, '.ubuntu-image.pck'), 'rb') as fp:
            pickle_state = load(fp).__getstate__()
        # This is the *next* state to execute.
        self.assertEqual(
            pickle_state['state'], ['populate_rootfs_contents_hooks'])

    def test_resume_loads_pickle_snap(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            EarlyExitLeaveATraceAssertionBuilder))
        main(('snap', '--until', 'prepare_image',
              '--workdir', workdir,
              self.model_assertion))
        self.assertFalse(os.path.exists(os.path.join(workdir, 'success')))
        main(('--workdir', workdir, '--resume'))
        self.assertTrue(os.path.exists(os.path.join(workdir, 'success')))

    def test_resume_loads_pickle_classic(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ClassicBuilder',
            EarlyExitLeaveATraceClassicBuilder))
        self._resources.enter_context(
            patch('ubuntu_image.classic_builder.check_root_privilege'))
        main(('classic', '--until', 'prepare_image',
              '--workdir', workdir,
              '--project', 'ubuntu-cpc',
              self.classic_gadget_tree))
        self.assertFalse(os.path.exists(os.path.join(workdir, 'success')))
        main(('--workdir', workdir, '--resume'))
        self.assertTrue(os.path.exists(os.path.join(workdir, 'success')))

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_does_not_fit(self):
        # The contents of a structure is too large for the image size.
        workdir = self._resources.enter_context(TemporaryDirectory())
        # See LP: #1666580
        main(('snap', '--workdir', workdir,
              '--thru', 'load_gadget_yaml',
              self.model_assertion))
        # Make the gadget's mbr contents too big.
        path = os.path.join(workdir, 'unpack', 'gadget', 'pc-boot.img')
        os.truncate(path, 512)
        mock = self._resources.enter_context(patch(
            'ubuntu_image.__main__._logger.error'))
        code = main(('snap', '--workdir', workdir, '--resume'))
        self.assertEqual(code, 1)
        self.assertEqual(
            mock.call_args_list[-1],
            call('Volume contents do not fit (72B over): '
                 'volumes:<pc>:structure:<mbr> [#0]'))

    def test_classic_not_privileged(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ClassicBuilder',
            EarlyExitLeaveATraceClassicBuilder))
        self._resources.enter_context(
            patch('os.geteuid', return_value=1))
        self._resources.enter_context(
            patch('pwd.getpwuid', return_value=['test']))
        mock = self._resources.enter_context(patch(
            'ubuntu_image.__main__._logger.error'))
        code = main(('classic', '--workdir', workdir,
                     '--project', 'ubuntu-cpc',
                     self.classic_gadget_tree))
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(workdir, 'success')))
        self.assertEqual(
            mock.call_args_list[-1],
            call('Current user(test) does not have root privilege to build '
                 'classic image. Please run ubuntu-image as root.'))

    def test_classic_cross_build_no_static(self):
        # We need to check that a DependencyError is raised when
        # find_executable does not find the qemu-<ARCH>-static binary in
        # PATH (and no path env is set)
        workdir = self._resources.enter_context(TemporaryDirectory())
        livecd_rootfs = self._resources.enter_context(TemporaryDirectory())
        auto = os.path.join(livecd_rootfs, 'auto')
        os.mkdir(auto)
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ClassicBuilder',
            CallLBLeaveATraceClassicBuilder))
        self._resources.enter_context(
            envar('UBUNTU_IMAGE_LIVECD_ROOTFS_AUTO_PATH', auto))
        self._resources.enter_context(
            patch('ubuntu_image.helpers.run', return_value=None))
        self._resources.enter_context(
            patch('ubuntu_image.helpers.find_executable', return_value=None))
        self._resources.enter_context(
            patch('ubuntu_image.helpers.get_host_arch',
                  return_value='amd64'))
        self._resources.enter_context(
            patch('ubuntu_image.__main__.get_host_distro',
                  return_value='bionic'))
        self._resources.enter_context(
            patch('ubuntu_image.classic_builder.check_root_privilege',
                  return_value=None))
        mock = self._resources.enter_context(patch(
            'ubuntu_image.__main__._logger.error'))
        code = main(('classic', '--workdir', workdir,
                     '--project', 'ubuntu-cpc', '--arch', 'armhf',
                     self.classic_gadget_tree))
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(workdir, 'success')))
        self.assertEqual(
            mock.call_args_list[-1],
            call('Required dependency qemu-arm-static seems to be missing. '
                 'Use UBUNTU_IMAGE_QEMU_USER_STATIC_PATH in case of '
                 'non-standard archs or custom paths.'))

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without sudo access (builder environment)')
    def test_hook_fired(self):
        # For the purpose of testing, we will be using the post-populate-rootfs
        # hook as we made sure it's still executed as part of of the
        # DoNothingBuilder.
        hookdir = self._resources.enter_context(TemporaryDirectory())
        hookfile = os.path.join(hookdir, 'post-populate-rootfs')
        # Let's make sure that, with the use of post-populate-rootfs, we can
        # modify the rootfs contents.
        with open(hookfile, 'w') as fp:
            fp.write("""\
#!/bin/sh
echo "[MAGIC_STRING_FOR_U-I_HOOKS]" > $UBUNTU_IMAGE_HOOK_ROOTFS/foo
""")
        os.chmod(hookfile, 0o744)
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        code = main(('--hooks-directory', hookdir,
                     '--workdir', workdir,
                     '--output-dir', workdir,
                     self.model_assertion))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(workdir, 'root', 'foo')))
        imagefile = os.path.join(workdir, 'pc.img')
        self.assertTrue(os.path.exists(imagefile))
        # Map the image and grep through it to see if our hook change actually
        # landed in the final image.
        with open(imagefile, 'r+b') as fp:
            m = self._resources.enter_context(mmap(fp.fileno(), 0))
            self.assertGreaterEqual(m.find(b'[MAGIC_STRING_FOR_U-I_HOOKS]'), 0)

    def test_hook_error(self):
        # For the purpose of testing, we will be using the post-populate-rootfs
        # hook as we made sure it's still executed as part of of the
        # DoNothingBuilder.
        hookdir = self._resources.enter_context(TemporaryDirectory())
        hookfile = os.path.join(hookdir, 'post-populate-rootfs')
        with open(hookfile, 'w') as fp:
            fp.write("""\
#!/bin/sh
echo -n "Failed" 1>&2
return 1
""")
        os.chmod(hookfile, 0o744)
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        mock = self._resources.enter_context(patch(
            'ubuntu_image.__main__._logger.error'))
        code = main(('--hooks-directory', hookdir, self.model_assertion))
        self.assertEqual(code, 1)
        self.assertEqual(
            mock.call_args_list[-1],
            call('Hook script in path {} failed for the post-populate-rootfs '
                 'hook with return code 1. Output of stderr:\nFailed'.format(
                    hookfile)))

    def test_hook_fired_after_resume(self):
        # For the purpose of testing, we will be using the post-populate-rootfs
        # hook as we made sure it's still executed as part of of the
        # DoNothingBuilder.
        hookdir = self._resources.enter_context(TemporaryDirectory())
        hookfile = os.path.join(hookdir, 'post-populate-rootfs')
        with open(hookfile, 'w') as fp:
            fp.write("""\
#!/bin/sh
touch {}/success
""".format(hookdir))
        os.chmod(hookfile, 0o744)
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            DoNothingBuilder))
        main(('--until', 'prepare_image',
              '--hooks-directory', hookdir,
              '--workdir', workdir,
              self.model_assertion))
        self.assertFalse(os.path.exists(os.path.join(hookdir, 'success')))
        # Check if after a resume the hook path is still correct and the hooks
        # are fired as expected.
        code = main(('--workdir', workdir, '--resume'))
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(hookdir, 'success')))

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_hook_official_support(self):
        # This test is responsible for checking if all the officially declared
        # hooks are called as intended, making sure none get dropped by
        # accident.
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            XXXModelAssertionBuilder))
        fire_mock = self._resources.enter_context(patch(
            'ubuntu_image.hooks.HookManager.fire'))
        code = main(('--channel', 'edge', self.model_assertion))
        self.assertEqual(code, 0)
        called_hooks = [x[0][0] for x in fire_mock.call_args_list]
        self.assertListEqual(called_hooks, supported_hooks)


class TestMainWithBadGadget(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_bad_gadget_log(self):
        log = self._resources.enter_context(LogCapture())
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            BadGadgetModelAssertionBuilder))
        main(('snap', '--channel', 'edge',
              '--workdir', workdir,
              self.model_assertion))
        self.assertEqual(log.logs, [
            (logging.ERROR, 'gadget.yaml parse error: '
                            'GUID structure type with non-GPT schema'),
            (logging.ERROR, 'Use --debug for more information')
            ])

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_bad_gadget_debug_log(self):
        log = self._resources.enter_context(LogCapture())
        workdir = self._resources.enter_context(TemporaryDirectory())
        self._resources.enter_context(patch(
            'ubuntu_image.__main__.ModelAssertionBuilder',
            BadGadgetModelAssertionBuilder))
        main(('snap', '--debug',
              '--workdir', workdir,
              '--channel', 'edge',
              self.model_assertion))
        self.assertEqual(log.logs, [
            (logging.ERROR, 'uncaught exception in state machine step: '
                            '[3] load_gadget_yaml'),
            'IMAGINE THE TRACEBACK HERE',
            (logging.ERROR, 'gadget.yaml parse error'),
            'IMAGINE THE TRACEBACK HERE',
            ])
