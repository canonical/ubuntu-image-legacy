"""Test image building."""

import os
import re
import shutil

from contextlib import ExitStack
from itertools import product
from pickle import dumps, loads
from pkg_resources import resource_filename
from subprocess import CompletedProcess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.helpers import MiB, run
from ubuntu_image.testing.helpers import (
    DoNothingBuilder, IN_TRAVIS, XXXModelAssertionBuilder)
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
COMMASPACE = ', '


# For convenience.
def utf8open(path):
    return open(path, 'r', encoding='utf-8')


@skipIf(True, 'No BaseImageBuilder')
class TestBaseImageBuilder(TestCase):
    maxDiff = None

    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)

    def test_rootfs(self):
        with BaseImageBuilder() as state:
            state.run_thru('calculate_rootfs_size')
            self.assertEqual(
                set(os.listdir(state.rootfs)),
                {'foo', 'bar', 'boot', 'baz'})
            self.assertTrue(os.path.isdir(os.path.join(state.rootfs, 'baz')))
            self.assertTrue(os.path.isdir(os.path.join(state.rootfs, 'boot')))
            self.assertEqual(
                set(os.listdir(os.path.join(state.rootfs, 'baz'))),
                {'buz'})
            self.assertEqual(
                len(os.listdir(os.path.join(state.rootfs, 'boot'))),
                0)
            path = os.path.join(state.rootfs, 'foo')
            with utf8open(os.path.join(state.rootfs, path)) as fp:
                self.assertEqual(fp.read(), 'this is foo')
            with utf8open(os.path.join(state.rootfs, 'bar')) as fp:
                self.assertEqual(fp.read(), 'this is bar')
            with utf8open(os.path.join(state.rootfs, 'baz', 'buz')) as fp:
                self.assertEqual(fp.read(), 'some bazz buzz')
            self.assertEqual(state.rootfs_size, 54)

    def test_bootfs(self):
        with BaseImageBuilder() as state:
            state.run_thru('calculate_bootfs_size')
            self.assertEqual(
                set(os.listdir(state.bootfs)),
                {'boot', 'other'})
            self.assertTrue(os.path.isdir(os.path.join(state.bootfs, 'boot')))
            self.assertEqual(
                set(os.listdir(os.path.join(state.bootfs, 'boot'))),
                {'qux', 'qay'})
            with utf8open(os.path.join(state.bootfs, 'other')) as fp:
                self.assertEqual(fp.read(), 'other')
            with utf8open(os.path.join(state.bootfs, 'boot', 'qux')) as fp:
                self.assertEqual(fp.read(), 'boot qux')
            with utf8open(os.path.join(state.bootfs, 'boot', 'qay')) as fp:
                self.assertEqual(fp.read(), 'boot qay')
            self.assertEqual(state.bootfs_size, 31.5)

    def test_workdir(self):
        workdir = self._resources.enter_context(TemporaryDirectory())
        # Enter a new context just to manage the builder's resources.
        with BaseImageBuilder(workdir=workdir) as state:
            state.run_thru('make_temporary_directories')
            self.assertEqual(state.rootfs, os.path.join(workdir, 'root'))
            self.assertEqual(state.bootfs, os.path.join(workdir, 'boot'))
            self.assertTrue(os.path.exists(state.bootfs))
            self.assertTrue(os.path.exists(state.rootfs))
        # The workdir does not get deleted after the state machine exits.
        self.assertTrue(os.path.exists(state.bootfs))
        self.assertTrue(os.path.exists(state.rootfs))

    def test_filesystems(self):
        state = self._resources.enter_context(BaseImageBuilder())
        state.run_thru('populate_filesystems')
        boot_dir = self._resources.enter_context(TemporaryDirectory())
        # The boot file system is a VFAT file system.
        run('mcopy -s -i {} :: {}'.format(state.boot_img, boot_dir),
            env=dict(MTOOLS_SKIP_CHECK='1'))
        self.assertEqual(set(os.listdir(boot_dir)), {'boot', 'other'})
        self.assertEqual(
            set(os.listdir(os.path.join(boot_dir, 'boot'))),
            {'qay', 'qux'})
        with utf8open(os.path.join(boot_dir, 'other')) as fp:
            self.assertEqual(fp.read(), 'other')
        with utf8open(os.path.join(boot_dir, 'boot', 'qux')) as fp:
            self.assertEqual(fp.read(), 'boot qux')
        with utf8open(os.path.join(boot_dir, 'boot', 'qay')) as fp:
            self.assertEqual(fp.read(), 'boot qay')
        # The root file system is an ext4 file system.
        root_dir = self._resources.enter_context(TemporaryDirectory())
        run('debugfs -R "rdump / {}" {}'.format(root_dir, state.root_img),
            shell=True)
        self.assertEqual(
            set(os.listdir(root_dir)),
            {'foo', 'bar', 'baz', 'lost+found', 'boot'})
        boot_mount = os.path.join(root_dir, 'boot')
        self.assertTrue(os.path.isdir(boot_mount))
        self.assertEqual(os.listdir(boot_mount), [])
        with utf8open(os.path.join(root_dir, 'foo')) as fp:
            self.assertEqual(fp.read(), 'this is foo')
        with utf8open(os.path.join(root_dir, 'bar')) as fp:
            self.assertEqual(fp.read(), 'this is bar')
        with utf8open(os.path.join(root_dir, 'baz', 'buz')) as fp:
            self.assertEqual(fp.read(), 'some bazz buzz')

    @skipIf(IN_TRAVIS, 'cannot mount in a docker container')
    def test_filesystems_xenial(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap prepare-image`.  Mimic what happens on Ubuntu
        # 16.04 where mkfs.ext4 does not support the -d option.
        #
        # This isn't perfectly wonderful because we really should run the
        # tests in Travis twice, once on Xenial and once on >Xenial, skipping
        # the one that isn't appropriate rather than assuming >Xenial and
        # mocking the Xenial case.
        def no_dash_d(command, *, check=True, **args):
            if command.startswith('mkfs.ext4') and '-d' in command.split():
                return CompletedProcess([], 1, '', '')
            return run(command, check=check, **args)
        self._resources.enter_context(patch(
            'ubuntu_image.builder.run', no_dash_d))
        state = self._resources.enter_context(BaseImageBuilder())
        state.run_thru('populate_filesystems')
        # The root file system is an ext4 file system.
        root_dir = self._resources.enter_context(TemporaryDirectory())
        run('debugfs -R "rdump / {}" {}'.format(root_dir, state.root_img),
            shell=True)
        self.assertEqual(
            set(os.listdir(root_dir)),
            {'foo', 'bar', 'baz', 'lost+found', 'boot'})
        boot_mount = os.path.join(root_dir, 'boot')
        self.assertTrue(os.path.isdir(boot_mount))
        self.assertEqual(os.listdir(boot_mount), [])
        with utf8open(os.path.join(root_dir, 'foo')) as fp:
            self.assertEqual(fp.read(), 'this is foo')
        with utf8open(os.path.join(root_dir, 'bar')) as fp:
            self.assertEqual(fp.read(), 'this is bar')
        with utf8open(os.path.join(root_dir, 'baz', 'buz')) as fp:
            self.assertEqual(fp.read(), 'some bazz buzz')

    def test_finish(self):
        output = self._resources.enter_context(NamedTemporaryFile())
        state = self._resources.enter_context(
            BaseImageBuilder(output=output.name))
        list(state)
        self.assertTrue(os.path.exists(output.name))
        self.assertFalse(os.path.exists(state.root_img))
        self.assertFalse(os.path.exists(state.boot_img))
        proc = run('sgdisk --print {}'.format(output.name))
        # The disk image file name and identifier (GUID) can vary so remove
        # and check those lines separate.
        stdout = proc.stdout.splitlines()
        self.assertRegex(
            stdout[0],
            'Disk [a-zA-Z0-9_/]+: 8388608 sectors, 4.0 GiB')
        self.assertRegex(
            stdout[2],
            'Disk identifier \(GUID\): [-A-Z0-9]+')
        del stdout[2]
        del stdout[0]
        self.assertMultiLineEqual(
                NL.join(stdout), """\
Logical sector size: 512 bytes
Partition table holds up to 128 entries
First usable sector is 34, last usable sector is 8388574
Partitions will be aligned on 2048-sector boundaries
Total free space is 790461 sectors (386.0 MiB)

Number  Start (sector)    End (sector)  Size       Code  Name
   2           10240          141311   64.0 MiB    EF00  system-boot
   3          147456         7614463   3.6 GiB     8300  writable""")


class TestModelAssertionBuilder(TestCase):
    # XXX These tests relies on external resources, namely that the gadget and
    # kernel snaps in this model assertion can actually be downloaded from the
    # real store.  That's a test isolation bug and a potential source of test
    # brittleness.  We should fix this.
    #
    # XXX These tests also requires root, because `snap prepare-image`
    # currently requires it.  mvo says this will be fixed.

    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')

    @skipIf(IN_TRAVIS, 'cannot mount in a docker container')
    def test_fs_contents(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap prepare-image`.
        output = self._resources.enter_context(NamedTemporaryFile())
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            output=output,
            model_assertion=self.model_assertion,
            )
        state = self._resources.enter_context(XXXModelAssertionBuilder(args))
        state.run_thru('calculate_bootfs_size')
        # How does the root and boot file systems look?
        files = [
            '{boot}/EFI/boot/bootx64.efi',
            '{boot}/EFI/boot/grub.cfg',
            '{boot}/EFI/boot/grubx64.efi',
            '{boot}/EFI/ubuntu/grub.cfg',
            '{boot}/EFI/ubuntu/grubenv',
            '{root}/boot/',
            '{root}/snap/',
            ]
        for filename in files:
            path = filename.format(
                root=state.rootfs,
                boot=state.bootfs,
                )
            self.assertTrue(os.path.exists(path), path)
        # 2016-08-01 barry@ubuntu.com: Since these tests currently use real
        # data, the snap version numbers may change.  Until we use test data
        # (sideloaded) do regexp matches against specific snap file names.
        seeds_path = os.path.join(root, 'var', 'lib', 'snapd', 'seed', 'snaps')
        snaps = set(os.listdir(seeds_path))
        seed_patterns = [
            '^canonical-pc_[0-9]+.snap$',
            '^canonical-pc-linux_[0-9]+.snap.sideinfo$',
            '^canonical-pc_[0-9]+.snap.sideinfo$',
            '^ubuntu-core_[0-9]+.snap$',
            '^canonical-pc-linux_[0-9]+.snap$',
            '^ubuntu-core_[0-9]+.snap.sideinfo$',
            '^canonical-pc-linux_[0-9]+.snap$',
            '^ubuntu-core_[0-9]+.snap$',
            ]
        # Make sure every file matches a pattern and every pattern matches a
        # file.
        patterns_matched = set()
        files_matched = set()
        matches = []
        for pattern, snap in product(seed_patterns, snaps):
            if pattern in patterns_matched or snap in files_matched:
                continue
            if re.match(pattern, snap):
                matches.append((pattern, snap))
                patterns_matched.add(pattern)
                files_matched.add(snap)
        patterns_unmatched = set(seed_patterns) - patterns_matched
        files_unmatched = snaps - files_matched
        self.assertEqual(
            len(patterns_unmatched), 0,
            'Unmatched patterns: {}'.format(COMMASPACE.join(
                patterns_unmatched)))
        self.assertEqual(
            len(files_unmatched), 0,
            'Unmatched files: {}'.format(COMMASPACE.join(files_unmatched)))

    def test_no_workdir_exception(self):
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with XXXModelAssertionBuilder(args) as state:
            state.run_until('make_temporary_directories')
        pickle_data = dumps(state)
        self.assertRaises(FileNotFoundError, loads, pickle_data)

    def test_make_disk_no_dos_partitions_yet(self):
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.gadget = SimpleNamespace(scheme='MBR')
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.make_disk)
            # Be quiet.
            resources.enter_context(patch('ubuntu_image.state.log.exception'))
            cm = resources.enter_context(self.assertRaises(ValueError))
            list(state)
            self.assertEqual(str(cm.exception),
                             'DOS partition tables not yet supported')


class TestShortCircuitBuilder(TestCase):
    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        self._workdir = self._resources.enter_context(TemporaryDirectory())
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')
        self.args = SimpleNamespace(
            channel='edge',
            workdir=self._workdir,
            model_assertion=self.model_assertion,
            output=None,
            )

    def test_save_restore(self):
        # Create a short-circuited state machine we can jump right to.
        state = self._resources.enter_context(DoNothingBuilder(self.args))
        state._next.pop()
        state._next.append(state.calculate_rootfs_size)
        state.rootfs = os.path.join(self._workdir, 'rootfs')
        os.makedirs(state.rootfs)
        with open(os.path.join(state.rootfs, 'dummy'), 'wb') as fp:
            fp.write(b'x' * 150)
        pickle_data = dumps(state)
        self.assertEqual(state.rootfs_size, 0)
        with loads(pickle_data) as new_state:
            next(new_state)
        # 150 * 1.5
        self.assertEqual(new_state.rootfs_size, 225)

    def test_load_gadget_yaml(self):
        state = self._resources.enter_context(DoNothingBuilder(self.args))
        state._next.pop()
        state._next.append(state.load_gadget_yaml)
        metadir = os.path.join(state.rootfs, 'gadget', 'meta')
        os.makedirs(metadir)
        shutil.copy(
            resource_filename('ubuntu_image.tests.data', 'image.yaml'),
            os.path.join(metadir, 'image.yaml'))
        self.assertIsNone(state.gadget)
        next(state)
        self.assertIsNotNone(state.gadget)
        self.assertEqual(state.gadget.partitions[0].size, MiB(50))
