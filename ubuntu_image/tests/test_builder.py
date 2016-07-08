"""Test image building."""

import os

from ubuntu_image.builder import BaseImageBuilder
from unittest import TestCase


class TestBaseImageBuilder(TestCase):
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
            with open(path, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'this is foo')
            path = os.path.join(state.rootfs, 'bar')
            with open(path, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'this is bar')
            path = os.path.join(state.rootfs, 'baz', 'buz')
            with open(path, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'some bazz buzz')
            self.assertEqual(state.rootfs_size, 54)

    def test_bootfs(self):
        with BaseImageBuilder() as state:
            state.run_thru('calculate_bootfs_size')
            self.assertEqual(
                set(os.listdir(state.bootfs)),
                {'boot'})
            self.assertTrue(os.path.isdir(os.path.join(state.bootfs, 'boot')))
            self.assertEqual(
                set(os.listdir(os.path.join(state.bootfs, 'boot'))),
                {'qux', 'qay'})
            path = os.path.join(state.bootfs, 'boot', 'qux')
            with open(path, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'boot qux')
            path = os.path.join(state.bootfs, 'boot', 'qay')
            with open(path, 'r', encoding='utf-8') as fp:
                self.assertEqual(fp.read(), 'boot qay')
            self.assertEqual(state.bootfs_size, 24)

    def test_filesystems(self):
        with BaseImageBuilder() as state:
            state.run_thru('populate_filesystems')
