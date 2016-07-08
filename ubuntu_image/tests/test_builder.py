"""Test image building."""

import os

from contextlib import ExitStack, suppress
from tempfile import TemporaryDirectory
from ubuntu_image.builder import BaseImageBuilder
from ubuntu_image.helpers import run
from unittest import TestCase


NL = '\n'


# For convenience.
def utf8open(path):
    return open(path, 'r', encoding='utf-8')


class TestBaseImageBuilder(TestCase):
    maxDiff = None

    def tearDown(self):
        with suppress(FileNotFoundError):
            os.remove('disk.img')

    def test_rootfs(self):
        with BaseImageBuilder() as state:
            state.run_thru('calculate_rootfs_size')
            self.assertEqual(
                set(os.listdir(state.rootfs)),
                {'foo', 'bar', 'boot', 'baz'})
            self.assertTrue(os.path.isdir(os.path.join(state.rootfs, 'baz')))
            self.assertTrue(os.path.isdir(os.path.join(state.rootfs, 'boot')))
            self.assertEqual(
                set(os.listdir(os.path.join(state.rootfs, 'baz'))),
                {'buz'})
            self.assertEqual(
                len(os.listdir(os.path.join(state.rootfs, 'boot'))),
                0)
            path = os.path.join(state.rootfs, 'foo')
            with utf8open(os.path.join(state.rootfs, path)) as fp:
                self.assertEqual(fp.read(), 'this is foo')
            with utf8open(os.path.join(state.rootfs, 'bar')) as fp:
                self.assertEqual(fp.read(), 'this is bar')
            with utf8open(os.path.join(state.rootfs, 'baz', 'buz')) as fp:
                self.assertEqual(fp.read(), 'some bazz buzz')
            self.assertEqual(state.rootfs_size, 54)

    def test_bootfs(self):
        with BaseImageBuilder() as state:
            state.run_thru('calculate_bootfs_size')
            self.assertEqual(
                set(os.listdir(state.bootfs)),
                {'boot', 'other'})
            self.assertTrue(os.path.isdir(os.path.join(state.bootfs, 'boot')))
            self.assertEqual(
                set(os.listdir(os.path.join(state.bootfs, 'boot'))),
                {'qux', 'qay'})
            with utf8open(os.path.join(state.bootfs, 'other')) as fp:
                self.assertEqual(fp.read(), 'other')
            with utf8open(os.path.join(state.bootfs, 'boot', 'qux')) as fp:
                self.assertEqual(fp.read(), 'boot qux')
            with utf8open(os.path.join(state.bootfs, 'boot', 'qay')) as fp:
                self.assertEqual(fp.read(), 'boot qay')
            self.assertEqual(state.bootfs_size, 31.5)

    def test_filesystems(self):
        with ExitStack() as resources:
            state = resources.enter_context(BaseImageBuilder())
            state.run_thru('populate_filesystems')
            boot_dir = resources.enter_context(TemporaryDirectory())
            # The boot file system is a VFAT file system.
            run('mcopy -s -i {} :: {}'.format(state.boot_img, boot_dir),
                env=dict(MTOOLS_SKIP_CHECK='1'))
            self.assertEqual(set(os.listdir(boot_dir)), {'boot', 'other'})
            self.assertEqual(
                set(os.listdir(os.path.join(boot_dir, 'boot'))),
                {'qay', 'qux'})
            with utf8open(os.path.join(boot_dir, 'other')) as fp:
                self.assertEqual(fp.read(), 'other')
            with utf8open(os.path.join(boot_dir, 'boot', 'qux')) as fp:
                self.assertEqual(fp.read(), 'boot qux')
            with utf8open(os.path.join(boot_dir, 'boot', 'qay')) as fp:
                self.assertEqual(fp.read(), 'boot qay')
            # The root file system is an ext4 file system.
            root_dir = resources.enter_context(TemporaryDirectory())
            run('debugfs -R "rdump / {}" {}'.format(root_dir, state.root_img),
                shell=True)
            self.assertEqual(
                set(os.listdir(root_dir)),
                {'foo', 'bar', 'baz', 'lost+found', 'boot'})
            boot_mount = os.path.join(root_dir, 'boot')
            self.assertTrue(os.path.isdir(boot_mount))
            self.assertEqual(os.listdir(boot_mount), [])
            with utf8open(os.path.join(root_dir, 'foo')) as fp:
                self.assertEqual(fp.read(), 'this is foo')
            with utf8open(os.path.join(root_dir, 'bar')) as fp:
                self.assertEqual(fp.read(), 'this is bar')
            with utf8open(os.path.join(root_dir, 'baz', 'buz')) as fp:
                self.assertEqual(fp.read(), 'some bazz buzz')

    def test_finish(self):
        with ExitStack() as resources:
            state = resources.enter_context(BaseImageBuilder())
            list(state)
            self.assertTrue(os.path.exists('disk.img'))
            self.assertFalse(os.path.exists(state.root_img))
            self.assertFalse(os.path.exists(state.boot_img))
        proc = run('sgdisk --print disk.img',
                   universal_newlines=True)
        # The disk identifier (GUID) is variable so remove that line.
        output = proc.stdout.splitlines()
        del output[2]
        self.assertMultiLineEqual(
                NL.join(output), """\
Disk disk.img: 8388608 sectors, 4.0 GiB
Logical sector size: 512 bytes
Partition table holds up to 128 entries
First usable sector is 34, last usable sector is 8388574
Partitions will be aligned on 2048-sector boundaries
Total free space is 790461 sectors (386.0 MiB)

Number  Start (sector)    End (sector)  Size       Code  Name
   2           10240          141311   64.0 MiB    EF00  system-boot
   3          147456         7614463   3.6 GiB     8300  writable""")
