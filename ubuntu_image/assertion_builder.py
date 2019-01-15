"""Flow for building a ubuntu core image."""

import os
import shutil
import logging

from subprocess import CalledProcessError
from ubuntu_image.common_builder import AbstractImageBuilderState
from ubuntu_image.helpers import snap
from ubuntu_image.image import Image
from ubuntu_image.parser import StructureRole


SYSTEMBOOT_BACKUP = 'system-boot.img'
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
        etc_cloud = os.path.join(dst, 'etc', 'cloud')
        if os.path.isdir(etc_cloud) and not os.listdir(etc_cloud):
            # The snap --prepare-image command creates /etc/cloud even if
            # it's empty.  We don't want to copy it over into the final rootfs
            # in that case as it can cause issues when base snaps want to ship
            # default configuration there.
            os.rmdir(etc_cloud)
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

    def populate_bootfs_contents(self):
        super().populate_bootfs_contents()
        self._next.append(self.populate_recovery_contents)

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

    def populate_recovery_contents(self):
        recovery = False
        target_dir = None
        boot_target_dir = None
        boot_part = None
        boot_schema = None
        # Check if a recovery partition has been specified
        for _, volume in self.gadget.volumes.items():
            for partnum, part in enumerate(volume.structures):
                if part.role is StructureRole.system_boot:
                    boot_target_dir = os.path.join(
                        volume.basedir, 'part{}'.format(partnum))
                    boot_part = part
                    boot_schema = volume.schema
                if part.role is StructureRole.system_recovery:
                    target_dir = os.path.join(
                        volume.basedir, 'part{}'.format(partnum))
                    recovery = True
                if recovery and target_dir and boot_target_dir:
                    break
        if recovery and target_dir and boot_target_dir:
            # Move the seed directory to the system-recovery partition
            src = os.path.join(
                self.rootfs, 'system-data', 'var', 'lib', 'snapd', 'seed')
            dst = os.path.join(target_dir, 'seed')
            shutil.move(src, dst)
            # Backup the boot partition to the system-recovery partition
            self._backup_system_boot(
                target_dir, boot_target_dir, boot_part, boot_schema)
        self._next.append(self.prepare_filesystems)

    def _backup_system_boot(
            self, target_dir, boot_target_dir, part, boot_schema):
        # Prepare the image file for system-boot
        imgfile = os.path.join(target_dir, SYSTEMBOOT_BACKUP)
        Image(imgfile, part.size, boot_schema)
        self._prepare_image(imgfile, part)

        # Copy the system-boot files to the image
        self._populate_vfat_image(boot_target_dir, imgfile)
