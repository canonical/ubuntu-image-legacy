"""Test image building."""

import os

from tempfile import TemporaryDirectory
from ubuntu_image.image import GiB, Image, MiB
from unittest import TestCase


class TestImage(TestCase):
    def setUp(self):
        actual_tmpdir = TemporaryDirectory()
        self.tmpdir = actual_tmpdir.name
        self.addCleanup(actual_tmpdir.cleanup)
        self.img = os.path.join(self.tmpdir, 'img')
        assert not os.path.exists(self.img)

    def test_initialize(self):
        image = Image(self.img, GiB(1.25))
        self.assertTrue(os.path.exists(image.path))
        # GiB == 1024**3; 1.25GiB == 1342177280 bytes.
        self.assertEqual(os.stat(image.path).st_size, 1342177280)

    def test_initialize_smaller(self):
        image = Image(self.img, MiB(4.5))
        self.assertTrue(os.path.exists(image.path))
        # MiB == 1024**2; 4.5MiB == 4718592 bytes.
        self.assertEqual(os.stat(image.path).st_size, 4718592)
