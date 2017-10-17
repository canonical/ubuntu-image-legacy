"""Test classic image building."""

import os
import json
import logging

from contextlib import ExitStack
# from itertools import product
from os import stat
from pkg_resources import resource_filename
from pwd import getpwuid
from subprocess import CalledProcessError, PIPE
from tempfile import NamedTemporaryFile, TemporaryDirectory
from textwrap import dedent
from types import SimpleNamespace
from ubuntu_image.helpers import MiB, run
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole, VolumeSchema)
from ubuntu_image.testing.helpers import (
     DIRS_UNDER_ROOTFS, LiveBuildMocker, LogCapture, XXXClassicBuilder)
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
COMMASPACE = ', '


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


class TestClassicBuilder(TestCase):
    # XXX These tests relies on external resources, namely that the rootfs can
    # actually be downloaded from the ubuntu archive
    # That's a test isolation bug and a potential source of test
    # brittleness. We should fix this.
    #
    # XXX These tests also requires root, because `lb build`
    # currently requires it.

    def setUp(self):
        self._resources = ExitStack()
        # Mock out the check_root_privilege call
        self._resources.enter_context(
            patch('ubuntu_image.classic_builder.check_root_privilege'))
        self.addCleanup(self._resources.close)
        self.gadget_tree = resource_filename(
            'ubuntu_image.tests.data', 'gadget_tree')

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_prepare_gadget_tree_locally(self):
        # Run the action classic builder through the steps needed to
        # at least call `snapcraft prime`.
        # To create pc-boot.img and pc-core.img, we need to fetch
        # packages like grub-pc-bin, shim-signed from ubuntu archive,
        # even if gadget tree is placed locally on the machine.
        workdir = self._resources.enter_context(TemporaryDirectory())
        args = SimpleNamespace(
            project='ubuntu-cpc',
            suite='xenial',
            arch='amd64',
            image_format='img',
            output=None,
            subproject=None,
            subarch=None,
            output_dir=None,
            workdir=workdir,
            cloud_init=None,
            with_with_proposed=None,
            extra_ppas=None,
            hooks_directory=[],
            gadget_tree=self.gadget_tree,
            )
        state = self._resources.enter_context(XXXClassicBuilder(args))
        gadget_dir = os.path.join(workdir, 'unpack', 'gadget')

        state.run_thru('prepare_gadget_tree')
        files = [
            '{gadget_dir}/grub-cpc.cfg',
            '{gadget_dir}/grubx64.efi',
            '{gadget_dir}/pc-boot.img',
            '{gadget_dir}/pc-core.img',
            '{gadget_dir}/shim.efi.signed',
            '{gadget_dir}/meta/gadget.yaml',
            ]
        # Check if all needed bootloader bits are in place.
        for filename in files:
            path = filename.format(
                gadget_dir=gadget_dir,
                )
            self.assertTrue(os.path.exists(path), path)

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_prepare_gadget_tree_remotely(self):
        # Hosting a project under https://github.com/snapcore instead of
        # a personal repository sounds more reasonable.
        workdir = self._resources.enter_context(TemporaryDirectory())
        args = SimpleNamespace(
            project='ubuntu-cpc',
            suite='xenial',
            arch='amd64',
            image_format='img',
            output=None,
            subproject=None,
            subarch=None,
            output_dir=None,
            workdir=workdir,
            cloud_init=None,
            with_with_proposed=None,
            extra_ppas=None,
            hooks_directory=[],
            gadget_tree='https://github.com/adglkh/pc-amd64-gadget-cpc',
            )
        state = self._resources.enter_context(XXXClassicBuilder(args))
        gadget_dir = os.path.join(workdir, 'unpack', 'gadget')
        state.run_thru('prepare_gadget_tree')
        files = [
            '{gadget_dir}/grub-cpc.cfg',
            '{gadget_dir}/grubx64.efi',
            '{gadget_dir}/pc-boot.img',
            '{gadget_dir}/pc-core.img',
            '{gadget_dir}/shim.efi.signed',
            '{gadget_dir}/meta/gadget.yaml',
            ]
        # Check if all needed bootloader bits are in place.
        for filename in files:
            path = filename.format(
                gadget_dir=gadget_dir,
                )
            self.assertTrue(os.path.exists(path), path)

    def test_fs_contents(self):
        # Run the action classic builder through the steps needed to
        # at least call `lb config && lb build`.
        output = self._resources.enter_context(NamedTemporaryFile())
        workdir = self._resources.enter_context(TemporaryDirectory())
        unpackdir = os.path.join(workdir, 'unpack')
        mock = LiveBuildMocker(unpackdir)
        args = SimpleNamespace(
            project='ubuntu-cpc',
            suite='xenial',
            arch='amd64',
            image_format='img',
            output=output.name,
            subproject='subproject',
            subarch='subarch',
            output_dir=None,
            workdir=workdir,
            cloud_init=None,
            with_proposed='1',
            extra_ppas='ppa:some/ppa',
            hooks_directory=[],
            gadget_tree=self.gadget_tree,
            )
        state = self._resources.enter_context(XXXClassicBuilder(args))
        # Mock out rootfs generation `live_build`
        # and create dummy top-level filesystem layout.
        self._resources.enter_context(
            patch('ubuntu_image.helpers.run', mock.run))
        state.run_thru('populate_bootfs_contents')
        # How does the root and boot file systems look?
        files = [
            '{boot}/EFI/boot/bootx64.efi',
            '{boot}/EFI/boot/grubx64.efi',
            '{boot}/EFI/ubuntu/grub.cfg',
            '{root}/boot/',
            ]
        for filename in files:
            path = filename.format(
                root=state.rootfs,
                boot=state.gadget.volumes['pc'].bootfs,
                )
            self.assertTrue(os.path.exists(path), path)
        # Simply check if all top-level files and folders exist.
        for dirname in DIRS_UNDER_ROOTFS:
            path = os.path.join(state.rootfs, dirname)
            self.assertTrue(os.path.exists(path), path)

    def test_populate_rootfs_contents_fstab_label(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                workdir=workdir,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                cloud_init=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_data,
                filesystem_label='writable',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            etc_path = os.path.join(state.unpackdir, 'chroot', 'etc')
            os.makedirs(etc_path)
            with open(os.path.join(etc_path, 'fstab'), 'w') as fp:
                fp.write('LABEL=cloudimg-rootfs   /    ext4   defaults    0 0')
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # The seed metadata should exist.
            # And the filesystem label should be modified to 'writable'
            fstab_data = os.path.join(state.rootfs, 'etc', 'fstab')
            with open(fstab_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'LABEL=writable   '
                                            '/    ext4   defaults    0 0')

    def test_populate_rootfs_contents_empty_fstab_entry(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                workdir=workdir,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                cloud_init=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            part = SimpleNamespace(
                role=StructureRole.system_data,
                filesystem_label='writable',
                filesystem=FileSystemType.none,
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                schema=VolumeSchema.gpt,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            etc_path = os.path.join(state.unpackdir, 'chroot', 'etc')
            os.makedirs(etc_path)
            with open(os.path.join(etc_path, 'fstab'), 'w') as fp:
                pass
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # And the filesystem label should be inserted if it doesn't exist.
            fstab_data = os.path.join(state.rootfs, 'etc', 'fstab')
            with open(fstab_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'LABEL=writable   '
                                            '/    ext4   defaults    0 0')

    def test_populate_rootfs_contents_without_cloud_init(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', flush=True, file=cloud_init)
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                workdir=workdir,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                cloud_init=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
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
                schema=VolumeSchema.mbr,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            os.makedirs(os.path.join(state.unpackdir, 'chroot'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # While we're at it, make sure we also remove the old grub dir
            grub_dirs = os.path.join(state.rootfs, 'boot', 'grub', 'test')
            os.makedirs(grub_dirs, exist_ok=True)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # The user data should not have been written and there should be
            # no metadata either.
            seed_path = os.path.join(
                state.rootfs, 'var', 'lib', 'cloud', 'seed', 'nocloud-net')
            self.assertFalse(os.path.exists(
                os.path.join(seed_path, 'user-data')))
            self.assertFalse(os.path.exists(
                os.path.join(seed_path, 'meta-data')))

    def test_populate_rootfs_contents_with_cloud_init(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            cloud_init = resources.enter_context(
                NamedTemporaryFile('w', encoding='utf-8'))
            print('cloud init user data', end='', flush=True, file=cloud_init)
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                cloud_init=cloud_init.name,
                workdir=workdir,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
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
                schema=VolumeSchema.mbr,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            os.makedirs(os.path.join(state.unpackdir, 'chroot'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # Both the user data and the seed metadata should exist.
            seed_path = os.path.join(
                state.rootfs,
                'var', 'lib', 'cloud', 'seed', 'nocloud-net')
            user_data = os.path.join(seed_path, 'user-data')
            meta_data = os.path.join(seed_path, 'meta-data')
            with open(user_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'cloud init user data')
            with open(meta_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'instance-id: nocloud-static\n')

    def test_populate_rootfs_contents_grub_boot_remove(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                workdir=workdir,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                cloud_init=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
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
                schema=VolumeSchema.mbr,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            os.makedirs(os.path.join(state.unpackdir, 'chroot'))
            state.rootfs = resources.enter_context(TemporaryDirectory())
            # Create some dummy files in the grub directory.
            grub_dir = os.path.join(state.rootfs, 'boot', 'grub')
            os.makedirs(grub_dir, exist_ok=True)
            open(os.path.join(grub_dir, 'test'), 'wb').close()
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            # There should be no default boot/grub path present.
            self.assertFalse(os.path.exists(grub_dir))

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
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
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
                role=None,
                filesystem_label='not a boot',
                filesystem=FileSystemType.ext4,
                content=[contents1, contents2],
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
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
            dstbase = os.path.join(workdir, 'volumes', 'volume1', 'part0')
            with open(os.path.join(dstbase, 'at.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(dstbase, 'bt', 'c.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'56789')
            with open(os.path.join(dstbase, 'bt', 'd', 'e.dat'), 'rb') as fp:
                self.assertEqual(fp.read(), b'0abcd')

    def test_bootloader_options_invalid(self):
        # This test provides coverage for populate_bootfs_contents() when the
        # bootloader has a bogus value.
        #
        # We don't want to run the entire state machine just for this test, so
        # we start by setting up enough of the environment for the method
        # under test to function.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                workdir=workdir,
                debug=None,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
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
                )
            prep_state(state, workdir)
            # Don't blat to stderr.
            resources.enter_context(patch('ubuntu_image.state.log'))
            with self.assertRaises(ValueError) as cm:
                next(state)
            self.assertEqual(
                str(cm.exception),
                'Unsupported volume bootloader value: bogus')

    def test_populate_bootfs_contents_content_mismatch(self):
        # If a content source ends in a slash, so must the target.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=None,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.  The two paths (is-a-file and is-a-directory)
            # are differentiated by whether the source ends in a slash or not.
            # In that case, the target must also end in a slash.
            content1 = SimpleNamespace(
                source='bs/',
                # No slash!
                target='bt',
                )
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem=FileSystemType.ext4,
                content=[content1],
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.grub,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
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

    def test_populate_filesystems_none_type(self):
        # We do a bit-wise copy when the file system has no type.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=None,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
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
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir, [part0_img])
            # The source image.
            gadget_dir = os.path.join(unpackdir, 'gadget')
            os.makedirs(gadget_dir)
            with open(os.path.join(gadget_dir, 'image1.img'),
                      'wb') as fp:
                fp.write(b'\1' * 47)
            with open(os.path.join(gadget_dir, 'image2.img'),
                      'wb') as fp:
                fp.write(b'\2' * 19)
            with open(os.path.join(gadget_dir, 'image3.img'),
                      'wb') as fp:
                fp.write(b'\3' * 51)
            with open(os.path.join(gadget_dir, 'image4.img'),
                      'wb') as fp:
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

    def test_gadget_priming_command_fails(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=False,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_gadget_tree)
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
                (logging.ERROR, "COMMAND FAILED: ['snapcraft', 'prime']"),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                ])

    def test_gadget_priming_command_fails_debug(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=True,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
            state.unpackdir = unpackdir
            state._next.pop()
            state._next.append(state.prepare_gadget_tree)
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
            # Note that there is traceback in the output now.
            self.assertEqual(log_capture.logs, [
                (logging.ERROR, "COMMAND FAILED: ['snapcraft', 'prime']"),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                (logging.ERROR, 'Full debug traceback follows'),
                ('IMAGINE THE TRACEBACK HERE'),
                ])

    def test_live_build_command_fails(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=False,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
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
                (logging.ERROR,
                 'COMMAND FAILED: dpkg -L livecd-rootfs | grep "auto$"'),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                ])

    def test_live_build_command_fails_debug(self):
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=True,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
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
            # Note that there is traceback in the output now.
            self.assertEqual(log_capture.logs, [
                (logging.ERROR,
                 'COMMAND FAILED: dpkg -L livecd-rootfs | grep "auto$"'),
                (logging.ERROR, 'command stdout'),
                (logging.ERROR, 'command stderr'),
                (logging.ERROR, 'Full debug traceback follows'),
                ('IMAGINE THE TRACEBACK HERE'),
                ])

    def test_make_disk_with_proper_file_owner(self):
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
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.make_disk)
            # Set up expected state.
            state.unpackdir = unpackdir
            state.images = os.path.join(workdir, '.images')
            state.disk_img = os.path.join(workdir, 'disk.img')
            state.rootfs_size = MiB(1)
            os.makedirs(state.images)
            # Craft a gadget schema.
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
                structures=[part2, part3],
                schema=VolumeSchema.gpt,
                image_size=MiB(10),
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            # Set up images for the targeted test.  These represent the image
            # files that would have already been crafted to write to the disk
            # in early (untested here) stages of the state machine.
            part2_img = os.path.join(state.images, 'part2.img')
            with open(part2_img, 'wb') as fp:
                fp.write(b'\3' * 13)
            root_img = os.path.join(state.images, 'part3.img')
            with open(root_img, 'wb') as fp:
                fp.write(b'\4' * 14)
            prep_state(state, workdir,
                       [part2_img, root_img])
            # Mock out the SUDO_USER by using the login user(USER)
            # to ease the test.
            resources.enter_context(
                    patch.dict(os.environ, {'SUDO_USER': os.environ['USER']}))
            # Create the disk.
            next(state)
            # Verify some parts of the disk.img's content.  First, that we've
            # written the part offsets at the right place.y
            disk_img = os.path.join(outputdir, 'volume1.img')
            with open(disk_img, 'rb') as fp:
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
            self.assertEqual(partitions[0], ('writable', 10240))
            # check the file's owner
            file_owner = getpwuid(stat(disk_img).st_uid).pw_name
            self.assertTrue(os.environ['SUDO_USER'], file_owner)

    def test_generate_manifests_exclude(self):
        # This is not a full test of the manifest generation process as this
        # requires more preparation.  Here we try to see if deprecated words
        # are being removed from the manifest.
        with ExitStack() as resources:
            workdir = resources.enter_context(TemporaryDirectory())
            unpackdir = resources.enter_context(TemporaryDirectory())
            outputdir = resources.enter_context(TemporaryDirectory())
            # Fast forward a state machine to the method under test.
            args = SimpleNamespace(
                project='ubuntu-cpc',
                suite='xenial',
                arch='amd64',
                image_format='img',
                unpackdir=unpackdir,
                workdir=workdir,
                debug=True,
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=outputdir,
                with_proposed=None,
                extra_ppas=None,
                hooks_directory=[],
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.generate_manifests)
            # Mock out the SUDO_USER by using the login user(USER)
            # to ease the test.
            resources.enter_context(
                    patch.dict(os.environ, {'SUDO_USER': os.environ['USER']}))
            # Set up expected state.
            state.rootfs = os.path.join(workdir, 'root')
            test_output = dedent("""\
                                 foo 1.1
                                 bar 3.12.3-0ubuntu1
                                 ubiquity 17.10.8
                                 baz 2.3
                                 casper 1.384
                                 """)

            def run_script(command, *, check=True, **args):
                if 'chroot' in command:
                    stdout = args.pop('stdout', PIPE)
                    stdout.write(test_output)
                    stdout.flush()
                else:
                    pass
            resources.enter_context(patch(
                'ubuntu_image.classic_builder.run',
                side_effect=run_script))
            next(state)
            manifest_path = os.path.join(outputdir, 'filesystem.manifest')
            self.assertTrue(os.path.exists(manifest_path))
            # check the file's owner
            file_owner = getpwuid(stat(manifest_path).st_uid).pw_name
            self.assertTrue(os.environ['SUDO_USER'], file_owner)
            with open(manifest_path) as f:
                self.assertEqual(
                    f.read(),
                    dedent("""\
                           foo 1.1
                           bar 3.12.3-0ubuntu1
                           baz 2.3
                           """))
