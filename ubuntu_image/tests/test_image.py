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

    def test_copy_blob_install_grub_to_mbr(self):
        # Install GRUB to MBR
        # TODO: this has to be represented in the image.yaml
        # NOTE: the boot.img has to be a part of the gadget snap itself
        # FIXME: embed a pointer to 2nd stage in bios-boot partition
        #
        # dd if=blobs/img.mbr of=img bs=446 count=1 conv=notrunc
        #
        # Start by creating a blob of the requested size.
        blob_file = os.path.join(self.tmpdir, 'mbr.blob')
        with open(blob_file, 'wb') as fp:
            fp.write(b'happyhappyjoyjoy' * 27)
            fp.write(b'happyhappyjoyj')
        self.assertEqual(os.stat(blob_file).st_size, 446)
        image = Image(self.img, MiB(1))
        image.copy_blob(blob_file, bs=446, count=1, conv='notrunc')
        # At the top of the image file, there should be 27 Stimpy
        # Exclamations, followed by a happyhappyjoyj.
        with open(image.path, 'rb') as fp:
            complete_stimpys = fp.read(432)
            partial_stimpys = fp.read(14)
            # Spot check.
            zeros = fp.read(108)
        self.assertEqual(complete_stimpys, b'happyhappyjoyjoy' * 27)
        self.assertEqual(partial_stimpys, b'happyhappyjoyj')
        # Stevens $4.13 - the extended file should read as zeros.
        self.assertEqual(zeros, b'\0' * 108)

    def test_copy_blob_with_seek(self):
        # dd if=blobs/img.bios-boot of=img bs=1MiB seek=4 count=1 conv=notrunc
        blob_file = os.path.join(self.tmpdir, 'img.bios-boot')
        with open(blob_file, 'wb') as fp:
            fp.write(b'x' * 100)
        image = Image(self.img, MiB(2))
        image.copy_blob(blob_file, bs=773, seek=4, count=1, conv='notrunc')
        # The seek=4 skipped 4 blocks of 773 bytes.
        with open(image.path, 'rb') as fp:
            self.assertEqual(fp.read(3092), b'\0' * 3092)
            self.assertEqual(fp.read(100), b'x' * 100)
            self.assertEqual(fp.read(25), b'\0' * 25)
