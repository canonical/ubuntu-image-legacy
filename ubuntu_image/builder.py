"""Flow for building a disk image."""

import os
import shutil
import logging

from math import ceil
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import MiB, mkfs_ext4, run, snap
from ubuntu_image.image import Image, MBRImage
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole, VolumeSchema,
    parse as parse_yaml)
from ubuntu_image.state import State


SPACE = ' '
_logger = logging.getLogger('ubuntu-image')


class TMPNotReadableFromOutsideSnap(Exception):
    """ubuntu-image snap cannot write images to /tmp"""


class ModelAssertionBuilder(State):
    def __init__(self, args):
        super().__init__()
        # The working directory will contain several bits as we stitch
        # everything together.  It will contain the final disk image file
        # (unless output is given).  It will contain an unpack/ directory
        # which is where `snap prepare-image` will put its contents.  It will
        # contain a system-data/ directory which containing everything needed
        # for the final root file system (e.g. an empty boot/ mount point, the
        # snap/ directory and a var/ hierarchy containing snaps and
        # sideinfos), and it will contain a boot/ directory with the grub
        # files.
        self.workdir = (
            self.resources.enter_context(TemporaryDirectory())
            if args.workdir is None
            else args.workdir)
        # Where the disk.img file ends up.  /tmp to a snap is not the same
        # /tmp outside of the snap.  When running as a snap, don't allow the
        # user to output a disk image to a location that won't exist for them.
        # When run as a snap, /tmp is not writable.
        if any(key.startswith('SNAP') for key in os.environ):
            # The output directories, in order of precedence.
            for path in (args.output, args.output_dir, os.getcwd()):
                if path is None:
                    continue
                path = os.sep.join(path.split(os.sep)[:2])
                if path == '/tmp':
                    raise TMPNotReadableFromOutsideSnap
                else:
                    # This path is okay and since it'll take precedence, we're
                    # done checking.
                    break
        self.output_dir = args.output_dir
        self.output = args.output
        # Information passed between states.
        self.rootfs = None
        self.rootfs_size = 0
        self.part_images = None
        self.image_size = 0
        self.bootfs = None
        self.bootfs_sizes = None
        self.images = None
        self.entry = None
        self.disk_img = None
        self.gadget = None
        self.args = args
        self.unpackdir = None
        self.cloud_init = args.cloud_init
        self.exitcode = 0
        self._next.append(self.make_temporary_directories)

    def __getstate__(self):
        state = super().__getstate__()
        state.update(
            args=self.args,
            bootfs=self.bootfs,
            bootfs_sizes=self.bootfs_sizes,
            cloud_init=self.cloud_init,
            disk_img=self.disk_img,
            exitcode=self.exitcode,
            gadget=self.gadget,
            image_size=self.image_size,
            images=self.images,
            output=self.output,
            output_dir=self.output_dir,
            part_images=self.part_images,
            rootfs=self.rootfs,
            rootfs_size=self.rootfs_size,
            unpackdir=self.unpackdir,
            )
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        self.args = state['args']
        self.bootfs = state['bootfs']
        self.bootfs_sizes = state['bootfs_sizes']
        self.cloud_init = state['cloud_init']
        self.disk_img = state['disk_img']
        self.exitcode = state['exitcode']
        self.gadget = state['gadget']
        self.image_size = state['image_size']
        self.images = state['images']
        self.output = state['output']
        self.output_dir = state['output_dir']
        self.part_images = state['part_images']
        self.rootfs = state['rootfs']
        self.rootfs_size = state['rootfs_size']
        self.unpackdir = state['unpackdir']

    def _log_exception(self, name):
        # Only log the exception if we're in debug mode.
        if self.args.debug:
            super()._log_exception(name)

    def make_temporary_directories(self):
        self.rootfs = os.path.join(self.workdir, 'root')
        self.unpackdir = os.path.join(self.workdir, 'unpack')
        os.makedirs(self.rootfs)
        # Despite the documentation, `snap prepare-image` doesn't create the
        # gadget/ directory.
        os.makedirs(os.path.join(self.unpackdir, 'gadget'))
        self._next.append(self.prepare_image)

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
            self._next.append(self.load_gadget_yaml)

    def load_gadget_yaml(self):
        yaml_file = os.path.join(
            self.unpackdir, 'gadget', 'meta', 'gadget.yaml')
        # Preserve the gadget.yaml in the working dir.
        shutil.copy(yaml_file, self.workdir)
        with open(yaml_file, 'r', encoding='utf-8') as fp:
            self.gadget = parse_yaml(fp)
        # Based on the -o/--output and -O/--output-dir options, and the volumes
        # in the gadget.yaml file, we can now calculate where the generated
        # disk images should go.  We'll write them directly to the final
        # destination so they don't have to be moved later.  Here is the
        # option precedence:
        #
        # * The location specified by -o/--output;
        # * <output_dir>/<volume_name>.img
        # * <work_dir>/disk.img
        if self.output is not None:
            self.disk_img = self.output
        elif self.output_dir is not None:
            os.makedirs(self.output_dir, exist_ok=True)
            volumes = self.gadget.volumes.keys()
            assert len(volumes) == 1, 'For now, only one volume is allowed'
            volume = list(volumes)[0]
            self.disk_img = os.path.join(
                self.output_dir, '{}.img'.format(volume))
        else:
            self.disk_img = os.path.join(self.workdir, 'disk.img')
        self._next.append(self.populate_rootfs_contents)

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
        self._next.append(self.calculate_rootfs_size)

    @staticmethod
    def _calculate_dirsize(path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                total += os.path.getsize(os.path.join(dirpath, filename))
        # Fudge factor for incidentals.
        total *= 1.5
        return ceil(total)

    def calculate_rootfs_size(self):
        # Calculate the size of the root file system.  Basically, I'm trying
        # to reproduce du(1) close enough without having to call out to it and
        # parse its output.
        # On a 100MiB filesystem, ext4 takes a little over 7MiB for the
        # metadata.  Use 8MiB as a minimum padding here.
        self.rootfs_size = self._calculate_dirsize(self.rootfs) + MiB(8)
        self._next.append(self.pre_populate_bootfs_contents)

    def pre_populate_bootfs_contents(self):
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        for partnum, part in enumerate(volume.structures):
            target_dir = os.path.join(self.workdir, 'part{}'.format(partnum))
            os.makedirs(target_dir, exist_ok=True)
        self._next.append(self.populate_bootfs_contents)

    def populate_bootfs_contents(self):
        # XXX We currently support only one volume specification.
        assert len(self.gadget.volumes) == 1, (
            'For now, only one volume is allowed')
        # The unpack directory has a boot/ directory inside it.  The contents
        # of this directory (but not the parent <unpack>/boot directory
        # itself) needs to be moved to the bootfs directory.
        volume = list(self.gadget.volumes.values())[0]
        # At least one structure is required.
        for partnum, part in enumerate(volume.structures):
            target_dir = os.path.join(self.workdir, 'part{}'.format(partnum))
            if part.role is StructureRole.system_boot:
                self.bootfs = target_dir
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
        self._next.append(self.calculate_bootfs_size)

    def calculate_bootfs_size(self):
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        self.bootfs_sizes = {}
        # At least one structure is required.
        for i, part in enumerate(volume.structures):
            if part.filesystem is FileSystemType.none:
                continue
            partnum = 'part{}'.format(i)
            target_dir = os.path.join(self.workdir, partnum)
            self.bootfs_sizes[partnum] = self._calculate_dirsize(target_dir)
        self._next.append(self.prepare_filesystems)

    def prepare_filesystems(self):
        self.images = os.path.join(self.workdir, '.images')
        os.makedirs(self.images)
        # The image for the boot partition.
        self.part_images = []
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        farthest_offset = 0
        for partnum, part in enumerate(volume.structures):
            part_img = os.path.join(self.images, 'part{}.img'.format(partnum))
            if part.role is StructureRole.system_data:
                # The image for the root partition.
                if part.size is None:
                    part.size = self.rootfs_size
                elif part.size < self.rootfs_size:
                    _logger.warning('rootfs partition size ({}) smaller than '
                                    'actual rootfs contents {}'.format(
                                        part.size, self.rootfs_size))
                    part.size = self.rootfs_size
                # We defer creating the root file system image because we have
                # to populate it at the same time.  See mkfs.ext4(8) for
                # details.
                Path(part_img).touch()
                os.truncate(part_img, self.rootfs_size)
            else:
                run('dd if=/dev/zero of={} count=0 bs={} seek=1'.format(
                    part_img, part.size))
                if part.filesystem is FileSystemType.vfat:
                    label_option = (
                        '-n {}'.format(part.filesystem_label)
                        # XXX I think this could be None or the empty string,
                        # but this needs verification.
                        if part.filesystem_label
                        else '')
                    # XXX: hard-coding of sector size.
                    run('mkfs.vfat -s 1 -S 512 -F 32 {} {}'.format(
                        label_option, part_img))
            self.part_images.append(part_img)
            farthest_offset = max(farthest_offset, (part.offset + part.size))
        # Calculate or check the final image size.
        #
        # XXX: Hard-codes last 34 512-byte sectors for backup GPT,
        # empirically derived from sgdisk behavior.
        calculated = ceil(farthest_offset / 1024 + 17) * 1024
        if self.args.image_size is None:
            self.image_size = calculated
        else:
            if self.args.image_size < calculated:
                _logger.warning('Ignoring --image-size={} smaller '
                                'than minimum required size {}'.format(
                                    self.args.given_image_size, calculated))
                self.image_size = calculated
            else:
                self.image_size = self.args.image_size
        self._next.append(self.populate_filesystems)

    def populate_filesystems(self):
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        for partnum, part in enumerate(volume.structures):
            part_img = self.part_images[partnum]
            part_dir = os.path.join(self.workdir, 'part{}'.format(partnum))
            if part.role is StructureRole.system_data:
                # The root partition needs to be ext4, which may or may not be
                # populated at creation time, depending on the version of
                # e2fsprogs.
                mkfs_ext4(part_img, self.rootfs, part.filesystem_label)
            elif part.filesystem is FileSystemType.none:
                image = Image(part_img, part.size)
                offset = 0
                for content in part.content:
                    src = os.path.join(self.unpackdir, 'gadget', content.image)
                    file_size = os.path.getsize(src)
                    assert content.size is None or content.size >= file_size, (
                        'Spec size {} < actual size {} of: {}'.format(
                            content.size, file_size, content.image))
                    if content.size is not None:
                        file_size = content.size
                    # XXX: We need to check for overlapping images.
                    if content.offset is not None:
                        offset = content.offset
                    # XXX: We must check offset+size vs. the target image.
                    image.copy_blob(src, bs=1, seek=offset, conv='notrunc')
                    offset += file_size
            elif part.filesystem is FileSystemType.vfat:
                sourcefiles = SPACE.join(
                    os.path.join(part_dir, filename)
                    for filename in os.listdir(part_dir)
                    )
                env = dict(MTOOLS_SKIP_CHECK='1')
                env.update(os.environ)
                run('mcopy -s -i {} {} ::'.format(part_img, sourcefiles),
                    env=env)
            elif part.filesystem is FileSystemType.ext4:
                mkfs_ext4(part_img, part_dir, part.filesystem_label)
            else:
                raise AssertionError('Invalid part filesystem type: {}'.format(
                    part.filesystem))
        self._next.append(self.make_disk)

    def make_disk(self):
        part_id = 1
        # Walk through all partitions and write them to the disk image at the
        # lowest permissible offset.  We should not have any overlapping
        # partitions, the parser should have already rejected such as invalid.
        #
        # XXX: The parser should sort these partitions for us in disk order as
        # part of checking for overlaps, so we should not need to sort them
        # here.
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        # XXX: This ought to be a single constructor that figures out the
        # class for us when we pass in the schema.
        if volume.schema is VolumeSchema.mbr:
            image = MBRImage(self.disk_img, self.image_size)
        else:
            image = Image(self.disk_img, self.image_size)
        offset_writes = []
        part_offsets = {}
        for i, part in enumerate(volume.structures):
            if part.name is not None:
                part_offsets[part.name] = part.offset
            if part.offset_write is not None:
                offset_writes.append((part.offset, part.offset_write))
            image.copy_blob(self.part_images[i],
                            bs='1M', seek=part.offset // MiB(1),
                            count=ceil(part.size / MiB(1)),
                            conv='notrunc')
            if part.role is StructureRole.mbr or part.type == 'bare':
                continue
            # sgdisk takes either a sector or a KiB/MiB argument; assume
            # that the offset and size are always multiples of 1MiB.
            #
            # XXX Size must not be zero, which will happen if part.size < 1MiB
            partition_args = dict(
                new='{}M:+{}K'.format(
                    part.offset // MiB(1), ceil(part.size / 1024)),
                typecode=part.type,
                )
            # XXX: special-casing.
            if (volume.schema is VolumeSchema.mbr and
                    part.role is StructureRole.system_boot):
                partition_args['activate'] = True
            elif (volume.schema is VolumeSchema.gpt and
                    part.role is StructureRole.system_data):
                partition_args['change_name'] = 'writable'
            if part.name is not None:
                partition_args['change_name'] = part.name
            image.partition(part_id, **partition_args)
            part_id += 1
        for value, dest in offset_writes:
            # Decipher non-numeric offset_write values.
            if isinstance(dest, tuple):
                dest = part_offsets[dest[0]] + dest[1]
            # XXX: Hard-coding of 512-byte sectors.
            image.write_value_at_offset(value // 512, dest)
        self._next.append(self.finish)

    def finish(self):
        self._next.append(self.close)
