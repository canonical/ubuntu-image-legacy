"""Test classic image building."""

import os

from contextlib import ExitStack
# from itertools import product
from pkg_resources import resource_filename
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole, VolumeSchema)
from ubuntu_image.testing.helpers import XXXClassicBuilder
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
        self.addCleanup(self._resources.close)
        self.gadget_tree = resource_filename(
            'ubuntu_image.tests.data', 'gadget_tree')

    @skipIf('UBUNTU_IMAGE_TESTS_NO_NETWORK' in os.environ,
            'Cannot run this test without network access')
    def test_fs_contents(self):
        # Run the action classic builder through the steps needed to
        # at least call `lb config && lb build`.
        output = self._resources.enter_context(NamedTemporaryFile())
        args = SimpleNamespace(
            project='ubuntu-cpc',
            suite='xenial',
            arch='amd64',
            image_format='img',
            output=output.name,
            subproject=None,
            subarch=None,
            output_dir=None,
            workdir=None,
            cloud_init=None,
            with_proposed=None,
            extra_ppas=None,
            gadget_tree=self.gadget_tree,
            )
        state = self._resources.enter_context(XXXClassicBuilder(args))
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

        dirs_under_rootfs = ['bin', 'boot', 'dev', 'etc', 'home', 'initrd.img',
                             'lib', 'lib64', 'media', 'mnt', 'opt', 'proc',
                             'root', 'run', 'sbin', 'snap', 'srv', 'sys',
                             'tmp', 'usr', 'var', 'vmlinuz']
        for dirname in dirs_under_rootfs:
            path = os.path.join(state.rootfs,  dirname)
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
                proposed=None,
                extra_ppas=None,
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
            # Both the user data and the seed metadata should exist.
            fstab_data = os.path.join(state.rootfs, 'etc', 'fstab')
            with open(fstab_data, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'LABEL=cloudimg-rootfs   '
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
                proposed=None,
                extra_ppas=None,
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
                proposed=None,
                extra_ppas=None,
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

    def test_bootloader_options_uboot(self):
        # This test provides coverage for populate_bootfs_contents() when the
        # uboot bootloader is used. The bootloader bits are fetched from ubuntu
        # archive via the following command when we have network connectivity
        # `apt-get install shim-signed grub-pc-bin grub-efi-amd64-signed`
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
                cloud_init=None,
                output=None,
                subproject=None,
                subarch=None,
                output_dir=None,
                proposed=None,
                extra_ppas=None,
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Since we're not running make_temporary_directories(), just set
            # up some additional expected state.
            # state.unpackdir = unpackdir

            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            content1 = SimpleNamespace(
                source='/tmp/grubx64.efi.signed',
                target='EFI/boot/grubx64.efi',
                )
            content2 = SimpleNamespace(
                source='/tmp/shimx64.efi.signed',
                target='EFI/boot/bootx64.efi',
                )
            content3 = SimpleNamespace(
                source='grub.cfg',
                target='EFI/ubuntu/grub.cfg',
                )
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                content=[content1, content2, content3]
                )
            volume = SimpleNamespace(
                structures=[part],
                bootloader=BootLoader.uboot,
                )
            state.gadget = SimpleNamespace(
                volumes=dict(volume1=volume),
                )
            prep_state(state, workdir)
            # We fetch the bootloader bits(i.e. boot.img) from ubuntu archive
            # and have grub configuration file(under gadget_tree) in place.
            with open(os.path.join('/tmp/', 'grubx64.efi.signed'), 'wb') as fp:
                fp.write(b'01234')
            with open(os.path.join('/tmp/', 'shimx64.efi.signed'), 'wb') as fp:
                fp.write(b'56789')
            next(state)
            # Did the boot data get copied?
            part0_dir = os.path.join(state.volumedir, 'volume1', 'part0')
            with open(os.path.join(part0_dir, 'EFI', 'boot', 'grubx64.efi'),
                      'rb') as fp:
                self.assertEqual(fp.read(), b'01234')
            with open(os.path.join(part0_dir, 'EFI', 'boot', 'bootx64.efi'),
                      'rb') as fp:
                self.assertEqual(fp.read(), b'56789')
            with open(os.path.join(part0_dir, 'EFI', 'ubuntu', 'grub.cfg'),
                      'rb') as fp:
                with open(os.path.join(self.gadget_tree, 'grub.cfg'),
                          'rb') as org_fp:
                    self.assertEqual(fp.read(), org_fp.read())

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
                proposed=None,
                extra_ppas=None,
                gadget_tree=self.gadget_tree,
                )
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            # Now we have to craft enough of gadget definition to drive the
            # method under test.
            content1 = SimpleNamespace(
                source='grub.cfg',
                target='EFI/ubuntu/grub.cfg',
                )
            part = SimpleNamespace(
                role=StructureRole.system_boot,
                filesystem_label='system-boot',
                filesystem=FileSystemType.none,
                content=[content1],
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
                proposed=None,
                extra_ppas=None,
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
                proposed=None,
                extra_ppas=None,
                gadget_tree=self.gadget_tree,
                )
            # Jump right to the method under test.
            state = resources.enter_context(XXXClassicBuilder(args))
            state._next.pop()
            state._next.append(state.populate_filesystems)
            # Set up expected state.
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
            # They all are placed # in workdir in the end.
            with open(os.path.join(workdir, 'image1.img'), 'wb') as fp:
                fp.write(b'\1' * 47)
            with open(os.path.join(workdir, 'image2.img'), 'wb') as fp:
                fp.write(b'\2' * 19)
            with open(os.path.join(workdir, 'image3.img'), 'wb') as fp:
                fp.write(b'\3' * 51)
            with open(os.path.join(workdir, 'image4.img'), 'wb') as fp:
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
