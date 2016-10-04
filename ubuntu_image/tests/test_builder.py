"""Test image building."""

import os
import re

from contextlib import ExitStack
from itertools import product
from pkg_resources import resource_filename
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.parser import BootLoader, FileSystemType
from ubuntu_image.testing.helpers import XXXModelAssertionBuilder
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
COMMASPACE = ', '


# For convenience.
def utf8open(path):
    return open(path, 'r', encoding='utf-8')


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
            workdir=None,
            output=output,
            model_assertion=self.model_assertion,
            cloud_init=None,
            extra_snaps=None,
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

    def test_snap_gets_called(self):
        # This exists for coverage under Travis-CI which normally won't run
        # the snap command because the mount that snap does can't be performed
        # in a docker container.
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            cloud_init=None,
            extra_snaps=[],
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            mock = resources.enter_context(patch('ubuntu_image.builder.snap'))
            state.run_thru('prepare_image')
            all_call_args = mock.call_args_list
            self.assertEqual(len(all_call_args), 1)
            # The second argument is a temporary directory, so just check the
            # first and last arguments.
            first_call = all_call_args[0][0]
            self.assertEqual(first_call[0], self.model_assertion)
            self.assertEqual(first_call[2], 'edge')

    def test_populate_rootfs_contents(self):
        # This exists for coverage under Travis-CI which normally won't run
        # the snap command because the mount that snap does can't be performed
        # in a docker container.
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            cloud_init=None,
            extra_snaps=None,
            )
        with ExitStack() as resources:
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
            self.assertEqual(set(os.listdir(system_data)), {'boot', 'var'})

    def test_populate_rootfs_contents_with_cloud_init(self):
        with ExitStack() as resources:
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', file=cloud_init)
            cloud_init.flush()
            args = SimpleNamespace(
                channel='edge',
                workdir=None,
                model_assertion=self.model_assertion,
                output=None,
                cloud_init=cloud_init.name,
                extra_snaps=None,
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
            # Did the user data get copied?
            user_data = os.path.join(
                state.rootfs, 'system-data', 'var', 'lib', 'cloud', 'seed',
                'nocloud-net', 'user-data')
            with open(user_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'cloud init user data')

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
                workdir=workdir,
                unpackdir=unpackdir,
                output=None,
                cloud_init=None,
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
                workdir=workdir,
                unpackdir=unpackdir,
                output=None,
                cloud_init=None,
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
                workdir=workdir,
                unpackdir=unpackdir,
                output=None,
                cloud_init=None,
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
                workdir=workdir,
                unpackdir=unpackdir,
                output=None,
                cloud_init=None,
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
                workdir=workdir,
                unpackdir=unpackdir,
                output=None,
                cloud_init=None,
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
