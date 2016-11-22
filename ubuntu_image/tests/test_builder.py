"""Test image building."""

import os
import re
import json
import logging

from contextlib import ExitStack
from itertools import product
from pkg_resources import resource_filename
from struct import unpack
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.helpers import MiB, run
from ubuntu_image.parser import BootLoader, FileSystemType, VolumeSchema
from ubuntu_image.testing.helpers import LogCapture, XXXModelAssertionBuilder
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
            extra_snaps=None,
            model_assertion=self.model_assertion,
            output=output,
            workdir=None,
            )
        state = self._resources.enter_context(XXXModelAssertionBuilder(args))
        state.run_thru('calculate_bootfs_size')
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
                boot=state.bootfs,
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
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                workdir=None,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
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
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                workdir=None,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(os.path.join(image_dir, 'snap'))
            os.makedirs(os.path.join(image_dir, 'var'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
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
                extra_snaps=None,
                model_assertion=self.model_assertion,
                output=None,
                workdir=None,
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
                unpackdir=unpackdir,
                workdir=workdir,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.uboot,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
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
            with open(os.path.join(workdir, 'part0', '1.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(workdir, 'part0', '2.dat'), 'rb') as fp:
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
                unpackdir=unpackdir,
                workdir=workdir,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader='bogus',
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
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
                unpackdir=unpackdir,
                workdir=workdir,
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
            part = SimpleNamespace(
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents1, contents2],
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            # Run the method, the testable effects of which copy all the files
            # in the source directory (i.e. <unpackdir>/gadget/<source>) into
            # the target directory (i.e. <workdir>/part0).  So put some
            # contents into the source locations.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            src = os.path.join(gadget_dir, 'as.dat')
            with open(src, 'wb') as fp:
                fp.write(b'01234')
            src = os.path.join(gadget_dir, 'bs')
            os.makedirs(src)
            # Put a couple of files and a directory in the source, since
            # directories are copied recursively.
            with open(os.path.join(src, 'c.dat'), 'wb') as fp:
                fp.write(b'56789')
            srcdir = os.path.join(src, 'd')
            os.makedirs(srcdir)
            with open(os.path.join(srcdir, 'e.dat'), 'wb') as fp:
                fp.write(b'0abcd')
            # Run the state machine.
            next(state)
            # Did all the files and directories get copied?
            dstbase = os.path.join(workdir, 'part0')
            with open(os.path.join(dstbase, 'at.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(dstbase, 'bt', 'c.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'56789')
            with open(os.path.join(dstbase, 'bt', 'd', 'e.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'0abcd')

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
                unpackdir=unpackdir,
                workdir=workdir,
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
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents],
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            state.unpackdir = unpackdir
            # Run the state machine.  Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(ValueError) as cm:
                next(state)
            self.assertEqual(
                str(cm.exception), 'target must end in a slash: bt')

    def test_calculate_bootfs_size_no_filesystem(self):
        # When a part has no file system type, we can't calculate its size.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.calculate_bootfs_size)
            # Craft a gadget specification.
            part = SimpleNamespace(
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Calculate the size.
            next(state)
            self.assertEqual(len(state.bootfs_sizes), 0)

    def test_populate_filesystems_none_type(self):
        # We do a bit-wise copy when the file system has no type.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
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
            state.boot_images = [part0_img]
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
                filesystem=FileSystemType.none,
                content=[contents1, contents2, contents3, contents4],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
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
            resources.enter_context(patch('ubuntu_image.builder.mkfs_ext4'))
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
                unpackdir=unpackdir,
                workdir=workdir,
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
            state.boot_images = [part0_img]
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                filesystem=FileSystemType.ext4,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            # Mock out the mkfs.ext4 call, and we'll just test the contents
            # directory (i.e. what would go in the ext4 file system).
            mock = resources.enter_context(
                patch('ubuntu_image.builder.mkfs_ext4'))
            next(state)
            # Check that mkfs.ext4 got called with the expected values.  It
            # actually got called twice, but it's only the first call
            # (i.e. the one creating the part, not the image) that we care
            # about.
            self.assertEqual(len(mock.call_args_list), 2)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs,
                # mkfs_ext4 positional arguments.
                (part0_img, os.path.join(workdir, 'part0'), 'hold the door'))

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
                unpackdir=unpackdir,
                workdir=workdir,
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
            state.boot_images = [part0_img]
            # Craft a gadget specification.
            contents1 = SimpleNamespace(
                image='image1.img',
                size=None,
                offset=None,
                )
            part = SimpleNamespace(
                filesystem=801,
                filesystem_label='hold the door',
                content=[contents1],
                size=150,
                )
            volume = SimpleNamespace(
                structures=[part],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
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

    def test_make_disk(self):
        # make_disk() will use the MBRImage subclass when the volume schema is
        # mbr instead of gpt.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                debug=False,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = 4001
            os.makedirs(state.images)
            # Craft a gadget specification.  It doesn't need much because
            # we're going to short-circuit out of make_disk().
            volume = SimpleNamespace(
                schema=VolumeSchema.mbr,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Set up the short-circuit.
            mock = resources.enter_context(
                patch('ubuntu_image.builder.MBRImage',
                      side_effect=RuntimeError))
            # Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(RuntimeError):
                next(state)
            # Check that the MBRImage mock got called as expected.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(posargs, (state.disk_img, state.image_size))

    def test_make_disk_with_parts(self):
        # Write all the parts to the disk at the proper offset.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = MiB(10)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='ef',
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                )
            part2 = SimpleNamespace(
                name='gamma',
                type='mbr',
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order.
                structures=[part2, part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
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
            state.root_img = os.path.join(state.images, 'root.img')
            state.rootfs_size = MiB(1)
            state.rootfs_offset = MiB(5)
            with open(state.root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            state.boot_images = [part2_img, part0_img, part1_img]
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.y
            with open(state.disk_img, 'rb') as fp:
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
            proc = run('sfdisk --json {}'.format(state.disk_img))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'], part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            self.assertEqual(partitions[0], ('alpha', 4096))
            self.assertEqual(partitions[1], ('beta', 8192))
            self.assertEqual(partitions[2], ('writable', 10240))

    def test_make_disk_with_out_of_order_structures(self):
        # Structures get partition numbers matching their appearance in the
        # gadget.yaml, even if these are out of order with respect to their
        # disk offsets.  LP: #1642999
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = MiB(10)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='aa',
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='bb',
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                )
            part2 = SimpleNamespace(
                name='gamma',
                type='mbr',
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order which does not match the disk
                # offset order.  LP: #1642999
                structures=[part1, part0, part2],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
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
            state.root_img = os.path.join(state.images, 'root.img')
            state.rootfs_size = MiB(1)
            state.rootfs_offset = MiB(5)
            with open(state.root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            state.boot_images = [part1_img, part0_img, part2_img]
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.y
            with open(state.disk_img, 'rb') as fp:
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
            proc = run('sfdisk --json {}'.format(state.disk_img))
            layout = json.loads(proc.stdout)
            partitions = [
                (part['name'], part['start'])
                for part in layout['partitiontable']['partitions']
                ]
            # Partition number matches gadget.yaml order, i.e. part1, part0,
            # rootfs (part2 is an mbr).
            self.assertEqual(partitions[0], ('beta', 8192))
            self.assertEqual(partitions[1], ('alpha', 4096))
            self.assertEqual(partitions[2], ('writable', 10240))

    def test_make_disk_with_parts_system_boot(self):
        # For MBR-style volumes, a part with a filesystem-label of
        # 'system-boot' gets the boot flag turned on in the partition table.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = MiB(10)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name=None,
                filesystem_label='system-boot',
                type='da',
                size=MiB(1),
                offset=MiB(1),
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.mbr,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            state.root_img = os.path.join(state.images, 'root.img')
            state.rootfs_size = MiB(1)
            state.rootfs_offset = MiB(2)
            with open(state.root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            state.boot_images = [part0_img]
            # Create the disk.
            next(state)
            # Verify the disk image's partition table.
            proc = run('sfdisk --json {}'.format(state.disk_img))
            layout = json.loads(proc.stdout)
            partition1 = layout['partitiontable']['partitions'][0]
            self.assertTrue(partition1['bootable'])

    def test_make_disk_with_parts_relative_offset_writes(self):
        # offset-write accepts label+1234 format.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = MiB(10)
            os.makedirs(state.images)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                )
            part1 = SimpleNamespace(
                name='beta',
                type='ef',
                size=MiB(1),
                offset=MiB(4),
                offset_write=('alpha', 200),
                )
            volume = SimpleNamespace(
                structures=[part0, part1],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
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
            state.root_img = os.path.join(state.images, 'root.img')
            state.rootfs_size = MiB(1)
            with open(state.root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            state.boot_images = [part0_img, part1_img]
            # Create the disk.
            next(state)
            # Verify that beta's offset was written 200 bytes past the start
            # of the alpha partition.
            with open(state.disk_img, 'rb') as fp:
                fp.seek(MiB(2) + 200)
                offset = unpack('<I', fp.read(4))[0]
                self.assertEqual(offset, MiB(4) / 512)

    def test_prepare_filesystems_with_no_vfat_partitions(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=None,
                output=None,
                unpackdir=None,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            state.rootfs_size = MiB(1)
            # Mock the run() call to prove that we never call dd.
            mock = resources.enter_context(patch('ubuntu_image.builder.run'))
            next(state)
            # There should be only one call to run() and that's for the dd.
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertTrue(posargs[0].startswith('dd if='))

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
                unpackdir=None,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            state.rootfs_size = MiB(1)
            # Mock the run() call to prove that we never call dd.
            resources.enter_context(patch('ubuntu_image.builder.run'))
            next(state)
            self.assertEqual(state.image_size, 2114560)

    def test_image_size_explicit(self):
        # --image-size=5M overrides the implicit disk image size.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                image_size=MiB(5),
                output=None,
                unpackdir=None,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            state.rootfs_size = MiB(1)
            # Mock the run() call to prove that we never call dd.
            resources.enter_context(patch('ubuntu_image.builder.run'))
            next(state)
            self.assertEqual(state.image_size, MiB(5))

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
                unpackdir=None,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='da',
                filesystem=FileSystemType.none,
                size=MiB(1),
                offset=0,
                offset_write=None,
                )
            volume = SimpleNamespace(
                structures=[part0],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            state.rootfs_size = MiB(1)
            # Mock the run() call to prove that we never call dd.
            resources.enter_context(patch('ubuntu_image.builder.run'))
            mock = resources.enter_context(
                patch('ubuntu_image.builder._logger.warning'))
            next(state)
            self.assertEqual(state.image_size, 2114560)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring --image-size=1M smaller '
                'than minimum required size 2114560')

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
                unpackdir=None,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.prepare_filesystems)
            # Craft a gadget schema.
            part0 = SimpleNamespace(
                name='alpha',
                type='aa',
                size=MiB(1),
                offset=MiB(2),
                offset_write=100,
                filesystem=FileSystemType.ext4,
                filesystem_label='alpha',
                )
            part1 = SimpleNamespace(
                name='beta',
                type='bb',
                size=MiB(1),
                offset=MiB(4),
                offset_write=200,
                filesystem=FileSystemType.ext4,
                filesystem_label='beta',
                )
            part2 = SimpleNamespace(
                name='gamma',
                type='mbr',
                size=MiB(1),
                offset=0,
                offset_write=None,
                filesystem=FileSystemType.ext4,
                filesystem_label='gamma',
                )
            volume = SimpleNamespace(
                # gadget.yaml appearance order which does not match the disk
                # offset order.  LP: #1642999
                structures=[part1, part0, part2],
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            state.rootfs_size = MiB(1)
            # Mock the run() call to prove that we never call dd.
            resources.enter_context(patch('ubuntu_image.builder.run'))
            mock = resources.enter_context(
                patch('ubuntu_image.builder._logger.warning'))
            next(state)
            # The actual image size is 6MiB + 17KiB.  The former value comes
            # from the farthest out structure (part1 at offset 4MiB + 1MiB
            # size) + the rootfs size of 1MiB.  The latter comes from the
            # empirically derived 34 sector GPT backup space.
            self.assertEqual(state.image_size, 6308864)
            self.assertEqual(len(mock.call_args_list), 1)
            posargs, kwargs = mock.call_args_list[0]
            self.assertEqual(
                posargs[0],
                'Ignoring --image-size=3M smaller '
                'than minimum required size 6308864')

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
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                cloud_init=None,
                output=None,
                unpackdir=unpackdir,
                workdir=workdir,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.image_size = MiB(256)
            os.makedirs(state.images)
            # Craft a gadget schema.  This is based on the official pi3-kernel
            # gadget.yaml file.
            contents0 = SimpleNamespace(
                source='boot-assets/',
                target='/',
                )
            part0 = SimpleNamespace(
                name=None,
                filesystem_label='system-boot',
                filesystem='vfat',
                type='0C',
                size=MiB(128),
                offset=MiB(1),
                offset_write=None,
                contents=[contents0],
                )
            volume0 = SimpleNamespace(
                schema=VolumeSchema.mbr,
                bootloader=BootLoader.uboot,
                structures=[part0],
                )
            state.gadget = SimpleNamespace(
                volumes=dict(pi3=volume0),
                )
            # Set up images for the targeted test.  The important thing here
            # is that the root partition gets sizes to a non-multiple of 1KiB.
            part0_img = os.path.join(state.images, 'part0.img')
            with open(part0_img, 'wb') as fp:
                fp.write(b'\1' * 11)
            state.root_img = os.path.join(state.images, 'root.img')
            state.rootfs_size = 947980
            state.rootfs_offset = MiB(129)
            with open(state.root_img, 'wb') as fp:
                fp.write(b'\2' * 947980)
            state.boot_images = [part0_img]
            # Create the disk.
            next(state)
            # The root file system must be at least 947980 bytes.
            proc = run('sfdisk --json {}'.format(state.disk_img))
            layout = json.loads(proc.stdout)
            partition1 = layout['partitiontable']['partitions'][1]
            # sfdisk returns size in sectors.  947980 bytes rounded up to 512
            # byte sectors.
            self.assertGreaterEqual(partition1['size'], 1852)

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
                extra_snaps=[],
                model_assertion=self.model_assertion,
                output=None,
                workdir=workdir,
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
                extra_snaps=[],
                model_assertion=self.model_assertion,
                output=None,
                workdir=workdir,
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
