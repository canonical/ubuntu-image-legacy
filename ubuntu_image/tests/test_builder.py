"""Test image building."""

import os
import re
import json
import logging

from contextlib import ExitStack
from itertools import product
from pkg_resources import resource_filename
from shutil import SpecialFileError
from struct import unpack
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.helpers import DoesNotFit, MiB, run
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole, VolumeSchema)
from ubuntu_image.testing.helpers import (
    LogCapture, XXXModelAssertionBuilder, envar)
from ubuntu_image.testing.nose import NosePlugin
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
COMMASPACE = ', '


# For convenience.
def utf8open(path):
    return open(path, 'r', encoding='utf-8')


# For forcing a test failure.
def check_returncode(*args, **kws):
    raise CalledProcessError(1, 'failing command')


def prep_state(state, workdir, part_images=None):
    # For tests which don't run the full state machine, we need to reproduce
    # enough of the state for the individual test.
    state.volumedir = os.path.join(workdir, 'volumes')
    for name, volume in state.gadget.volumes.items():
        basedir = os.path.join(state.volumedir, name)
        volume.basedir = basedir
        os.makedirs(basedir, exist_ok=True)
        volume.part_images = [] if part_images is None else part_images


def make_content_at(pdir, content):
    # Generate content tree at given pdir location.
    for where, what in content.items():
        wpath = os.path.join(pdir, where)
        os.makedirs(os.path.dirname(wpath), exist_ok=True)
        with open(wpath, 'wb') as fp:
            fp.write(what)


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

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_fs_contents(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap prepare-image`.
        output = self._resources.enter_context(NamedTemporaryFile())
        args = SimpleNamespace(
            channel='edge',
            cloud_init=None,
            debug=False,
            snap=None,
            extra_snaps=None,
            model_assertion=self.model_assertion,
            output=output.name,
            output_dir=None,
            workdir=None,
            hooks_directory=[],
            disk_info=None,
            disable_console_conf=False,
            )
        state = self._resources.enter_context(XXXModelAssertionBuilder(args))
        state.run_thru('populate_bootfs_contents')
        # How does the root and boot file systems look?
        files = [
            '{boot}/EFI/boot/bootx64.efi',
            '{boot}/EFI/boot/grub.cfg',
            '{boot}/EFI/boot/grubx64.efi',
            '{boot}/EFI/ubuntu/grubenv',
            '{root}/system-data/boot/',
            ]
        for filename in files:
            path = filename.format(
                root=state.rootfs,
                boot=state.gadget.volumes['pc'].bootfs,
                )
            self.assertTrue(os.path.exists(path), path)
        # 2016-08-01 barry@ubuntu.com: Since these tests currently use real
        # data, the snap version numbers may change.  Until we use test data
        # (sideloaded) do regexp matches against specific snap file names.
        seeds_path = os.path.join(
            state.rootfs, 'system-data',
            'var', 'lib', 'snapd', 'seed', 'snaps')
        snaps = set(os.listdir(seeds_path))
        seed_patterns = [
            '^pc-kernel_[0-9]+.snap$',
            '^pc_[0-9]+.snap$',
            # This snap's name is undergoing transition.
            '^(ubuntu-)?core_[0-9]+.snap$',
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
            (len(patterns_unmatched), len(files_unmatched)),
            (0, 0),
            'Unmatched patterns: {}\nUnmatched files: {}'.format(
                COMMASPACE.join(patterns_unmatched),
                COMMASPACE.join(files_unmatched)))

    def test_populate_rootfs_contents_without_cloud_init(self):
        with ExitStack() as resources:
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', flush=True, file=cloud_init)
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # The user data should not have been written and there should be
            # no metadata either.
            seed_path = os.path.join(
                state.rootfs,
                'system-data', 'var', 'lib', 'cloud', 'seed', 'nocloud-net')
            self.assertFalse(os.path.exists(
                os.path.join(seed_path, 'user-data')))
            self.assertFalse(os.path.exists(
                os.path.join(seed_path, 'meta-data')))

    def test_populate_rootfs_contents_with_cloud_init(self):
        with ExitStack() as resources:
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', flush=True, file=cloud_init)
            args = SimpleNamespace(
                channel='edge',
                cloud_init=cloud_init.name,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Both the user data and the seed metadata should exist.
            seed_path = os.path.join(
                state.rootfs,
                'system-data', 'var', 'lib', 'cloud', 'seed', 'nocloud-net')
            user_data = os.path.join(seed_path, 'user-data')
            meta_data = os.path.join(seed_path, 'meta-data')
            with open(user_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'cloud init user data')
            with open(meta_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'instance-id: nocloud-static\n')

    def test_populate_rootfs_contents_with_etc_and_stuff(self):
        # LP: #1632134
        with ExitStack() as resources:
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            for subdir in ('var/lib/foo', 'etc', 'stuff', 'boot', 'home'):
                path = os.path.join(image_dir, subdir)
                os.makedirs(path)
                # Throw a sentinel data file in the subdirectory.
                with open(os.path.join(path, 'sentinel.dat'), 'wb') as fp:
                    fp.write(b'x' * 25)
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Everything except /boot and /home got copied.
            for subdir in ('var/lib/foo', 'etc', 'stuff', 'home'):
                path = os.path.join(state.rootfs, 'system-data', subdir)
                with open(os.path.join(path, 'sentinel.dat'), 'rb') as fp:
                    self.assertEqual(fp.read(), b'x' * 25)
            # But these directories did not get copied.
            boot = os.path.join(state.rootfs, 'boot')
            self.assertFalse(os.path.exists(boot))

    def test_populate_rootfs_contents_with_etc_and_stuff_uc20(self):
        with ExitStack() as resources:
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'system-seed')
            for subdir in ('var/lib/foo', 'etc', 'stuff', 'boot', 'home'):
                path = os.path.join(image_dir, subdir)
                os.makedirs(path)
                # Throw a sentinel data file in the subdirectory.
                with open(os.path.join(path, 'sentinel.dat'), 'wb') as fp:
                    fp.write(b'x' * 25)
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # Note that "seeded=True" here which means its a uc20 layout
            state.gadget = SimpleNamespace(seeded=True)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Everything got copied (i.e. /boot too) into the rootfs,
            # no system-data prefix
            for subdir in ('var/lib/foo', 'etc', 'stuff', 'boot'):
                path = os.path.join(state.rootfs,  subdir)
                with open(os.path.join(path, 'sentinel.dat'), 'rb') as fp:
                    self.assertEqual(fp.read(), b'x' * 25)

    def test_populate_rootfs_contents_remove_empty_etc_cloud(self):
        with ExitStack() as resources:
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'etc', 'cloud'))
            with open(os.path.join(image_dir, 'etc',
                                   'sentinel.dat'), 'wb') as fp:
                fp.write(b'x' * 25)
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Make sure the empty /etc/cloud has not been copied, but all other
            # etc contents did.
            etc_cloud = os.path.join(
                state.rootfs, 'system-data', 'etc', 'cloud')
            self.assertFalse(os.path.exists(etc_cloud))
            etc_sentinel = os.path.join(
                state.rootfs, 'system-data', 'etc', 'sentinel.dat')
            self.assertTrue(os.path.exists(etc_sentinel))

    def test_populate_rootfs_contents_keep_nonempty_etc_cloud(self):
        with ExitStack() as resources:
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            src_cloud = os.path.join(image_dir, 'etc', 'cloud')
            os.makedirs(src_cloud)
            with open(os.path.join(src_cloud, 'sentinel.dat'), 'wb') as fp:
                fp.write(b'x' * 25)
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Make sure the non-empty /etc/cloud directory got carried over.
            etc_sentinel = os.path.join(
                state.rootfs, 'system-data', 'etc', 'cloud', 'sentinel.dat')
            self.assertTrue(os.path.exists(etc_sentinel))

    def test_populate_rootfs_correct_path_for_seeded(self):
        with ExitStack() as resources:
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', flush=True, file=cloud_init)
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            seed_dir = os.path.join(state.unpackdir, 'system-seed')
            os.makedirs(os.path.join(seed_dir, 'snap'))
            os.makedirs(os.path.join(seed_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=True)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Check if the rootfs contents have been copied to the expected
            # directory.
            self.assertFalse(os.path.exists(
                os.path.join(state.rootfs, 'system-data')))
            self.assertTrue(os.path.exists(
                os.path.join(state.rootfs, 'snap')))
            self.assertTrue(os.path.exists(
                os.path.join(state.rootfs, 'var')))

    def test_bootloader_options_uboot(self):
        # This test provides coverage for populate_bootfs_contents() when the
        # uboot bootloader is used.  The live gadget snap (only tested when we
        # have network connectivity to the store, but good enough for now)
        # uses the grub bootloader and covers that path.
        #
        # We don't want to run the entire state machine just for this test, so
        # we start by setting up enough of the environment for the method
        # under test to function.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.uboot,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            # Run the method, the testable effects of which copy all the files
            # in the boot directory (i.e. <unpackdir>/image/boot/uboot) into
            # the 'ubuntu' directory (i.e. <workdir>/part0).  So put some
            # contents into the source directory.
            src = os.path.join(unpackdir, 'image', 'boot', 'uboot')
            os.makedirs(src)
            with open(os.path.join(src, '1.dat'), 'wb') as fp:
                fp.write(b'01234')
            with open(os.path.join(src, '2.dat'), 'wb') as fp:
                fp.write(b'56789')
            next(state)
            # Did the boot data get copied?
            volume1_dir = os.path.join(state.volumedir, 'volume1')
            with open(os.path.join(volume1_dir, 'part0', '1.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(volume1_dir, 'part0', '2.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'56789')

    def test_bootloader_options_invalid(self):
        # This test provides coverage for populate_bootfs_contents() when the
        # bootloader has a bogus value.
        #
        # We don't want to run the entire state machine just for this test, so
        # we start by setting up enough of the environment for the method
        # under test to function.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader='bogus',
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            # Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(ValueError) as cm:
                next(state)
            self.assertEqual(
                str(cm.exception),
                'Unsupported volume bootloader value: bogus')

    def test_populate_bootfs_contents(self):
        # This test provides coverage for populate_bootfs_contents() when a
        # volume's part is defined as an ext4 or vfat file system type.  In
        # that case, the part's contents are copied to the target directory.
        # There are two paths here: one where the contents are a directory and
        # the other where the contents are a file.  We can test both cases
        # here for full coverage.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.  The two paths (is-a-file and is-a-directory)
            # are differentiated by whether the source ends in a slash or not.
            # In that case, the target must also end in a slash.
            contents1 = SimpleNamespace(
                source='as.dat',
                target='at.dat',
                )
            contents2 = SimpleNamespace(
                source='bs/',
                target='bt/',
                )
            contents3 = SimpleNamespace(
                source='grub.conf',
                target='EFI/ubuntu/grub.cfg',
                )
            contents4 = SimpleNamespace(
                source='nested/',
                target='EFI/ubuntu/',
                )
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents1, contents2, contents3, contents4],
                )
            volume = SimpleNamespace(
                bootloader=BootLoader.grub,
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            prep_state(state, workdir)
            # Run the method, the testable effects of which copy all the files
            # in the source directory (i.e. <unpackdir>/gadget/<source>) into
            # the target directory (i.e. <workdir>/part0).  So put some
            # contents into the source locations.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            gadget_content = {
                'as.dat': b'01234',
                'bs/c.dat': b'56789',
                # Put a couple of files and a directory in the source, since
                # directories are copied recursively.
                'bs/d/e.dat': b'0abcd',
                # Generate part of the gadget
                'grub.conf': b'from-gadget',
                # And some content to check collision/overwrite handling
                'nested/very/nested.cfg': b'from-gadget',
                'nested/very/nested-only-gadget.cfg': b'from-gadget',
                'nested/very/much/much.cfg': b'from-gadget',
                'nested/1': b'from-gadget',
                'nested/2': b'from-gadget',
            }
            make_content_at(gadget_dir, gadget_content)
            # While we're at it, also make sure the grub bootloader specific
            # rootfs files are moved to the right places as well.
            boot_dir = os.path.join(state.unpackdir, 'image', 'boot', 'grub')
            os.makedirs(boot_dir)
            # When those files get generated by snap prepare-image, they should
            # not be overwritten by copies from unpacked gadget
            boot_content = {
                'grub.cfg': b'from-image-boot-grub',
                '1': b'from-image-boot-grub',
                'very/nested.cfg': b'from-image-boot-grub',
                'very/very/nested.cfg': b'from-image-boot-grub',
            }
            make_content_at(boot_dir, boot_content)
            dstbase = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            # Run the state machine.
            next(state)
            expected_content = {
                # Did all the files and directories get copied with the right
                # names?
                'at.dat': b'01234',
                'bt/c.dat': b'56789',
                'bt/d/e.dat': b'0abcd',
                # Copied from gadget
                'EFI/ubuntu/very/nested-only-gadget.cfg': b'from-gadget',
                'EFI/ubuntu/very/much/much.cfg': b'from-gadget',
                'EFI/ubuntu/1': b'from-image-boot-grub',
                'EFI/ubuntu/2': b'from-gadget',
                # Copied from image/boot/grrub generated content, not
                # overwritten by gadget files
                'EFI/ubuntu/grub.cfg': b'from-image-boot-grub',
                'EFI/ubuntu/very/nested.cfg': b'from-image-boot-grub',
                'EFI/ubuntu/very/very/nested.cfg': b'from-image-boot-grub',
            }
            for where, what in expected_content.items():
                with open(os.path.join(dstbase, where), 'rb') as fp:
                    self.assertEqual(fp.read(), what)

    def test_populate_bootfs_contents_from_prepare_image(self):
        # This test provides coverage for populate_bootfs_contents() when
        # snap prepare-image with content resolving support is used.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem=FileSystemType.ext4,
                )
            volume = SimpleNamespace(
                bootloader=BootLoader.grub,
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            prep_state(state, workdir)
            # Run the method, the testable effects of which copy all
            # the files in the source directory. I.e.
            # <unpackdir>/resolved-content/volume1/part0/some-dir/some-file
            # into the target directory <workdir>/part0. So put some
            # contents into the source locations.
            resolved_content_dir = os.path.join(
                unpackdir, 'resolved-content/volume1/part0/')
            os.makedirs(resolved_content_dir)
            resolved_content = {
                'at.dat': b'01234',
                'bt/c.dat': b'56789',
                # Put a couple of files and a directory in the source, since
                # directories are copied recursively.
                'bt/d/e.dat': b'0abcd',
            }
            make_content_at(resolved_content_dir, resolved_content)
            dstbase = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            # Run the state machine.
            next(state)
            expected_content = {
                'at.dat': b'01234',
                'bt/c.dat': b'56789',
                'bt/d/e.dat': b'0abcd',
            }
            for where, what in expected_content.items():
                with open(os.path.join(dstbase, where), 'rb') as fp:
                    self.assertEqual(fp.read(), what)

    def test_populate_bootfs_contents_seeded(self):
        # Test populate_bootfs_contents() behavior for the system-seed
        # partition.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.  The two paths (is-a-file and is-a-directory)
            # are differentiated by whether the source ends in a slash or not.
            # In that case, the target must also end in a slash.
            contents1 = SimpleNamespace(
                source='as.dat',
                target='at.dat',
                )
            contents2 = SimpleNamespace(
                source='grub.conf',
                target='EFI/ubuntu/grub.cfg',
                )
            part0 = SimpleNamespace(
                role=StructureRole.system_seed,
                filesystem=FileSystemType.vfat,
                content=[contents1, contents2],
                )
            # This partition is unused and basically 'invalid', only exists
            # here for us to make sure it was skipped and not acted on.
            part1 = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem=FileSystemType.vfat,
                content=[contents1, contents2],
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=True,
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            prep_state(state, workdir)
            # Run the method, the testable effects of which copy all the files
            # in the source directory (i.e. <unpackdir>/gadget/<source>) into
            # the target directory.  In this case the target directory should
            # be the rootfs.
            state.rootfs = os.path.join(workdir, 'rootfs')
            os.makedirs(state.rootfs)
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            src = os.path.join(gadget_dir, 'as.dat')
            with open(src, 'wb') as fp:
                fp.write(b'01234')
            src = os.path.join(gadget_dir, 'grub.conf')
            with open(src, 'wb') as fp:
                fp.write(b'from-gadget')
            # With system-seed role being used, there is no bootloader specific
            # files, eveything is under the system-seed directory
            rootfs_grub_dir = os.path.join(state.rootfs, 'EFI', 'ubuntu')
            os.makedirs(rootfs_grub_dir)
            # When this file gets generated by snap prepare-image, it should
            # not be overwritten by copies from unpacked gadget
            src = os.path.join(rootfs_grub_dir, 'grub.cfg')
            with open(src, 'wb') as fp:
                fp.write(b'from-EFI-ubuntu')
            # Run the state machine.
            next(state)
            # Did the content copy happen as expected?
            with open(os.path.join(state.rootfs, 'at.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            # Did we get the bootloader specific copies done?
            efi_dir = os.path.join(state.rootfs, 'EFI', 'ubuntu')
            with open(os.path.join(efi_dir, 'grub.cfg'), 'rb') as fp:
                self.assertEqual(fp.read(), b'from-EFI-ubuntu')
            # Make sure the part1 dummy system-boot partition was really
            # skipped and no copies for it have been made.
            part1_path = os.path.join(workdir, 'volumes', 'volume1', 'part1')
            self.assertFalse(os.path.exists(part1_path))

    def test_populate_bootfs_contents_content_mismatch(self):
        # If a content source ends in a slash, so must the target.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.  The two paths (is-a-file and is-a-directory)
            # are differentiated by whether the source ends in a slash or not.
            # In that case, the target must also end in a slash.
            contents = SimpleNamespace(
                source='bs/',
                # No slash!
                target='bt',
                )
            part = SimpleNamespace(
                role=None,
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents],
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            prep_state(state, workdir)
            # Run the state machine.  Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(ValueError) as cm:
                next(state)
            self.assertEqual(
                str(cm.exception), 'target must end in a slash: bt')

    def test_populate_bootfs_contents_special_file(self):
        # If a content source ends in a slash, so must the target.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.  The two paths (is-a-file and is-a-directory)
            # are differentiated by whether the source ends in a slash or not.
            # In that case, the target must also end in a slash.
            contents = SimpleNamespace(
                source='bs/',
                # No slash!
                target='bt/',
                )
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents],
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            prep_state(state, workdir)
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            src = os.path.join(gadget_dir, 'bs', 'd')
            os.makedirs(src)
            os.mkfifo(os.path.join(src, 'not-a-file'))
            # Run the state machine.  Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(SpecialFileError) as cm:
                next(state)
            self.assertRegex(
                str(cm.exception), '.*/not-a-file` is a named pipe')

    def test_populate_filesystems_none_type(self):
        # We do a bit-wise copy when the file system has no type.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                cmd='snap',
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            contents2 = SimpleNamespace(
                image='image2.img',
                size=23,
                offset=None,
                )
            contents3 = SimpleNamespace(
                image='image3.img',
                size=None,
                offset=None,
                )
            contents4 = SimpleNamespace(
                image='image4.img',
                size=None,
                offset=127,
                )
            part = SimpleNamespace(
                role=None,
                filesystem=FileSystemType.none,
                content=[contents1, contents2, contents3, contents4],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                schema=VolumeSchema.gpt,
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir, [part0_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            with open(os.path.join(gadget_dir, 'image2.img'), 'wb') as fp:
                fp.write(b'\2' * 19)
            with open(os.path.join(gadget_dir, 'image3.img'), 'wb') as fp:
                fp.write(b'\3' * 51)
            with open(os.path.join(gadget_dir, 'image4.img'), 'wb') as fp:
                fp.write(b'\4' * 11)
            # Mock out the mkfs.ext4 call, and we'll just test the contents
            # directory (i.e. what would go in the ext4 file system).
            resources.enter_context(
                patch('ubuntu_image.common_builder.mkfs_ext4'))
            next(state)
            # Check the contents of the part0 image file.
            with open(part0_img, 'rb') as fp:
                data = fp.read()
            self.assertEqual(
                data,
                b'\1' * 47 +
                b'\2' * 19 +
                # 23 (specified size) - 19 (actual size).
                b'\0' * 4 +
                b'\3' * 51 +
                # 127 (offset) - 121 (written byte count)
                b'\0' * 6 +
                b'\4' * 11 +
                # 150 (image size) - 138 (written byte count)
                b'\0' * 12)

    def test_populate_filesystems_ext4_type(self):
        # We do a bit-wise copy when the file system has no type.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                cmd='snap',
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                role=None,
                filesystem=FileSystemType.ext4,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir, [part0_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Mock out the mkfs.ext4 call, and we'll just test the contents
            # directory (i.e. what would go in the ext4 file system).
            mock = resources.enter_context(
                patch('ubuntu_image.common_builder.mkfs_ext4'))
            next(state)
            # Check that mkfs.ext4 got called with the expected values.  It
            # actually got called twice, but it's only the first call
            # (i.e. the one creating the part, not the image) that we care
            # about.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            part0_path = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            self.assertEqual(
                posargs,
                # mkfs_ext4 positional arguments.
                (part0_img, part0_path, 'snap', 'hold the door'))

    def test_populate_filesystems_bogus_type(self):
        # We do a bit-wise copy when the file system has no type.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                role=None,
                filesystem=801,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir, [part0_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(AssertionError) as cm:
                next(state)
            self.assertEqual(
                str(cm.exception), 'Invalid part filesystem type: 801')

    def test_populate_filesystems_lk_bootloader(self):
        # We check that boot.img and snapbootsel.bin are copied around so
        # they can be used when creating the image from gadget.yaml.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                cmd='snap',
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                role=None,
                filesystem=FileSystemType.ext4,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.lk,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir, [part0_img])
            # Create files that should be copied to the gadget folder
            boot_dir = os.path.join(unpackdir, 'image', 'boot', 'lk')
            os.makedirs(boot_dir)
            with open(os.path.join(boot_dir, 'boot.img'), 'wb') as fp:
                fp.write(b'\1' * 10)
            with open(os.path.join(boot_dir, 'snapbootsel.bin'), 'wb') as fp:
                fp.write(b'\1' * 10)
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Mock out the mkfs.ext4 call, and we'll just test the contents
            # directory (i.e. what would go in the ext4 file system).
            mock = resources.enter_context(
                patch('ubuntu_image.common_builder.mkfs_ext4'))
            next(state)
            # Check that boot files are copied to the gadget folder
            file1 = os.path.join(gadget_dir, 'boot.img')
            self.assertTrue(os.path.exists(file1))
            file2 = os.path.join(gadget_dir, 'snapbootsel.bin')
            self.assertTrue(os.path.exists(file2))
            # Check that mkfs.ext4 got called with the expected values.  It
            # actually got called twice, but it's only the first call
            # (i.e. the one creating the part, not the image) that we care
            # about.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            part0_path = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            self.assertEqual(
                posargs,
                # mkfs_ext4 positional arguments.
                (part0_img, part0_path, 'snap', 'hold the door'))

    def test_populate_filesystems_lk_bootloader_no_boot_files(self):
        # This covers the case of no content files provided for lk
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                cmd='snap',
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                role=None,
                filesystem=FileSystemType.ext4,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.lk,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir, [part0_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Mock out the mkfs.ext4 call, and we'll just test the contents
            # directory (i.e. what would go in the ext4 file system).
            mock = resources.enter_context(
                patch('ubuntu_image.common_builder.mkfs_ext4'))
            next(state)
            # Check that mkfs.ext4 got called with the expected values.  It
            # actually got called twice, but it's only the first call
            # (i.e. the one creating the part, not the image) that we care
            # about.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            part0_path = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            self.assertEqual(
                posargs,
                # mkfs_ext4 positional arguments.
                (part0_img, part0_path, 'snap', 'hold the door'))

    def test_populate_filesystems_seeded_image(self):
        # Check if population of seeded images copies the rootfs to the seed.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=None,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                cmd='snap',
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            part1_img = os.path.join(state.images, 'part1.img')
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part0 = SimpleNamespace(
                role=None,
                filesystem=FileSystemType.none,
                content=[contents1],
                size=150,
                )
            part1 = SimpleNamespace(
                role=StructureRole.system_seed,
                filesystem=FileSystemType.vfat,
                size=None,
                )
            # This partition is unused and basically 'invalid', only exists
            # here for us to make sure it was skipped and not acted on.
            part2 = SimpleNamespace(
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1, part2],
                schema=VolumeSchema.mbr,
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=True,
                )
            prep_state(state, workdir, [part0_img, part1_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Mock out the mkfs.ext4 call, since we want to make sure it's not
            # called in this case.  We also mock out the run call to see if
            # mcopy was called as expected.
            mkfs_mock = resources.enter_context(
                patch('ubuntu_image.common_builder.mkfs_ext4'))
            run_mock = resources.enter_context(
                patch('ubuntu_image.common_builder.run'))
            # Prepare some files on the rootfs directory.
            state.rootfs = os.path.join(workdir, 'rootfs')
            os.makedirs(state.rootfs)
            file1_path = os.path.join(state.rootfs, 'bar')
            file2_path = os.path.join(state.rootfs, 'foo')
            open(file1_path, 'w')
            open(file2_path, 'w')
            next(state)
            # Check the contents of the part0 image file.
            with open(part0_img, 'rb') as fp:
                data = fp.read()
            self.assertEqual(data, b'\1' * 47 + b'\0' * 103)
            # Make sure the mkfs.ext4 call never happened.
            # This check also guarentees that the dummy part2 partition is
            # skipped and not acted on.
            self.assertEqual(len(mkfs_mock.call_args_list), 0)
            # Make sure there was only one run call and that it was for
            # mcopy of the seed partition.
            self.assertEqual(len(run_mock.call_args_list), 1)
            posargs, kwargs = run_mock.call_args_list[0]
            # Check if the right arguments were passed to mcopy.
            mcopy_cmd = posargs[0]
            self.assertTrue(
                mcopy_cmd.startswith('mcopy -s -i {} '.format(part1_img)))
            self.assertIn(file1_path, mcopy_cmd)
            self.assertIn(file2_path, mcopy_cmd)

    def test_make_disk(self):
        # make_disk() will use Image with the msdos label with the mbr schema.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            # Craft a gadget specification.  It doesn't need much because
            # we're going to short-circuit out of make_disk().
            volume = SimpleNamespace(
                schema=VolumeSchema.mbr,
                image_size=4001,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Prepare the state machine for the steps we don't execute.
            prep_state(state, workdir)
            # Set up the short-circuit.
            mock = resources.enter_context(
                patch('ubuntu_image.common_builder.Image',
                      side_effect=RuntimeError))
            # Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(RuntimeError):
                next(state)
            # Check that the Image mock got called as expected.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs,
                (os.path.join(outputdir, 'volume1.img'), 4001, volume.schema))

    def test_make_disk_with_parts(self):
        # Write all the parts to the disk at the proper offset.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=None,
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                )
            part2 = SimpleNamespace(
                name='gamma',
                type='mbr',
                role=StructureRole.mbr,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part3 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(5),
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order.
                structures=[part2, part0, part1, part3],
                schema=VolumeSchema.gpt,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            part1_img = os.path.join(state.images, 'part1.img')
            with open(part1_img, 'wb') as fp:
                fp.write(b'\2' * 12)
            part2_img = os.path.join(state.images, 'part2.img')
            with open(part2_img, 'wb') as fp:
                fp.write(b'\3' * 13)
            root_img = os.path.join(state.images, 'part3.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir,
                       [part2_img, part0_img, part1_img, root_img])
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.y
            disk_img = os.path.join(outputdir, 'volume1.img')
            with open(disk_img, 'rb') as fp:
                # Part 0's offset is written at position 100.
                fp.seek(100)
                # Read a 32-bit little-ending integer.  Remember
                # struct.unpack() always returns tuples, and the values are
                # written in sector units, which are hard-coded as 512 bytes.
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(2) / 512)
                # Part 1's offset is written at position 200.
                fp.seek(200)
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(4) / 512)
                # Part 0's image lives at MiB(2).
                fp.seek(MiB(2))
                self.assertEqual(fp.read(15), b'\1' * 11 + b'\0' * 4)
                # Part 1's image lives at MiB(4).
                fp.seek(MiB(4))
                self.assertEqual(fp.read(15), b'\2' * 12 + b'\0' * 3)
                # Part 2's image is an MBR so it must live at offset 0.
                fp.seek(0)
                self.assertEqual(fp.read(15), b'\3' * 13 + b'\0' * 2)
                # The root file system lives at the end, which in this case is
                # at the 5MiB location (e.g. the farthest out non-mbr
                # partition is at 4MiB and has 1MiB in size.
                fp.seek(MiB(5))
                self.assertEqual(fp.read(15), b'\4' * 14 + b'\0')
            # Verify the disk image's partition table.
            proc = run('sfdisk --json {}'.format(disk_img))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'] if 'name' in part else None, part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            self.assertEqual(partitions[0], ('alpha', 4096))
            self.assertEqual(partitions[1], ('beta', 8192))
            self.assertEqual(partitions[2], ('writable', 10240))

    def test_make_disk_with_parts_seeded(self):
        # Make sure for seeded images we skip the right partitions.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='mbr',
                role=StructureRole.mbr,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name='seed',
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_seed,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            part2 = SimpleNamespace(
                name='data',
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=MiB(5),
                offset=MiB(2),
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order.
                structures=[part0, part1, part2],
                schema=VolumeSchema.gpt,
                image_size=MiB(20),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=True,
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            part1_img = os.path.join(state.images, 'part1.img')
            with open(part1_img, 'wb') as fp:
                fp.write(b'\2' * 12)
            part2_img = os.path.join(state.images, 'part2.img')
            with open(part2_img, 'wb') as fp:
                fp.write(b'\3' * 13)
            prep_state(state, workdir,
                       [part2_img, part0_img, part1_img])
            # Create the disk.
            next(state)
            # Verify the disk image's partition table.
            disk_img = os.path.join(outputdir, 'volume1.img')
            proc = run('sfdisk --json {}'.format(disk_img))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'] if 'name' in part else None, part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            self.assertEqual(len(partitions), 1)
            self.assertEqual(partitions[0], ('seed', 2048))

    def test_make_disk_with_bare_parts(self):
        # The second structure has a role:bare meaning it is not wrapped in a
        # disk partition.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            state.rootfs_size = MiB(1)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='assets',
                role=None,
                size=MiB(1),
                offset=0,
                offset_write=None,
                type='bare',
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(5),
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order.
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            state.images = os.path.join(workdir, '.image')
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            volumedir = os.path.join(workdir, 'volumes', 'volume1')
            os.makedirs(volumedir)
            part0_img = os.path.join(volumedir, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            root_img = os.path.join(volumedir, 'root.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir, [part0_img, root_img])
            os.makedirs(state.images)
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.
            img_file = os.path.join(outputdir, 'volume1.img')
            with open(img_file, 'rb') as fp:
                fp.seek(0)
                self.assertEqual(fp.read(15), b'\1' * 11 + b'\0' * 4)
                # The root file system lives at the end, which in this case is
                # at the 5MiB location (e.g. the farthest out non-mbr
                # partition is at 4MiB and has 1MiB in size.
                fp.seek(MiB(5))
                self.assertEqual(fp.read(15), b'\4' * 14 + b'\0')
            # Verify the disk image's partition table.
            proc = run('sfdisk --json {}'.format(img_file))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'] if 'name' in part else None, part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            self.assertEqual(len(partitions), 1)
            self.assertEqual(partitions[0], ('writable', 10240))

    def test_make_disk_with_out_of_order_structures(self):
        # Structures get partition numbers matching their appearance in the
        # gadget.yaml, even if these are out of order with respect to their
        # disk offsets.  LP: #1642999
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=None,
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                )
            part2 = SimpleNamespace(
                name='gamma',
                type='mbr',
                role=StructureRole.mbr,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part3 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(5),
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order which does not match the disk
                # offset order.  LP: #1642999
                structures=[part1, part0, part2, part3],
                schema=VolumeSchema.gpt,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            part1_img = os.path.join(state.images, 'part1.img')
            with open(part1_img, 'wb') as fp:
                fp.write(b'\2' * 12)
            part2_img = os.path.join(state.images, 'part2.img')
            with open(part2_img, 'wb') as fp:
                fp.write(b'\3' * 13)
            root_img = os.path.join(state.images, 'root.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir,
                       [part1_img, part0_img, part2_img, root_img])
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.y
            disk_img = os.path.join(outputdir, 'volume1.img')
            with open(disk_img, 'rb') as fp:
                # Part 0's offset is written at position 100.
                fp.seek(100)
                # Read a 32-bit little-ending integer.  Remember
                # struct.unpack() always returns tuples, and the values are
                # written in sector units, which are hard-coded as 512 bytes.
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(2) / 512)
                # Part 1's offset is written at position 200.
                fp.seek(200)
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(4) / 512)
                # Part 0's image lives at MiB(2).
                fp.seek(MiB(2))
                self.assertEqual(fp.read(15), b'\1' * 11 + b'\0' * 4)
                # Part 1's image lives at MiB(4).
                fp.seek(MiB(4))
                self.assertEqual(fp.read(15), b'\2' * 12 + b'\0' * 3)
                # Part 2's image is an MBR so it must live at offset 0.
                fp.seek(0)
                self.assertEqual(fp.read(15), b'\3' * 13 + b'\0' * 2)
                # The root file system lives at the end, which in this case is
                # at the 5MiB location (e.g. the farthest out non-mbr
                # partition is at 4MiB and has 1MiB in size.
                fp.seek(MiB(5))
                self.assertEqual(fp.read(15), b'\4' * 14 + b'\0')
            # Verify the disk image's partition table.
            proc = run('sfdisk --json {}'.format(disk_img))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'] if 'name' in part else None, part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            # Partition number matches gadget.yaml order, i.e. part1, part0,
            # rootfs (part2 is an mbr).
            self.assertEqual(partitions[0], ('beta', 8192))
            self.assertEqual(partitions[1], ('alpha', 4096))
            self.assertEqual(partitions[2], ('writable', 10240))

    def test_make_disk_with_parts_system_boot(self):
        # For MBR-style volumes, a part with a role of 'system-boot'
        # gets the boot flag turned on in the partition table.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name=None,
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                type='da',
                size=MiB(1),
                offset=MiB(1),
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(2),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.mbr,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            root_img = os.path.join(state.images, 'root.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir, [part0_img, root_img])
            # Create the disk.
            next(state)
            # Verify the disk image's partition table.
            disk_img = os.path.join(outputdir, 'volume1.img')
            proc = run('sfdisk --json {}'.format(disk_img))
            layout = json.loads(proc.stdout)
            partition1 = layout['partitiontable']['partitions'][0]
            self.assertTrue(partition1['bootable'])

    def test_make_disk_with_parts_relative_offset_writes(self):
        # offset-write accepts label+1234 format.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=None,
                size=MiB(1),
                offset=MiB(4),
                offset_write=('alpha', 200),
                )
            part2 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(5),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1, part2],
                schema=VolumeSchema.gpt,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            part1_img = os.path.join(state.images, 'part1.img')
            with open(part1_img, 'wb') as fp:
                fp.write(b'\2' * 12)
            root_img = os.path.join(state.images, 'root.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir, [part0_img, part1_img, root_img])
            # Create the disk.
            next(state)
            # Verify that beta's offset was written 200 bytes past the start
            # of the alpha partition.
            disk_img = os.path.join(outputdir, 'volume1.img')
            with open(disk_img, 'rb') as fp:
                fp.seek(MiB(2) + 200)
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(4) / 512)

    def test_generate_manifests(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=outputdir,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.generate_manifests)
            # Set up expected state.
            state.rootfs = os.path.join(workdir, 'root')
            snaps_dir = os.path.join(
                state.rootfs, 'system-data', 'var', 'lib', 'snapd', 'snaps')
            seed_dir = os.path.join(
                state.rootfs, 'system-data', 'var', 'lib', 'snapd', 'seed',
                'snaps')
            os.makedirs(snaps_dir)
            os.makedirs(seed_dir)
            state.gadget = SimpleNamespace(
                seeded=False,
                )
            # Create some dummy snaps in both directories
            snaps = {'foo': '13', 'bar-baz': '43', 'comma': '4.4',
                     'snap': '1', 'underscore_name': '78'}
            files = ['{}_{}.snap'.format(k, v) for k, v in snaps.items()]
            files.append('not_a_snap')
            for file in files:
                open(os.path.join(snaps_dir, file), 'w').close()
            seeds = {'foo': '13', 'bar-baz': '43', 'comma': '4.4',
                     'snap': '1', 'underscore_name': '78', 'pc': '19'}
            files = ['{}_{}.snap'.format(k, v) for k, v in seeds.items()]
            files.append('not_a_snap')
            for file in files:
                open(os.path.join(seed_dir, file), 'w').close()
            next(state)
            snaps_manifest = os.path.join(outputdir, 'snaps.manifest')
            seed_manifest = os.path.join(outputdir, 'seed.manifest')
            self.assertTrue(os.path.exists(snaps_manifest))
            self.assertTrue(os.path.exists(seed_manifest))
            with open(snaps_manifest) as f:
                manifest = set(f.read().splitlines())
                snap_set = set('{} {}'.format(k, v) for k, v in snaps.items())
                self.assertEqual(snap_set, manifest)
            with open(seed_manifest) as f:
                manifest = set(f.read().splitlines())
                snap_set = set('{} {}'.format(k, v) for k, v in seeds.items())
                self.assertEqual(snap_set, manifest)

    def test_generate_manifests_seeded(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                output_dir=outputdir,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.generate_manifests)
            # Set up expected state.
            state.rootfs = os.path.join(workdir, 'root')
            seed_dir = os.path.join(
                state.rootfs, 'snaps')
            os.makedirs(seed_dir)
            state.gadget = SimpleNamespace(
                seeded=True,
                )
            # Create some dummy snaps in both directories
            seeds = {'foo': '13', 'bar-baz': '43', 'comma': '4.4',
                     'snap': '1', 'underscore_name': '78', 'pc': '19'}
            files = ['{}_{}.snap'.format(k, v) for k, v in seeds.items()]
            files.append('not_a_snap')
            for file in files:
                open(os.path.join(seed_dir, file), 'w').close()
            next(state)
            snaps_manifest = os.path.join(outputdir, 'snaps.manifest')
            seed_manifest = os.path.join(outputdir, 'seed.manifest')
            # Make sure the snaps.manifest is not created in this case
            self.assertFalse(os.path.exists(snaps_manifest))
            self.assertTrue(os.path.exists(seed_manifest))
            with open(seed_manifest) as f:
                manifest = set(f.read().splitlines())
                snap_set = set('{} {}'.format(k, v) for k, v in seeds.items())
                self.assertEqual(snap_set, manifest)

    def test_prepare_filesystems_with_no_vfat_partitions(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=None,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            # Mock the run() call to prove that we never call dd.
            mock = resources.enter_context(
                patch('ubuntu_image.common_builder.run'))
            next(state)
            # There should be only one call to run() and that's for the dd.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertTrue(posargs[0].startswith('dd if='))

    def test_prepare_filesystems_seeded_image(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=None,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=StructureRole.system_seed,
                filesystem=FileSystemType.ext4,
                size=None,
                offset=MiB(1),
                offset_write=None,
                )
            # This partition is unused and basically 'invalid', only exists
            # here for us to make sure it was skipped and not acted on.
            part2 = SimpleNamespace(
                name='dummy',
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=MiB(10),
                offset=MiB(100),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1, part2],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=True,
                )
            prep_state(state, workdir)
            next(state)
            # Make sure both part0 and part1 got prepared.
            volumes_dir = os.path.join(workdir, 'volumes')
            self.assertTrue(os.path.exists(
                os.path.join(volumes_dir, 'volume1', 'part0.img')))
            self.assertTrue(os.path.exists(
                os.path.join(volumes_dir, 'volume1', 'part1.img')))
            # Check if the seed partition got the right size auto-selected.
            seed_part = state.gadget.volumes['volume1'].structures[1]
            self.assertEqual(seed_part.size, MiB(1))
            # Make sure the part2 dummy  partition was really skipped and no
            # actions have been performed on it.
            self.assertFalse(os.path.exists(
                os.path.join(volumes_dir, 'volume1', 'part2.img')))

    def test_image_size_calculated(self):
        # We let prepare_filesystems() calculate the disk image size.  The
        # rootfs is defined as 1MiB, and the only structure part is defined as
        # 1MiB.  The calculation adds 34 512-byte sectors for backup GPT.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=None,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            next(state)
            self.assertEqual(
                state.gadget.volumes['volume1'].image_size, 2114560)

    def test_image_size_calculated_seeded(self):
        # Same as above, but this time we make sure that for seeded (UC20)
        # images, all partitions are taken into consideration as expected
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=None,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                role=StructureRole.system_seed,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            part2 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=MiB(2),
                offset=MiB(2),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1, part2],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=True,
                )
            prep_state(state, workdir)
            next(state)
            self.assertEqual(
                state.gadget.volumes['volume1'].image_size, 4211712)

    def test_image_size_explicit(self):
        # --image-size=5M overrides the implicit disk image size.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=MiB(5),
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            next(state)
            self.assertEqual(
                state.gadget.volumes['volume1'].image_size, MiB(5))

    def test_multivolume_image_size_explicit(self):
        # --image-size=volume1:5M overrides the implicit disk image size.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size={'volume1': MiB(5)},
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            next(state)
            self.assertEqual(
                state.gadget.volumes['volume1'].image_size, MiB(5))

    def test_image_size_too_small(self):
        # --image-size=1M but the calculated size is larger, so the command
        # line option is ignored, with a warning.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='1M',
                image_size=MiB(1),
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            self.assertEqual(state.gadget.volumes['volume1'].image_size,
                             2114560)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring image size smaller than minimum required size: '
                'vol[0]:volume1 1M < 2114560')

    def test_image_size_too_small_with_out_of_order_structures(self):
        # Here we have a bunch of structures which are not sorted by offset.
        # In fact the last partition is at offset 0 with a size of 1MiB.  If
        # the "--image-size fits" calculation is performed against just the
        # last partition offset + its size, this will appear to be big
        # enough.  In reality though it's not because an earlier partition
        # (specifically part1) starts at 4MiB and has a size of 1MiB, so a
        # disk image of 3MiB won't fit.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='3M',
                image_size=MiB(3),
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            state.rootfs_size = MiB(1)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                role=None,
                type='21686148-6449-6E6f-744E-656564454649',
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                filesystem=FileSystemType.ext4,
                filesystem_label='alpha',
                )
            part1 = SimpleNamespace(
                name='beta',
                role=None,
                type='C12A7328-F81F-11D2-BA4B-00A0C93EC93B',
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                filesystem=FileSystemType.ext4,
                filesystem_label='beta',
                )
            part2 = SimpleNamespace(
                name='gamma',
                role=StructureRole.mbr,
                type='mbr',
                size=MiB(1),
                offset=0,
                offset_write=None,
                filesystem=FileSystemType.ext4,
                filesystem_label='gamma',
                )
            part3 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(5),
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order which does not match the disk
                # offset order.  LP: #1642999
                structures=[part1, part0, part2, part3],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            # The actual image size is 6MiB + 17KiB.  The former value comes
            # from the farthest out structure (part1 at offset 4MiB + 1MiB
            # size) + the rootfs size of 1MiB.  The latter comes from the
            # empirically derived 34 sector GPT backup space.
            self.assertEqual(
                state.gadget.volumes['volume1'].image_size, 6308864)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring image size smaller than minimum required size: '
                'vol[0]:volume1 3M < 6308864')

    def test_ambiguous_image_size(self):
        # An --image-size is given, but with keys that lead to ambiguous
        # selection.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='0:1M,volume1:2M',
                image_size={0: MiB(1), 'volume1': MiB(2)},
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            self.assertEqual(state.gadget.volumes['volume1'].image_size,
                             2114560)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring ambiguous volume size; index+name given')

    def test_multivolume_image_size_too_small(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='0:1M',
                image_size={0: MiB(1)},
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            self.assertEqual(state.gadget.volumes['volume1'].image_size,
                             2114560)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring image size smaller than minimum required size: '
                'vol[0]:volume1 0:1M < 2114560')

    def test_round_up_size_for_mbr_root_partitions(self):
        # LP: #1634557 - two rounding errors conspired to make mbr partitions
        # undersized.  First, an internal calculation in the builder used
        # floor division to produce a size in KiB less than the actual root
        # partition size if it wasn't an even multiple of 1024 bytes.  Second,
        # sfdisk implicitly rounds down partition sizes that aren't a multiple
        # of 1MiB.  This wasn't immediately noticed because initramfs will
        # automagically resize such partitions on first boot.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                output_dir=outputdir,
                unpackdir=unpackdir,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            # Craft a gadget schema.  This is based on the official pi3-kernel
            # gadget.yaml file.
            state.rootfs_size = 947980
            contents0 = SimpleNamespace(
                source='boot-assets/',
                target='/',
                )
            part0 = SimpleNamespace(
                name=None,
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem='vfat',
                type='0C',
                size=MiB(128),
                offset=MiB(1),
                offset_write=None,
                contents=[contents0],
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                size=state.rootfs_size,
                offset=MiB(129),
                offset_write=None,
                )
            volume0 = SimpleNamespace(
                schema=VolumeSchema.mbr,
                bootloader=BootLoader.uboot,
                structures=[part0, part1],
                image_size=MiB(256),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(pi3=volume0),
                seeded=False,
                )
            # Set up images for the targeted test.  The important thing here
            # is that the root partition gets sizes to a non-multiple of 1KiB.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            root_img = os.path.join(state.images, 'part1.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\2' * state.rootfs_size)
            prep_state(state, workdir, [part0_img, root_img])
            # Create the disk.
            next(state)
            # The root file system must be at least 947980 bytes.
            disk_img = os.path.join(outputdir, 'pi3.img')
            proc = run('sfdisk --json {}'.format(disk_img))
            layout = json.loads(proc.stdout)
            partition1 = layout['partitiontable']['partitions'][1]
            # sfdisk returns size in sectors.  947980 bytes rounded up to 512
            # byte sectors.
            self.assertGreaterEqual(partition1['size'], 1852)

    def test_explicit_rootfs_too_small(self):
        # The root file system (i.e. 'system-data' label) is explicitly given
        # as a structure in the gadget.yaml, but the given size is too small.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='1M',
                image_size=MiB(1),
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            part0 = SimpleNamespace(
                name='alpha',
                type='21686148-6449-6E6f-744E-656564454649',
                role=None,
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            part1 = SimpleNamespace(
                name=None,
                type=('83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
                role=StructureRole.system_data,
                filesystem=FileSystemType.ext4,
                size=state.rootfs_size - 1111,
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'rootfs partition size (1047465) smaller than '
                'actual rootfs contents 1048576')

    def test_mbr_contents_too_large(self):
        # A structure with role:mbr cannot have contents larger than 446 bytes.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='1M',
                image_size=MiB(1),
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Create mbr contents that is bigger than the mbr partition.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            gadget_dir = os.path.join(state.unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            mbr_content = os.path.join(gadget_dir, 'pc-boot.img')
            with open(mbr_content, 'wb') as fp:
                # Oops!  This is > 446 bytes (mbr role limit).
                fp.write(b'\1' * 512)
            # Name the part image file.
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            content = SimpleNamespace(
                image='pc-boot.img',
                size=None,
                offset=None,
                )
            part0 = SimpleNamespace(
                name=None,
                role=None,
                type='mbr',
                filesystem=FileSystemType.none,
                size=440,
                offset=0,
                offset_write=None,
                content=[content],
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(pc=volume),
                seeded=False,
                )
            prep_state(state, workdir, part_images=[part0_img])
            with self.assertRaises(DoesNotFit) as cm:
                next(state)
            self.assertEqual(cm.exception.part_number, 0)
            self.assertEqual(
                cm.exception.part_path, 'volumes:<pc>:structure:<mbr>')
            # 72 bytes over == 512 - 440
            self.assertEqual(cm.exception.overage, 72)

    def test_mbr_contents_too_large_with_name(self):
        # A structure with role:mbr cannot have contents larger than 446 bytes.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='1M',
                image_size=MiB(1),
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Create mbr contents that is bigger than the mbr partition.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            gadget_dir = os.path.join(state.unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            mbr_content = os.path.join(gadget_dir, 'pc-boot.img')
            with open(mbr_content, 'wb') as fp:
                # Oops!  This is > 446 bytes (mbr role limit).
                fp.write(b'\1' * 512)
            # Name the part image file.
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            content = SimpleNamespace(
                image='pc-boot.img',
                size=None,
                offset=None,
                )
            part0 = SimpleNamespace(
                name='master boot record',
                role=None,
                type='mbr',
                filesystem=FileSystemType.none,
                size=440,
                offset=0,
                offset_write=None,
                content=[content],
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(pc=volume),
                seeded=False,
                )
            prep_state(state, workdir, part_images=[part0_img])
            with self.assertRaises(DoesNotFit) as cm:
                next(state)
            self.assertEqual(cm.exception.part_number, 0)
            self.assertEqual(
                cm.exception.part_path,
                'volumes:<pc>:structure:<master boot record>')
            # 72 bytes over == 512 - 440
            self.assertEqual(cm.exception.overage, 72)

    def test_mbr_contents_too_large_with_role(self):
        # A structure with role:mbr cannot have contents larger than 446 bytes.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                given_image_size='1M',
                image_size=MiB(1),
                debug=False,
                output=None,
                output_dir=None,
                unpackdir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Create mbr contents that is bigger than the mbr partition.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            gadget_dir = os.path.join(state.unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            mbr_content = os.path.join(gadget_dir, 'pc-boot.img')
            with open(mbr_content, 'wb') as fp:
                # Oops!  This is > 446 bytes (mbr role limit).
                fp.write(b'\1' * 512)
            # Name the part image file.
            state.images = os.path.join(workdir, '.images')
            os.makedirs(state.images)
            part0_img = os.path.join(state.images, 'part0.img')
            # Craft a gadget schema.
            state.rootfs_size = MiB(1)
            content = SimpleNamespace(
                image='pc-boot.img',
                size=None,
                offset=None,
                )
            part0 = SimpleNamespace(
                name=None,
                role=StructureRole.mbr,
                type='mbr',
                filesystem=FileSystemType.none,
                size=440,
                offset=0,
                offset_write=None,
                content=[content],
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(pc=volume),
                seeded=False,
                )
            prep_state(state, workdir, part_images=[part0_img])
            with self.assertRaises(DoesNotFit) as cm:
                next(state)
            self.assertEqual(cm.exception.part_number, 0)
            self.assertEqual(
                cm.exception.part_path,
                'volumes:<pc>:structure:<mbr>')
            # 72 bytes over == 512 - 440
            self.assertEqual(cm.exception.overage, 72)

    def test_snap_with_extra_snaps(self):
        with ExitStack() as resources:
            # This tests needs to run the actual snap() helper function, not
            # the testsuite-wide mock.  This is appropriate since we're
            # mocking it ourselves here.
            if NosePlugin.snap_mocker is not None:
                NosePlugin.snap_mocker.patcher.stop()
                resources.callback(NosePlugin.snap_mocker.patcher.start)
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=['foo', 'bar=edge', 'baz=18/beta'],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_image)
            run_cmd = resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout='command stdout',
                    stderr='',
                    )))
            next(state)
            self.assertEqual(state.exitcode, 0)
            self.assertGreaterEqual(len(run_cmd.call_args), 1)
            self.assertListEqual(
                run_cmd.call_args[0][0],
                ['snap', 'prepare-image', '--channel=edge',
                 '--snap=foo', '--snap=bar=edge', '--snap=baz=18/beta',
                 self.model_assertion, unpackdir])

    def test_snap_with_extra_snaps_deprecated_syntax(self):
        # This is essentially exactly the same as test_snap_with_extra_snaps,
        # just making sure it still works with the deprecated --extra-snaps
        # syntax.
        with ExitStack() as resources:
            # This tests needs to run the actual snap() helper function, not
            # the testsuite-wide mock.  This is appropriate since we're
            # mocking it ourselves here.
            if NosePlugin.snap_mocker is not None:
                NosePlugin.snap_mocker.patcher.stop()
                resources.callback(NosePlugin.snap_mocker.patcher.start)
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=None,
                extra_snaps=['foo', 'bar=edge', 'baz=18/beta'],
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_image)
            run_cmd = resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout='command stdout',
                    stderr='',
                    )))
            next(state)
            self.assertEqual(state.exitcode, 0)
            self.assertGreaterEqual(len(run_cmd.call_args), 1)
            self.assertListEqual(
                run_cmd.call_args[0][0],
                ['snap', 'prepare-image', '--channel=edge',
                 '--snap=foo', '--snap=bar=edge', '--snap=baz=18/beta',
                 self.model_assertion, unpackdir])

    def test_snap_command_fails(self):
        # LP: #1621445 - If the snap(1) command fails, don't print the full
        # traceback unless --debug is given.
        with ExitStack() as resources:
            # This tests needs to run the actual snap() helper function, not
            # the testsuite-wide mock.  This is appropriate since we're
            # mocking it ourselves here.
            if NosePlugin.snap_mocker is not None:
                NosePlugin.snap_mocker.patcher.stop()
                resources.callback(NosePlugin.snap_mocker.patcher.start)
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_image)
            resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout='command stdout',
                    stderr='command stderr',
                    check_returncode=check_returncode,
                    )))
            log_capture = resources.enter_context(LogCapture())
            next(state)
            self.assertEqual(state.exitcode, 1)
            # Note that there is no traceback in the output.
            self.assertEqual(log_capture.logs, [
                (logging.ERROR, 'COMMAND FAILED: snap prepare-image '
                                '--channel=edge {} {}'.format(
                                    self.model_assertion, unpackdir)),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                ])

    def test_snap_command_fails_debug(self):
        # LP: #1621445 - If the snap(1) command fails, don't print the full
        # traceback unless --debug is given.
        with ExitStack() as resources:
            # This tests needs to run the actual snap() helper function, not
            # the testsuite-wide mock.  This is appropriate since we're
            # mocking it ourselves here.
            if NosePlugin.snap_mocker is not None:
                NosePlugin.snap_mocker.patcher.stop()
                resources.callback(NosePlugin.snap_mocker.patcher.start)
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=True,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_image)
            resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout='command stdout',
                    stderr='command stderr',
                    check_returncode=check_returncode,
                    )))
            log_capture = resources.enter_context(LogCapture())
            next(state)
            self.assertEqual(state.exitcode, 1)
            # Note that there is no traceback in the output.
            self.assertEqual(log_capture.logs, [
                (logging.ERROR, 'COMMAND FAILED: snap prepare-image '
                                '--channel=edge {} {}'.format(
                                    self.model_assertion, unpackdir)),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                (logging.ERROR, 'Full debug traceback follows'),
                ('IMAGINE THE TRACEBACK HERE'),
                ])

    def test_disk_info(self):
        with ExitStack() as resources:
            tmpdir = resources.enter_context(TemporaryDirectory())
            diskinfo = os.path.join(tmpdir, 'disk-info')
            with open(diskinfo, 'w') as fp:
                fp.write('Some disk info')
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=diskinfo,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state._next.pop()
            state._next.append(state.generate_disk_info)
            next(state)
            # Make sure the file is populated with the right contents.
            with open(os.path.join(state.rootfs, '.disk', 'info')) as fp:
                self.assertEqual(fp.read(), 'Some disk info')

    def test_disable_console_conf(self):
        with ExitStack() as resources:
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=True,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Make sure that when disable-console-conf is passed, we create the
            # right file on the rootfs.
            self.assertTrue(os.path.exists(os.path.join(
                state.rootfs, 'system-data', 'var', 'lib', 'console-conf',
                'complete')))

    def test_do_not_disable_console_conf_by_default(self):
        with ExitStack() as resources:
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(seeded=False)
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Just confirm that if we run ubuntu-image without
            # --disable-console-conf (so by default), the file isn't there.
            self.assertFalse(os.path.exists(os.path.join(
                state.rootfs, 'system-data', 'var', 'lib', 'console-conf',
                'complete')))

    def test_du_command_fails(self):
        with ExitStack() as resources:
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=False,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.rootfs = '/tmp'
            state._next.pop()
            state._next.append(state.calculate_rootfs_size)
            resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout='command stdout',
                    stderr='command stderr',
                    check_returncode=check_returncode,
                    )))
            log_capture = resources.enter_context(LogCapture())
            next(state)
            self.assertEqual(state.exitcode, 1)
            # Note that there is no traceback in the output.
            self.assertEqual(log_capture.logs, [
                (logging.ERROR, 'COMMAND FAILED: du -s -B1 /tmp'),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                ])

    def test_du_command_fails_debug(self):
        with ExitStack() as resources:
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                debug=True,
                snap=[],
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.rootfs = '/tmp'
            state._next.pop()
            state._next.append(state.calculate_rootfs_size)
            resources.enter_context(patch(
                'ubuntu_image.helpers.subprocess_run',
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout='command stdout',
                    stderr='command stderr',
                    check_returncode=check_returncode,
                    )))
            log_capture = resources.enter_context(LogCapture())
            next(state)
            self.assertEqual(state.exitcode, 1)
            self.assertEqual(log_capture.logs, [
                (logging.ERROR, 'COMMAND FAILED: du -s -B1 /tmp'),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                (logging.ERROR, 'Full debug traceback follows'),
                ('IMAGINE THE TRACEBACK HERE'),
                ])

    def test_multivolume_dash_o(self):
        # -o/--output is ignored when multiple volumes are specified in the
        # gadget.yaml file.  When -O/--output-dir is also not given, then the
        # current working directory is used.
        with ExitStack() as resources:
            outputdir = resources.enter_context(TemporaryDirectory())
            disk_img = os.path.join(outputdir, 'disk.img')
            getcwd_mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder.os.getcwd'))
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=disk_img,
                output_dir=outputdir,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            state.gadget = SimpleNamespace(
                volumes={name: SimpleNamespace()
                         for name in ('one', 'two', 'three')},
                seeded=False,
                )
            resources.enter_context(patch.object(state, '_make_one_disk'))
            log_mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.warning'))
            next(state)
            posargs, kwargs = log_mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                '-o/--output ignored for multiple volumes')
            self.assertEqual(len(getcwd_mock.call_args_list), 0)
            self.assertFalse(os.path.exists(disk_img))

    def test_multivolume_dash_o_cwd(self):
        # -o/--output is ignored when multiple volumes are specified in the
        # gadget.yaml file.  When -O/--output-dir is also not given, then the
        # current working directory is used.
        with ExitStack() as resources:
            cwd = resources.enter_context(TemporaryDirectory())
            getcwd_mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder.os.getcwd',
                      return_value=cwd))
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=None,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            state.gadget = SimpleNamespace(
                volumes={name: SimpleNamespace()
                         for name in ('one', 'two', 'three')},
                seeded=False,
                )
            resources.enter_context(patch.object(state, '_make_one_disk'))
            next(state)
            self.assertEqual(len(getcwd_mock.call_args_list), 1)

    def test_debug_unpack_contents(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            args = SimpleNamespace(
                channel='edge',
                cloud_init=None,
                snap=None,
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                output_dir=None,
                workdir=workdir,
                hooks_directory=[],
                disk_info=None,
                disable_console_conf=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            state._next.pop()
            state._next.append(state.load_gadget_yaml)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.uboot,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                seeded=False,
                )
            prep_state(state, workdir)
            # Test this debugging helper.
            unpackdir = resources.enter_context(TemporaryDirectory())
            resources.enter_context(
                envar('UBUNTU_IMAGE_PRESERVE_UNPACK', unpackdir))
            next(state)
            # Check the contents of the preserved unpack copy.  Remove the
            # unpredictable prefix.
            prefix_len = len(unpackdir) + 1
            files = []
            for dirpath, dirnames, filenames, in os.walk(unpackdir):
                files.extend(os.path.join(dirpath, filename)[prefix_len:]
                             for filename in filenames)
            self.assertEqual(sorted(files), [
                'unpack/gadget/grubx64.efi',
                'unpack/gadget/meta/gadget.yaml',
                'unpack/gadget/shim.efi.signed',
                ])

    def test_temporary_skip_hooks_on_uc20(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            args = SimpleNamespace(
                output=None,
                output_dir=None,
                model_assertion=self.model_assertion,
                workdir=workdir,
                hooks_directory=[],
                cloud_init=None,
                disk_info=None,
                disable_console_conf=False,
                debug=False,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            state._next.pop()
            state._next.append(state.populate_rootfs_contents_hooks)
            state.gadget = SimpleNamespace(
                volumes={},
                seeded=True,
                )
            prep_state(state, workdir)
            mock = resources.enter_context(
                patch('ubuntu_image.assertion_builder._logger.debug'))
            next(state)
            self.assertEqual(len(mock.call_args_list), 2)
            posargs, kwargs = mock.call_args_list[1]
            self.assertEqual(
                posargs[0],
                'Building from a seeded gadget - skipping the '
                'post-populate-rootfs hook execution: unsupported.')
