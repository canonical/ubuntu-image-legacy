"""Flow for building a ubuntu core image."""

import os
import shutil
import logging

from subprocess import CalledProcessError
from ubuntu_image.common_builder import AbstractImageBuilderState
from ubuntu_image.helpers import snap


_logger = logging.getLogger('ubuntu-image')


class ModelAssertionBuilder(AbstractImageBuilderState):
    def __init__(self, args):
        super().__init__(args)

    def prepare_image(self):
        # Since some people might still use the deprecated extra-snaps syntax,
        # combine the two argument lists before sending it out to
        # prepare-image.
        extra_snaps = (self.args.snap or []) + (self.args.extra_snaps or [])
        try:
            snap(self.args.model_assertion, self.unpackdir, self.workdir,
                 channel=self.args.channel, extra_snaps=extra_snaps,
                 cloud_init=self.cloud_init,
                 disable_console_conf=self.disable_console_conf,
                 factory_image=self.factory_image, validation=self.validation)
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
        if self.gadget.seeded:
            # For now, since we only create the system-seed partition for
            # uc20 images, we hard-code to use this path for the rootfs
            # seed population.  In the future we might want to consider
            # populating other partitions from `snap prepare-image` output
            # as well, so looking into directories like system-data/ etc.
            src = os.path.join(self.unpackdir, 'system-seed')
            dst = self.rootfs
        else:
            src = os.path.join(self.unpackdir, 'image')
            dst = os.path.join(self.rootfs, 'system-data')
            # This is just a mount point.
            os.makedirs(os.path.join(dst, 'boot'), exist_ok=True)
        for subdir in os.listdir(src):
            # LP: #1632134 - copy everything under the image directory except
            # /boot which goes to the boot partition. Unless this is a uc20
            # system which has everything under "system-seed".
            if not self.gadget.seeded and subdir == 'boot':
                continue
            shutil.move(os.path.join(src, subdir),
                        os.path.join(dst, subdir))
        etc_cloud = os.path.join(dst, 'etc', 'cloud')
        if os.path.isdir(etc_cloud) and not os.listdir(etc_cloud):
            # The snap --prepare-image command creates /etc/cloud even if
            # it's empty.  We don't want to copy it over into the final rootfs
            # in that case as it can cause issues when base snaps want to ship
            # default configuration there.
            os.rmdir(etc_cloud)
        super().populate_rootfs_contents()

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
        if self.gadget.seeded:
            # For uc20 builds, the snaps are located in a different directory.
            seed_dir = os.path.join(
                self.rootfs, 'snaps')
        else:
            seed_dir = os.path.join(
                self.rootfs, 'system-data', 'var', 'lib', 'snapd', 'seed',
                'snaps')
        self._write_manifest(seed_dir, 'seed.manifest')
        super().generate_manifests()
