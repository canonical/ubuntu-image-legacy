"""Flow for building a ubuntu core image."""

import os
import shutil
import logging

from subprocess import CalledProcessError
from ubuntu_image.common_builder import AbstractImageBuilderState
from ubuntu_image.helpers import snap
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole)


_logger = logging.getLogger('ubuntu-image')


class ModelAssertionBuilder(AbstractImageBuilderState):
    def __init__(self, args):
        super().__init__(args)

    def prepare_image(self):
        try:
            snap(self.args.model_assertion, self.unpackdir,
                 self.args.channel, self.args.extra_snaps)
        except CalledProcessError:
            if self.args.debug:
                _logger.exception('Full debug traceback follows')
            self.exitcode = 1
            # Stop the state machine right here by not appending a next step.
        else:
            self.yaml_file_path = os.path.join(
                self.unpackdir, 'gadget', 'meta', 'gadget.yaml')
            super().prepare_image()

    def populate_rootfs_contents(self):
        src = os.path.join(self.unpackdir, 'image')
        dst = os.path.join(self.rootfs, 'system-data')
        for subdir in os.listdir(src):
            # LP: #1632134 - copy everything under the image directory except
            # /boot which goes to the boot partition.
            if subdir != 'boot':
                shutil.move(os.path.join(src, subdir),
                            os.path.join(dst, subdir))
        if self.cloud_init is not None:
            # LP: #1633232 - Only write out meta-data when the --cloud-init
            # parameter is given.
            seed_dir = os.path.join(dst, 'var', 'lib', 'cloud', 'seed')
            cloud_dir = os.path.join(seed_dir, 'nocloud-net')
            os.makedirs(cloud_dir, exist_ok=True)
            metadata_file = os.path.join(cloud_dir, 'meta-data')
            with open(metadata_file, 'w', encoding='utf-8') as fp:
                print('instance-id: nocloud-static', file=fp)
            userdata_file = os.path.join(cloud_dir, 'user-data')
            shutil.copy(self.cloud_init, userdata_file)
        # This is just a mount point.
        os.makedirs(os.path.join(dst, 'boot'))
        super().populate_rootfs_contents()

    def _populate_one_bootfs(self, name, volume):
        for partnum, part in enumerate(volume.structures):
            target_dir = os.path.join(volume.basedir, 'part{}'.format(partnum))
            if part.role is StructureRole.system_boot:
                volume.bootfs = target_dir
                if volume.bootloader is BootLoader.uboot:
                    boot = os.path.join(
                        self.unpackdir, 'image', 'boot', 'uboot')
                    ubuntu = target_dir
                elif volume.bootloader is BootLoader.grub:
                    boot = os.path.join(
                        self.unpackdir, 'image', 'boot', 'grub')
                    # XXX: Bad special-casing.  `snap prepare-image` currently
                    # installs to /boot/grub, but we need to map this to
                    # /EFI/ubuntu.  This is because we are using a SecureBoot
                    # signed bootloader image which has this path embedded, so
                    # we need to install our files to there.
                    ubuntu = os.path.join(target_dir, 'EFI', 'ubuntu')
                else:
                    raise ValueError(
                        'Unsupported volume bootloader value: {}'.format(
                            volume.bootloader))
                os.makedirs(ubuntu, exist_ok=True)
                for filename in os.listdir(boot):
                    src = os.path.join(boot, filename)
                    dst = os.path.join(ubuntu, filename)
                    shutil.move(src, dst)
            gadget_dir = os.path.join(self.unpackdir, 'gadget')
            if part.filesystem is not FileSystemType.none:
                for content in part.content:
                    src = os.path.join(gadget_dir, content.source)
                    dst = os.path.join(target_dir, content.target)
                    if content.source.endswith('/'):
                        # This is a directory copy specification.  The target
                        # must also end in a slash.
                        #
                        # XXX: If this is a file instead of a directory, give
                        # a useful error message instead of a traceback.
                        #
                        # XXX: We should assert this constraint in the parser.
                        target, slash, tail = content.target.rpartition('/')
                        if slash != '/' and tail != '':
                            raise ValueError(
                                'target must end in a slash: {}'.format(
                                    content.target))
                        # The target of a recursive directory copy is the
                        # target directory name, with or without a trailing
                        # slash necessary at least to handle the case of
                        # recursive copy into the root directory), so make
                        # sure here that it exists.
                        os.makedirs(dst, exist_ok=True)
                        for filename in os.listdir(src):
                            sub_src = os.path.join(src, filename)
                            dst = os.path.join(target_dir, target, filename)
                            if os.path.isdir(sub_src):
                                shutil.copytree(sub_src, dst, symlinks=True,
                                                ignore_dangling_symlinks=True)
                            else:
                                shutil.copy(sub_src, dst)
                    else:
                        # XXX: If this is a directory instead of a file, give
                        # a useful error message instead of a traceback.
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy(src, dst)

    def populate_bootfs_contents(self):
        for name, volume in self.gadget.volumes.items():
            self._populate_one_bootfs(name, volume)
        super().populate_bootfs_contents()

    def _write_manifest(self, snaps_dir, filename):
        if os.path.isdir(snaps_dir):
            manifest_path = os.path.join(self.output_dir, filename)
            with open(manifest_path, 'w') as manifest:
                for file in os.listdir(snaps_dir):
                    if file.endswith('.snap'):
                        parts = file[:-5].rpartition('_')
                        manifest.write('{} {}\n'.format(parts[0], parts[2]))

    def generate_manifests(self):
        # After the images are built, we would also like to have some image
        # manifests exported so that one can easily check what snap packages
        # have been installed as part of the image.
        # We generate two files - one based off the snaps/ directory and other
        # basing on the contents of seed/snaps.
        # snaps.manifest
        snaps_dir = os.path.join(
            self.rootfs, 'system-data', 'var', 'lib', 'snapd', 'snaps')
        self._write_manifest(snaps_dir, 'snaps.manifest')
        # seed.manifest
        seed_dir = os.path.join(
            self.rootfs, 'system-data', 'var', 'lib', 'snapd', 'seed', 'snaps')
        self._write_manifest(seed_dir, 'seed.manifest')
        super().generate_manifests()
