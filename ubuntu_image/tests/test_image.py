"""Test image building."""

import os

from contextlib import suppress
from json import loads as load_json
from struct import unpack
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import GiB, MiB, run
from ubuntu_image.image import Diagnostics, Image, MBRImage
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
        # TODO: this has to be represented in the gadget.yaml
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

    def test_partition(self):
        # Create BIOS boot partition.
        #
        # The partition is 1MiB in size, as recommended by various
        # partitioning guides.  The actual required size is much, much
        # smaller.
        image = Image(self.img, MiB(10))
        image.partition(1, new='4MiB:+1MiB')
        image.partition(1, typecode='21686148-6449-6E6F-744E-656564454649')
        image.partition(1, change_name='grub')
        mbr = image.diagnostics(Diagnostics.mbr)
        # We should see that the disk size is 10MiB.
        self.assertRegex(mbr, '10.0 MiB')
        gpt = image.diagnostics(Diagnostics.gpt)
        # We should see that there is 1 partition named grub.
        self.assertRegex(gpt, 'grub')

    def test_write_value_at_offset(self):
        image = Image(self.img, MiB(2))
        image.write_value_at_offset(801, 130031)
        # Now open the path independently, seek to the given offset, and read
        # 4 bytes, then interpret it as a little-endian 32-bit integer.
        with open(image.path, 'rb') as fp:
            fp.seek(130031)
            # Unpack always returns a tuple, but there's only one item there.
            value, *ignore = unpack('<I', fp.read(4))
        self.assertEqual(value, 801)

    def test_write_value_at_offset_past_end(self):
        image = Image(self.img, 10000)
        self.assertRaises(ValueError, image.write_value_at_offset, 801, 130031)
        # And the file's size hasn't changed.
        self.assertEqual(os.path.getsize(self.img), 10000)

    def test_write_value_at_offsets_near_end(self):
        image = Image(self.img, 10000)
        # Attempt to write a bunch of values near the end of the file.  Since
        # the value will always be a 32-bit value, any positions farther out
        # than 4 bytes before the end will fail.
        results = set()
        for pos in range(9995, 10002):
            with suppress(ValueError):
                image.write_value_at_offset(801, pos)
                self.assertEqual(os.path.getsize(self.img), 10000)
                results.add(pos)
        self.assertEqual(results, {9995, 9996})

    def test_mbr_image_partition(self):
        image = MBRImage(self.img, MiB(2))
        self.assertFalse(image.initialized)
        image.partition(1, new='33:3000', activate=True, typecode='83')
        self.assertTrue(image.initialized)
        proc = run('sfdisk --list {}'.format(self.img))
        info = proc.stdout.splitlines()[-1].split()
        device = self.img + '1'
        self.assertEqual(
            info, [device, '*', '33', '3032', '3000', '1.5M', '83', 'Linux'])

    def test_mbr_image_partition_append(self):
        image = MBRImage(self.img, MiB(2))
        self.assertFalse(image.initialized)
        # Create the first partition.
        image.partition(1, new='33:3000', activate=True, typecode='83')
        self.assertTrue(image.initialized)
        # Append the next one.
        image.partition(2, new='3032:1000', typecode='dd')
        proc = run('sfdisk --list {}'.format(self.img))
        info = proc.stdout.splitlines()[-1].split()
        device = self.img + '2'
        self.assertEqual(
            # No boot-flag star.
            info, [device, '3033', '4032', '1000', '500K', 'dd', 'unknown'])

    def test_mbr_image_partition_tuple_typecode(self):
        # See the spec; type codes can by hybrid mbr/gpt style.
        image = MBRImage(self.img, MiB(2))
        self.assertFalse(image.initialized)
        image.partition(
            1, new='33:3000', activate=True,
            typecode=('83', '00000000-0000-0000-0000-0000deadbeef'))
        self.assertTrue(image.initialized)
        proc = run('sfdisk --list {}'.format(self.img))
        info = proc.stdout.splitlines()[-1].split()
        device = self.img + '1'
        self.assertEqual(
            info, [device, '*', '33', '3032', '3000', '1.5M', '83', 'Linux'])

    def test_mbr_image_partition_bad_keyword(self):
        image = MBRImage(self.img, MiB(2))
        self.assertRaises(
            ValueError,
            image.partition, 1, new='0:100', cracktivate=1, typecode='fe')

    def test_mbr_image_partition_named(self):
        # sfdisk does not support the --change-name argument, so it's
        # currently just ignored.
        image = MBRImage(self.img, MiB(2))
        self.assertFalse(image.initialized)
        image.partition(1, new='33:3000', activate=True, typecode='83',
                        change_name='first')
        self.assertTrue(image.initialized)
        proc = run('sfdisk --list {} --json'.format(self.img))
        disk_info = load_json(proc.stdout)
        partitions = disk_info['partitiontable']
        # See?  No name.  However, the device id is unpredictable.
        partitions.pop('id')
        self.assertEqual(partitions, {
            'device': self.img,
            'label': 'dos',
            'partitions': [{'bootable': True,
                            'node': '{}1'.format(self.img),
                            'size': 3000,
                            'start': 33,
                            'type': '83'}],
            'unit': 'sectors'})
