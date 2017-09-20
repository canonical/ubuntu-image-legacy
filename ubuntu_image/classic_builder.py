"""Flow for building a ubuntu classic disk image."""

import os
import git
import shutil
import logging

from math import ceil
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import gettempdir, TemporaryDirectory
from urllib.parse import urlparse
from ubuntu_image.helpers import (
     DoesNotFit, MiB, mkfs_ext4, check_root_privilege,
     live_build, run, save_cwd)
from ubuntu_image.hooks import HookManager
from ubuntu_image.image import Image
from ubuntu_image.state import State
from ubuntu_image.parser import (
    BootLoader, FileSystemType, StructureRole, VolumeSchema,
    parse as parse_yaml)


DEFAULT_fS_LABEL = 'writable'
SPACE = ' '
_logger = logging.getLogger('ubuntu-image')


class GitProgress(git.remote.RemoteProgress):
    """Show progress information during git clone."""

    def update(self, op_code, cur_count, max_count=None, message=''):
        print(self._cur_line)


class ClassicBuilder(State):
    def __init__(self, args):
        super().__init__()

        # The working directory will contain several bits as we stitch
        # everything together.  It will contain the final disk image file
        # (unless output is given).  It will contain an unpack/ directory
        # which is where `lb config && lb build` will put its contents.
        # It will contain a root/ directory which containing everything needed
        # for the final root file system.
        self.workdir = (
            self.resources.enter_context(TemporaryDirectory())
            if args.workdir is None
            else args.workdir)
        # The argument parser ensures that these are mutually exclusive.
        if args.output_dir is None:
            self.output_dir = (os.getcwd() if args.workdir is None
                               else args.workdir)
        else:
            self.output_dir = args.output_dir
        self.output = args.output
        # Information passed between states.
        self.rootfs = None
        self.rootfs_size = 0
        self.part_images = None
        self.entry = None
        self.gadget = None
        self.args = args
        self.unpackdir = None
        self.volumedir = None
        self.cloud_init = args.cloud_init
        self.gadget_tree = args.gadget_tree
        self.exitcode = 0
        self.done = False
        # Generic hook handling manager.
        self.hookdirs = args.hooks_directory
        self.hook_manager = HookManager(self.hookdirs)
        self._next.append(self.make_temporary_directories)

    def __getstate__(self):
        state = super().__getstate__()
        state.update(
            args=self.args,
            cloud_init=self.cloud_init,
            done=self.done,
            exitcode=self.exitcode,
            gadget=self.gadget,
            output=self.output,
            output_dir=self.output_dir,
            part_images=self.part_images,
            rootfs=self.rootfs,
            rootfs_size=self.rootfs_size,
            unpackdir=self.unpackdir,
            volumedir=self.volumedir,
            gadget_tree=self.gadget_tree,
            hookdirs=self.hookdirs,
            )
        return state

    def __setstate__(self, state):
        super().__setstate__(state)
        self.args = state['args']
        self.cloud_init = state['cloud_init']
        self.done = state['done']
        self.exitcode = state['exitcode']
        self.gadget = state['gadget']
        self.output = state['output']
        self.output_dir = state['output_dir']
        self.part_images = state['part_images']
        self.rootfs = state['rootfs']
        self.rootfs_size = state['rootfs_size']
        self.gadget_tree = state['gadget_tree']
        self.unpackdir = state['unpackdir']
        self.volumedir = state['volumedir']
        self.hookdirs = state['hookdirs']
        # Restore the hook manager along with the state.
        self.hook_manager = HookManager(self.hookdirs)

    def _log_exception(self, name):
        # Only log the exception if we're in debug mode.
        if self.args.debug:
            super()._log_exception(name)

    def make_temporary_directories(self):
        self.rootfs = os.path.join(self.workdir, 'root')
        self.unpackdir = os.path.join(self.workdir, 'unpack')
        self.volumedir = os.path.join(self.workdir, 'volumes')

        os.makedirs(self.rootfs)

        self._next.append(self.prepare_gadget_tree)

    def prepare_gadget_tree(self):
        try:
            gadget_dst = os.path.join(self.unpackdir, 'gadget_repo')
            if urlparse(self.gadget_tree).scheme != "":
                git.Repo.clone_from(self.gadget_tree, gadget_dst,
                                    progress=GitProgress())
            else:
                shutil.copytree(self.gadget_tree, gadget_dst)
            # generate unpacked gadget snap
            with save_cwd():
                os.chdir(gadget_dst)
                run(['snapcraft', 'prime'], env=os.environ)
            shutil.copytree(os.path.join(gadget_dst, 'prime'),
                            os.path.join(self.unpackdir, 'gadget'))

        except CalledProcessError:
            if self.args.debug:
                _logger.exception('Full debug traceback follows')
            self.exitcode = 1
            # Stop the state machine right here by not appending a next step.
        else:
            self._next.append(self.prepare_image)

    def prepare_image(self):
        # It's required to run ubuntu-image as root to build classic image.
        check_root_privilege()

        try:
            # Configure it with environment variables.
            env = {}
            if self.args.project is not None:
                env['PROJECT'] = self.args.project
            if self.args.suite is not None:
                env['SUITE'] = self.args.suite
            if self.args.arch is not None:
                env['ARCH'] = self.args.arch
            if self.args.subproject is not None:
                env['SUBPROJECT'] = self.args.subproject
            if self.args.subarch is not None:
                env['SUBARCH'] = self.args.subarch
            if self.args.with_proposed is not None:
                env['PROPOSED'] = self.args.with_proposed
            if self.args.extra_ppas is not None:
                env['EXTRA_PPAS'] = self.args.extra_ppas

            # Only genereate a single rootfs tree for classic image creation.
            env['GENERATE_ROOTFS_ONLY'] = 'true'
            live_build(self.unpackdir, env)
        except CalledProcessError:
            if self.args.debug:
                _logger.exception('Full debug traceback follows')
            self.exitcode = 1
            # Stop the state machine right here by not appending a next step.
        else:
            self._next.append(self.load_gadget_yaml)

    def load_gadget_yaml(self):
        # The gadget_tree has the same layout as the unpacked gadget snap.
        # And a piece of gadget.yaml is located at gadget_tree/meta folder.
        gadget_dir = os.path.join(self.unpackdir, 'gadget')
        yaml_file = os.path.join(gadget_dir, 'meta', 'gadget.yaml')
        # Preserve the gadget.yaml in the working dir.
        shutil.copy(yaml_file, self.workdir)
        with open(yaml_file, 'r', encoding='utf-8') as fp:
            self.gadget = parse_yaml(fp)
        # Make a working subdirectory for every volume we're going to create.
        # We'll put the volume contents inside these directories, and then use
        # the directories to create the disk images, one per volume.
        #
        # Store some additional metadata on the VolumeSpec object.  This is
        # convenient, if crufty, since we're poking data onto an object from
        # the outside.
        for name, volume in self.gadget.volumes.items():
            volume.basedir = os.path.join(self.volumedir, name)
            os.makedirs(volume.basedir)
        self._next.append(self.populate_rootfs_contents)

    def populate_rootfs_contents(self):
        src = os.path.join(self.unpackdir, 'chroot')
        dst = self.rootfs
        for subdir in os.listdir(src):
            shutil.move(os.path.join(src, subdir), os.path.join(dst, subdir))

        # Remove default grub bootloader settings as we ship bootloader bits
        # (binary blobs and grub.cfg) to a generated rootfs locally.
        grub_folder = os.path.join(dst, 'boot', 'grub')
        if os.path.exists(grub_folder):
            shutil.rmtree(grub_folder, ignore_errors=True)

        # Replace pre-defined LABEL in /etc/fstab with the one
        # we're using 'LABEL=writable' in grub.cfg.
        fstab_path = os.path.join(dst, 'etc', 'fstab')
        if os.path.exists(fstab_path):
            with open(fstab_path, 'r') as fstab:
                new_content = fstab.read().replace(
                    'LABEL=cloudimg-rootfs',
                    'LABEL={}'.format(DEFAULT_fS_LABEL))
            with open(fstab_path, 'w') as fstab:
                fstab.write(new_content)

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
        self._next.append(self.populate_rootfs_contents_hooks)

    def populate_rootfs_contents_hooks(self):
        # Separate populate step for firing the post-populate-rootfs hook.
        env = {'UBUNTU_IMAGE_HOOK_ROOTFS': self.rootfs}
        self.hook_manager.fire('post-populate-rootfs', env)
        self._next.append(self.calculate_rootfs_size)

    @staticmethod
    def _calculate_dirsize(path):
        # more accruate way to calculate size of dir which
        # contains hard or soft links
        total = 0
        proc = run('du -s -B1 {}'.format(path), check=False)
        if proc.returncode == 0:
            total = int(proc.stdout.strip().split()[0])
        # Fudge factor for incidentals.
        total *= 1.5
        return ceil(total)

    def calculate_rootfs_size(self):
        # Calculate the size of the root file system.
        #
        # On a 100MiB filesystem, ext4 takes a little over 7MiB for the
        # metadata.  Use 8MiB as a minimum padding here.
        self.rootfs_size = self._calculate_dirsize(self.rootfs) + MiB(8)
        self._next.append(self.pre_populate_bootfs_contents)

    def pre_populate_bootfs_contents(self):
        for name, volume in self.gadget.volumes.items():
            for partnum, part in enumerate(volume.structures):
                target_dir = os.path.join(
                    volume.basedir, 'part{}'.format(partnum))
                os.makedirs(target_dir, exist_ok=True)
        self._next.append(self.populate_bootfs_contents)

    def _populate_one_bootfs(self, name, volume):
        for partnum, part in enumerate(volume.structures):
            target_dir = os.path.join(volume.basedir, 'part{}'.format(partnum))
            if part.role is StructureRole.system_boot:
                volume.bootfs = target_dir
                if (volume.bootloader is not BootLoader.uboot and
                        volume.bootloader is not BootLoader.grub):
                        raise ValueError(
                            'Unsupported volume bootloader value: {}'.format(
                                volume.bootloader))
            if part.filesystem is FileSystemType.none:
                continue
            gadget_dir = os.path.join(self.unpackdir, 'gadget')
            for content in part.content:
                src = os.path.join(gadget_dir, content.source)
                dst = os.path.join(target_dir, content.target)
                if content.source.endswith('/'):
                    # This is a directory copy specification.  The target
                    # must also end in a slash.
                    #
                    # TODO: If this is a file instead of a directory, give
                    # a useful error message instead of a traceback.
                    #
                    # TODO: We should assert this constraint in the parser.
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
                    # TODO: If this is a directory instead of a file, give
                    # a useful error message instead of a traceback.
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(src, dst)

    def populate_bootfs_contents(self):
        for name, volume in self.gadget.volumes.items():
            self._populate_one_bootfs(name, volume)
        self._next.append(self.prepare_filesystems)

    def _prepare_one_volume(self, volume_index, name, volume):
        volume.part_images = []
        farthest_offset = 0
        for partnum, part in enumerate(volume.structures):
            part_img = os.path.join(
                volume.basedir, 'part{}.img'.format(partnum))
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
                        # TODO: I think this could be None or the empty string,
                        # but this needs verification.
                        if part.filesystem_label
                        else '')
                    # TODO: hard-coding of sector size.
                    run('mkfs.vfat -s 1 -S 512 -F 32 {} {}'.format(
                        label_option, part_img))
            volume.part_images.append(part_img)
            farthest_offset = max(farthest_offset, (part.offset + part.size))
        # Calculate or check the final image size.
        #
        # TODO: Hard-codes last 34 512-byte sectors for backup GPT,
        # empirically derived from sgdisk behavior.
        calculated = ceil(farthest_offset / 1024 + 17) * 1024
        if self.args.image_size is None:
            volume.image_size = calculated
        elif isinstance(self.args.image_size, int):
            # One size to rule them all.
            if self.args.image_size < calculated:
                _logger.warning(
                    'Ignoring image size smaller '
                    'than minimum required size: vol[{}]:{} '
                    '{} < {}'.format(volume_index, name,
                                     self.args.given_image_size, calculated))
                volume.image_size = calculated
            else:
                volume.image_size = self.args.image_size
        else:
            # The --image-size arguments are a dictionary, so look up the
            # one used for this volume.
            size_by_index = self.args.image_size.get(volume_index)
            size_by_name = self.args.image_size.get(name)
            if size_by_index is not None and size_by_name is not None:
                _logger.warning(
                    'Ignoring ambiguous volume size; index+name given')
                volume.image_size = calculated
            else:
                image_size = (size_by_index
                              if size_by_name is None
                              else size_by_name)
                if image_size < calculated:
                    _logger.warning(
                        'Ignoring image size smaller '
                        'than minimum required size: vol[{}]:{} '
                        '{} < {}'.format(volume_index, name,
                                         self.args.given_image_size,
                                         calculated))
                    volume.image_size = calculated
                else:
                    volume.image_size = image_size

    def prepare_filesystems(self):
        self.images = os.path.join(self.workdir, '.images')
        os.makedirs(self.images)
        for index, (name, volume) in enumerate(self.gadget.volumes.items()):
            self._prepare_one_volume(index, name, volume)
        self._next.append(self.populate_filesystems)

    def _populate_one_volume(self, name, volume):
        for partnum, part in enumerate(volume.structures):
            part_img = volume.part_images[partnum]
            part_dir = os.path.join(volume.basedir, 'part{}'.format(partnum))
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
                    # TODO: We need to check for overlapping images.
                    if content.offset is not None:
                        offset = content.offset
                    end = offset + file_size
                    if end > part.size:
                        if part.name is None:
                            if part.role is None:
                                whats_wrong = part.type
                            else:
                                whats_wrong = part.role.value
                        else:
                            whats_wrong = part.name
                        part_path = 'volumes:<{}>:structure:<{}>'.format(
                            name, whats_wrong)
                        self.exitcode = 1
                        raise DoesNotFit(partnum, part_path, end - part.size)
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

    def populate_filesystems(self):
        for name, volume in self.gadget.volumes.items():
            self._populate_one_volume(name, volume)
        self._next.append(self.make_disk)

    def _make_one_disk(self, imgfile, name, volume):
        part_id = 1
        # Create the image object for the selected volume schema
        image = Image(imgfile, volume.image_size, volume.schema)
        offset_writes = []
        part_offsets = {}
        # We first create all the partitions.
        for part in volume.structures:
            if part.name is not None:
                part_offsets[part.name] = part.offset
            if part.offset_write is not None:
                offset_writes.append((part.offset, part.offset_write))
            if part.role is StructureRole.mbr or part.type == 'bare':
                continue
            activate = False
            if (volume.schema is VolumeSchema.mbr and
                    part.role is StructureRole.system_boot):
                activate = True
            elif (volume.schema is VolumeSchema.gpt and
                    part.role is StructureRole.system_data and
                    part.name is None):
                part.name = DEFAULT_fS_LABEL
            image.partition(part.offset, part.size, part.name, activate)
        # Now since we're done, we need to do a second pass to copy the data
        # and set all the partition types.  This needs to be done like this as
        # libparted's commit() operation resets type GUIDs to defaults and
        # clobbers things like hybrid MBR partitions.
        part_id = 1
        for i, part in enumerate(volume.structures):
            image.copy_blob(volume.part_images[i],
                            bs=image.sector_size,
                            seek=part.offset // image.sector_size,
                            count=ceil(part.size / image.sector_size),
                            conv='notrunc')
            if part.role is StructureRole.mbr or part.type == 'bare':
                continue
            image.set_parition_type(part_id, part.type)
            part_id += 1
        for value, dest in offset_writes:
            # Decipher non-numeric offset_write values.
            if isinstance(dest, tuple):
                dest = part_offsets[dest[0]] + dest[1]
            image.write_value_at_offset(value // image.sector_size, dest)

    def make_disk(self):
        # Based on the -o/--output and -O/--output-dir options, and the volumes
        # in the gadget.yaml file, we can now calculate where the generated
        # disk images should go.  We'll write them directly to the final
        # destination so they don't have to be moved later.  Here is the
        # option precedence:
        #
        # * The location specified by -o/--output;
        # * <output_dir>/<volume_name>.img
        # * <work_dir>/disk.img
        #
        # If -o was given and there are multiple volumes, we ignore it and
        # act as if -O is in use.
        disk_img = None
        if self.output is not None:
            if len(self.gadget.volumes) > 1:
                _logger.warn('-o/--output ignored for multiple volumes')
            else:
                disk_img = self.output
        if not disk_img:
            os.makedirs(self.output_dir, exist_ok=True)
        # Walk through all partitions and write them to the disk image at the
        # lowest permissible offset.  We should not have any overlapping
        # partitions, the parser should have already rejected such as invalid.
        #
        # TODO: The parser should sort these partitions for us in disk order as
        # part of checking for overlaps, so we should not need to sort them
        # here.
        for name, volume in self.gadget.volumes.items():
            image_path = (
                disk_img if disk_img is not None
                else os.path.join(self.output_dir, '{}.img'.format(name)))
            self._make_one_disk(image_path, name, volume)
        self._next.append(self.generate_manifests)

    def generate_manifests(self):
        # After the images are built, we would also like to have some image
        # manifests exported so that one can easily check what packages have
        # been installed on the rootfs. We utilize dpkg-query tool to generate
        # the manifest file for classic image. Packages like casper which is
        # only useful in a live CD/DVD are removed.
        # The deprecated words can be found below:
        # https://help.ubuntu.com/community/MakeALiveCD/DVD/BootableFlashFromHarddiskInstall
        deprecated_words = ['ubiquity', 'casper']
        manifest_path = os.path.join(self.output_dir, 'filesystem.manifest')
        tmpfile_path = os.path.join(gettempdir(), 'filesystem.manifest')
        with open(tmpfile_path, 'w+') as tmpfile:
            query_cmd = ['sudo', 'chroot', self.rootfs, 'dpkg-query', '-W',
                         '--showformat=${Package} ${Version}\n']
            run(query_cmd, stdout=tmpfile, stderr=None, env=os.environ)
            tmpfile.seek(0, 0)
            with open(manifest_path, 'w') as manifest:
                for line in tmpfile:
                    if not any(word in line for word in deprecated_words):
                        manifest.write(line)

        self._next.append(self.finish)

    def finish(self):
        self.done = True
        self._next.append(self.close)
