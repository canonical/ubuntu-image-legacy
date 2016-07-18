"""Test image building."""

import os

from contextlib import ExitStack, suppress
from subprocess import CompletedProcess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.builder import BaseImageBuilder, ModelAssertionBuilder
from ubuntu_image.helpers import run
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
TRAVIS = 'TRAVIS_PULL_REQUEST' in os.environ


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

    def test_keep_temporary_directories(self):
        with ExitStack() as resources:
            tmpdir_object = TemporaryDirectory()
            tmpdir = resources.enter_context(tmpdir_object)
            resources.enter_context(patch(
                'ubuntu_image.builder.TemporaryDirectory',
                return_value=tmpdir_object))
            # Enter a new context just to manage the builder's resources.
            with BaseImageBuilder(keep=True) as state:
                state.run_thru('make_temporary_directories')
                self.assertEqual(state.rootfs, os.path.join(tmpdir, 'root'))
                self.assertEqual(state.bootfs, os.path.join(tmpdir, 'boot'))
                self.assertTrue(os.path.exists(state.bootfs))
                self.assertTrue(os.path.exists(state.rootfs))
            # After we exit the builder's context, the temporary directories
            # will still exist, because we passed in keep=True.
            self.assertTrue(os.path.exists(state.bootfs))
            self.assertTrue(os.path.exists(state.rootfs))

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

    @skipIf(TRAVIS, 'cannot mount in a docker container')
    def test_filesystems_xenial(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap weld`.  Mimic what happens on Ubuntu 16.04 where
        # mkfs.ext4 does not support the -d option.
        #
        # This isn't perfectly wonderful because we really should run the
        # tests in Travis twice, once on Xenial and once on >Xenial, skipping
        # the one that isn't appropriate rather than assuming >Xenial and
        # mocking the Xenial case.
        def no_dash_d(command, *, check=True, **args):
            if command.startswith('mkfs.ext4') and '-d' in command.split():
                return CompletedProcess([], 1, '', '')
            return run(command, check=check, **args)
        with ExitStack() as resources:
            resources.enter_context(patch(
                'ubuntu_image.builder.run', no_dash_d))
            state = resources.enter_context(BaseImageBuilder())
            state.run_thru('populate_filesystems')
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
        proc = run('sgdisk --print disk.img')
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


class TestModelAssertionBuilder(TestCase):
    # XXX These tests relies on external resources, namely that the gadget and
    # kernel snaps in this model assertion can actually be downloaded from the
    # real store.  That's a test isolation bug and a potential source of test
    # brittleness.  We should fix this.
    #
    # XXX These tests also requires root, because `snap weld` currently
    # requires it.  mvo says this will be fixed.

    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        fp = self._resources.enter_context(NamedTemporaryFile(
            mode='w', encoding='utf-8'))
        # There is trailing whitespace in this text and it is significant!
        # We do a bogus interpolation to appease pyflakes.
        print("""\
type: model
series: 16
authority-id: my-brand
brand-id: my-brand
model: canonical-pc-amd64
class: general
allowed-modes: classic, developer
required-snaps: {}
architecture: amd64
store: canonical
gadget: canonical-pc
kernel: canonical-pc-linux
core: ubuntu-core
timestamp: 2016-01-02T10:00:00-05:00
body-length: 0

openpgpg 2cln""".format(''), file=fp)
        fp.flush()
        self.model_assertion = fp.name

    @skipIf(TRAVIS, 'cannot mount in a docker container')
    def test_fs_contents(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap weld`.
        args = SimpleNamespace(
            channel='edge',
            keep=False,
            model_assertion=self.model_assertion,
            )
        state = self._resources.enter_context(ModelAssertionBuilder(args))
        state.run_thru('calculate_bootfs_size')
        # How does the root and boot file systems look?
        files = [
            '{boot}/grub/grub.cfg',
            '{boot}/grub/grubenv',
            '{root}/snap/',
            '{root}/var/lib/snapd/seed/snaps/canonical-pc_6.snap',
            '{root}/var/lib/snapd/seed/snaps'
                '/canonical-pc-linux_30.snap.sideinfo',   # noqa
            '{root}/var/lib/snapd/seed/snaps/canonical-pc_6.snap.sideinfo',
            '{root}/var/lib/snapd/seed/snaps/ubuntu-core_138.snap',
            '{root}/var/lib/snapd/seed/snaps/canonical-pc-linux_30.snap',
            '{root}/var/lib/snapd/seed/snaps/ubuntu-core_138.snap.sideinfo',
            '{root}/var/lib/snapd/snaps/canonical-pc-linux_30.snap',
            '{root}/var/lib/snapd/snaps/ubuntu-core_138.snap',
            ]
        for path in files:
            self.assertTrue(os.path.exists(path.format(
                root=state.rootfs,
                boot=state.bootfs,
                )))
