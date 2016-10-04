"""Flow for building a disk image."""


import os
import shutil
import logging

from math import ceil
from operator import attrgetter
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import MiB, mkfs_ext4, run, snap, sparse_copy
from ubuntu_image.image import Image, MBRImage
from ubuntu_image.parser import BootLoader, FileSystemType,\
                                VolumeSchema, parse as parse_yaml
from ubuntu_image.state import State


SPACE = ' '
_logger = logging.getLogger('ubuntu-image')


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
        # Where the disk.img file ends up.
        self.output = (
            os.path.join(self.workdir, 'disk.img')
            if args.output is None
            else args.output)
        # Information passed between states.
        self.rootfs = None
        self.rootfs_size = 0
        self.image_size = 0
        self.bootfs = None
        self.bootfs_sizes = None
        self.images = None
        self.boot_images = None
        self.root_img = None
        self.disk_img = None
        self.gadget = None
        self.args = args
        self.unpackdir = None
        self.cloud_init = args.cloud_init
        self._next.append(self.make_temporary_directories)

    def __getstate__(self):
        state = super().__getstate__()
        state.update(
            args=self.args,
            boot_images=self.boot_images,
            bootfs=self.bootfs,
            bootfs_sizes=self.bootfs_sizes,
            disk_img=self.disk_img,
            gadget=self.gadget,
            images=self.images,
            output=self.output,
            root_img=self.root_img,
            rootfs=self.rootfs,
            rootfs_size=self.rootfs_size,
            image_size=self.image_size,
            unpackdir=self.unpackdir,
            cloud_init=self.cloud_init,
            )
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        self.args = state['args']
        self.boot_images = state['boot_images']
        self.bootfs = state['bootfs']
        self.bootfs_sizes = state['bootfs_sizes']
        self.disk_img = state['disk_img']
        self.gadget = state['gadget']
        self.images = state['images']
        self.output = state['output']
        self.root_img = state['root_img']
        self.rootfs = state['rootfs']
        self.rootfs_size = state['rootfs_size']
        self.image_size = state['image_size']
        self.unpackdir = state['unpackdir']
        self.cloud_init = state['cloud_init']

    def make_temporary_directories(self):
        self.rootfs = os.path.join(self.workdir, 'root')
        self.unpackdir = os.path.join(self.workdir, 'unpack')
        os.makedirs(self.rootfs)
        # Despite the documentation, `snap prepare-image` doesn't create the
        # gadget/ directory.
        os.makedirs(os.path.join(self.unpackdir, 'gadget'))
        self._next.append(self.prepare_image)

    def prepare_image(self):
        snap(self.args.model_assertion, self.unpackdir,
             self.args.channel, self.args.extra_snaps)
        self._next.append(self.load_gadget_yaml)

    def load_gadget_yaml(self):
        yaml_file = os.path.join(
            self.unpackdir, 'gadget', 'meta', 'gadget.yaml')
        with open(yaml_file, 'r', encoding='utf-8') as fp:
            self.gadget = parse_yaml(fp)
        self._next.append(self.populate_rootfs_contents)

    def populate_rootfs_contents(self):
        src = os.path.join(self.unpackdir, 'image')
        dst = os.path.join(self.rootfs, 'system-data')
        shutil.move(os.path.join(src, 'var'), os.path.join(dst, 'var'))
        seed_dir = os.path.join(dst, 'var', 'lib', 'cloud', 'seed')
        cloud_dir = os.path.join(seed_dir, 'nocloud-net')
        os.makedirs(cloud_dir, exist_ok=True)
        metadata_file = os.path.join(cloud_dir, 'meta-data')
        with open(metadata_file, 'w', encoding='utf-8') as fp:
            print('instance-id: nocloud-static', file=fp)
        if self.cloud_init is not None:
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
            # XXX: Use file system label for the moment, until we get a proper
            # way to identify the boot partition.
            if part.filesystem_label == 'system-boot':
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
        self.boot_images = []
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        for partnum, part in enumerate(volume.structures):
            part_img = os.path.join(self.images, 'part{}.img'.format(partnum))
            self.boot_images.append(part_img)
            run('dd if=/dev/zero of={} count=0 bs={} seek=1'.format(
                part_img, part.size))
            if part.filesystem is FileSystemType.vfat:
                label_option = (
                    '-n {}'.format(part.filesystem_label)
                    # XXX I think this could be None or the empty string, but
                    # this needs verification.
                    if part.filesystem_label
                    else '')
                # XXX: hard-coding of sector size
                run('mkfs.vfat -s 1 -S 512 -F 32 {} {}'.format(
                    label_option, part_img))
            # XXX: Does not handle the case of partitions at the end of the
            # image.
            next_avail = part.offset + part.size
        # The image for the root partition.
        #
        # XXX: Hard-codes last 34 512-byte sectors for backup GPT,
        # empirically derived from sgdisk behavior.
        self.image_size = ceil((self.rootfs_size + next_avail) /
                               1024 + 17) * 1024
        self.root_img = os.path.join(self.images, 'root.img')
        # Create empty file with holes.
        with open(self.root_img,  'w'):
            pass
        os.truncate(self.root_img, self.rootfs_size)
        # We defer creating the root file system image because we have to
        # populate it at the same time.  See mkfs.ext4(8) for details.
        self._next.append(self.populate_filesystems)

    def populate_filesystems(self):
        volumes = self.gadget.volumes.values()
        assert len(volumes) == 1, 'For now, only one volume is allowed'
        volume = list(volumes)[0]
        for partnum, part in enumerate(volume.structures):
            part_img = self.boot_images[partnum]
            part_dir = os.path.join(self.workdir, 'part{}'.format(partnum))
            if part.filesystem is FileSystemType.none:
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
        # The root partition needs to be ext4, which may or may not be
        # populated at creation time, depending on the version of e2fsprogs.
        mkfs_ext4(self.root_img, self.rootfs)
        self._next.append(self.make_disk)

    def make_disk(self):
        self.disk_img = os.path.join(self.images, 'disk.img')
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
        if volume.schema == VolumeSchema.mbr:
            image = MBRImage(self.disk_img, self.image_size)
        else:
            image = Image(self.disk_img, self.image_size)

        structures = sorted(volume.structures, key=attrgetter('offset'))
        offset_writes = []
        part_offsets = {}
        for i, part in enumerate(structures):
            if part.name:
                part_offsets[part.name] = part.offset
            if part.offset_write:
                offset_writes.append((part.offset, part.offset_write))
            image.copy_blob(self.boot_images[i],
                            bs='1M', seek=part.offset // MiB(1),
                            count=ceil(part.size / MiB(1)),
                            conv='notrunc')
            if part.type == 'mbr':
                continue
            # sgdisk takes either a sector or a KiB/MiB argument; assume
            # that the offset and size are always multiples of 1MiB.
            partdef = '{}M:+{}M'.format(
                part.offset // MiB(1), part.size // MiB(1))
            part_args = {}
            part_args['new'] = partdef
            part_args['typecode'] = part.type
            # XXX: special-casing.
            if (volume.schema == VolumeSchema.mbr and
               part.filesystem_label == 'system-boot'):
                part_args['activate'] = True
            if part.name is not None:
                part_args['change_name'] = part.name
            image.partition(part_id, **part_args)
            part_id += 1
            next_offset = (part.offset + part.size) // MiB(1)
        # Create main snappy writable partition
        image.partition(part_id,
                        new='{}M:+{}K'.format(next_offset,
                                              self.rootfs_size // 1024),
                        typecode=('83',
                                  '0FC63DAF-8483-4772-8E79-3D69D8477DE4'))
        if volume.schema == VolumeSchema.gpt:
            image.partition(part_id, change_name='writable')
        image.copy_blob(self.root_img,
                        bs='1M', seek=next_offset,
                        count=ceil(self.rootfs_size / MiB(1)),
                        conv='notrunc')
        for value, dest in offset_writes:
            # decipher non-numeric offset_write values
            if isinstance(dest, tuple):
                dest = part_offsets[dest[0]] + dest[1]
            # XXX: Hard-coding of 512-byte sectors.
            image.write_value_at_offset(value // 512, dest)
        self._next.append(self.finish)

    def finish(self):
        # Move the completed disk image to destination location, since the
        # temporary scratch directory is about to get removed.
        shutil.move(self.disk_img, self.output, copy_function=sparse_copy)
        self._next.append(self.close)
