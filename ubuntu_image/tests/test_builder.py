"""Test image building."""

import os
import re

from contextlib import ExitStack
from itertools import product
from pkg_resources import resource_filename
from tempfile import NamedTemporaryFile, TemporaryDirectory
from types import SimpleNamespace
from ubuntu_image.testing.helpers import IN_TRAVIS, XXXModelAssertionBuilder
from unittest import TestCase, skipIf
from unittest.mock import patch


NL = '\n'
COMMASPACE = ', '


# For convenience.
def utf8open(path):
    return open(path, 'r', encoding='utf-8')


class TestModelAssertionBuilder(TestCase):
    # XXX These tests relies on external resources, namely that the gadget and
    # kernel snaps in this model assertion can actually be downloaded from the
    # real store.  That's a test isolation bug and a potential source of test
    # brittleness.  We should fix this.
    #
    # XXX These tests also requires root, because `snap prepare-image`
    # currently requires it.  mvo says this will be fixed.

    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        self.model_assertion = resource_filename(
            'ubuntu_image.tests.data', 'model.assertion')

    @skipIf(IN_TRAVIS, 'cannot mount in a docker container')
    def test_fs_contents(self):
        # Run the action model assertion builder through the steps needed to
        # at least call `snap prepare-image`.
        output = self._resources.enter_context(NamedTemporaryFile())
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            output=output,
            model_assertion=self.model_assertion,
            )
        state = self._resources.enter_context(XXXModelAssertionBuilder(args))
        state.run_thru('calculate_bootfs_size')
        # How does the root and boot file systems look?
        files = [
            '{boot}/EFI/boot/bootx64.efi',
            '{boot}/EFI/boot/grub.cfg',
            '{boot}/EFI/boot/grubx64.efi',
            '{boot}/EFI/ubuntu/grub.cfg',
            '{boot}/EFI/ubuntu/grubenv',
            '{root}/system-data/boot/',
            '{root}/system-data/snap/',
            ]
        for filename in files:
            path = filename.format(
                root=state.rootfs,
                boot=state.bootfs,
                )
            self.assertTrue(os.path.exists(path), path)
        # 2016-08-01 barry@ubuntu.com: Since these tests currently use real
        # data, the snap version numbers may change.  Until we use test data
        # (sideloaded) do regexp matches against specific snap file names.
        seeds_path = os.path.join(
            state.rootfs, 'system-data',
            'var', 'lib', 'snapd', 'seed', 'snaps')
        snaps = set(os.listdir(seeds_path))
        seed_patterns = [
            '^canonical-pc-linux_[0-9]+.snap$',
            '^canonical-pc_[0-9]+.snap$',
            '^ubuntu-core_[0-9]+.snap$',
            ]
        # Make sure every file matches a pattern and every pattern matches a
        # file.
        patterns_matched = set()
        files_matched = set()
        matches = []
        for pattern, snap in product(seed_patterns, snaps):
            if pattern in patterns_matched or snap in files_matched:
                continue
            if re.match(pattern, snap):
                matches.append((pattern, snap))
                patterns_matched.add(pattern)
                files_matched.add(snap)
        patterns_unmatched = set(seed_patterns) - patterns_matched
        files_unmatched = snaps - files_matched
        self.assertEqual(
            len(patterns_unmatched), 0,
            'Unmatched patterns: {}'.format(COMMASPACE.join(
                patterns_unmatched)))
        self.assertEqual(
            len(files_unmatched), 0,
            'Unmatched files: {}'.format(COMMASPACE.join(files_unmatched)))

    def test_make_disk_no_dos_partitions_yet(self):
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            state.gadget = SimpleNamespace(scheme='MBR')
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.make_disk)
            # Be quiet.
            resources.enter_context(patch('ubuntu_image.state.log.exception'))
            cm = resources.enter_context(self.assertRaises(ValueError))
            list(state)
            self.assertEqual(str(cm.exception),
                             'DOS partition tables not yet supported')

    def test_no_partitions(self):
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            os.makedirs(os.path.join(state.unpackdir, 'image', 'boot', 'grub'))
            state.bootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(scheme='GPT')
            state.gadget.partitions = []
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            next(state)
            # The only thing in the bootfs should be the EFI subdirectory.
            self.assertEqual(os.listdir(state.bootfs), ['EFI'])

    def test_no_esp_parts(self):
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            os.makedirs(os.path.join(state.unpackdir, 'image', 'boot', 'grub'))
            state.bootfs = resources.enter_context(TemporaryDirectory())
            state.gadget = SimpleNamespace(scheme='GPT')
            state.gadget.partitions = [SimpleNamespace(role='raw')]
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_bootfs_contents)
            next(state)
            # The only thing in the bootfs should be the EFI subdirectory.
            self.assertEqual(os.listdir(state.bootfs), ['EFI'])

    def test_snap_gets_called(self):
        # This exists for coverage under Travis-CI which normally won't run
        # the snap command because the mount that snap does can't be performed
        # in a docker container.
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            mock = resources.enter_context(patch('ubuntu_image.builder.snap'))
            state.run_thru('prepare_image')
            all_call_args = mock.call_args_list
            self.assertEqual(len(all_call_args), 1)
            # The second argument is a temporary directory, so just check the
            # first and last arguments.
            first_call = all_call_args[0][0]
            self.assertEqual(first_call[0], self.model_assertion)
            self.assertEqual(first_call[2], 'edge')

    def test_populate_rootfs_contents(self):
        # This exists for coverage under Travis-CI which normally won't run
        # the snap command because the mount that snap does can't be performed
        # in a docker container.
        args = SimpleNamespace(
            channel='edge',
            workdir=None,
            model_assertion=self.model_assertion,
            output=None,
            )
        with ExitStack() as resources:
            state = resources.enter_context(XXXModelAssertionBuilder(args))
            # Fake some state expected by the method under test.
            state.unpackdir = resources.enter_context(TemporaryDirectory())
            image_dir = os.path.join(state.unpackdir, 'image')
            os.makedirs(image_dir)
            with open(os.path.join(image_dir, 'snap'), 'w'):
                pass
            with open(os.path.join(image_dir, 'var'), 'w'):
                pass
            state.rootfs = resources.enter_context(TemporaryDirectory())
            system_data = os.path.join(state.rootfs, 'system-data')
            os.makedirs(system_data)
            # Jump right to the state method we're trying to test.
            state._next.pop()
            state._next.append(state.populate_rootfs_contents)
            next(state)
            self.assertEqual(
                set(os.listdir(system_data)), {'boot', 'snap', 'var'})
