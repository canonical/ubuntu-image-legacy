"""Test image building."""

import os

from contextlib import suppress
from parted import IOException
from struct import unpack
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.image import Image
from ubuntu_image.parser import VolumeSchema
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

    def test_initialize_partition_table_gpt(self):
        image = Image(self.img, MiB(10), VolumeSchema.gpt)
        self.assertTrue(os.path.exists(image.path))
        self.assertEqual(os.stat(image.path).st_size, 10485760)
        self.assertEqual(image.disk.type, 'gpt')
        self.assertEqual(image.schema, VolumeSchema.gpt)

    def test_initialize_partition_table_mbr(self):
        image = Image(self.img, MiB(10), VolumeSchema.mbr)
        self.assertTrue(os.path.exists(image.path))
        self.assertEqual(os.stat(image.path).st_size, 10485760)
        self.assertEqual(image.disk.type, 'msdos')
        self.assertEqual(image.schema, VolumeSchema.mbr)

    def test_initialize_partition_table_mbr_too_small(self):
        # Creating a super small image should fail as there's no place for
        # a partition table.
        self.assertRaises(IOException,
                          Image, self.img, 25, VolumeSchema.gpt)
        # ...but we can create an Image object without the partition table.
        image = Image(self.img, 25, None)
        self.assertTrue(os.path.exists(image.path))
        self.assertEqual(os.stat(image.path).st_size, 25)

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

    def test_gpt_image_partitions(self):
        image = Image(self.img, MiB(10), VolumeSchema.gpt)
        image.partition(offset=MiB(4), size=MiB(1), name='grub')
        self.assertEqual(len(image.disk.partitions), 1)
        image.partition(offset=MiB(5), size=MiB(4))
        self.assertEqual(len(image.disk.partitions), 2)
        image.set_parition_type(1, '21686148-6449-6E6F-744E-656564454649')
        image.set_parition_type(2, '0FC63DAF-8483-4772-8E79-3D69D8477DE4')
        # Use an external tool for checking the partition table to be sure
        # that it's indeed correct as suspected.
        disk_info = image.diagnostics()
        partitions = disk_info['partitiontable']
        # The device id is unpredictable.
        partitions.pop('id')
        # The partition uuids as well.
        [p.pop('uuid') for p in partitions['partitions']]
        self.maxDiff = None
        self.assertEqual(partitions, {
            'label': 'gpt',
            'device': self.img,
            'unit': 'sectors',
            'firstlba': 34,
            'lastlba': 20446,
            'partitions': [{
                'node': '{}1'.format(self.img),
                'start': 8192,
                'size': 2048,
                'type': '21686148-6449-6E6F-744E-656564454649',
                'name': 'grub',
                }, {
                'node': '{}2'.format(self.img),
                'start': 10240,
                'size': 8192,
                'type': '0FC63DAF-8483-4772-8E79-3D69D8477DE4',
                }],
            })

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

    def test_mbr_image_partitions(self):
        image = Image(self.img, MiB(2), VolumeSchema.mbr)
        # Create the first partition.
        image.partition(offset=image.sector(33),
                        size=image.sector(3000),
                        is_bootable=True)
        self.assertEqual(len(image.disk.partitions), 1)
        # Append the next one.
        image.partition(offset=image.sector(3033),
                        size=image.sector(1000))
        self.assertEqual(len(image.disk.partitions), 2)
        image.set_parition_type(1, '83')
        image.set_parition_type(2, 'dd')
        disk_info = image.diagnostics()
        partitions = disk_info['partitiontable']
        # The device id is unpredictable.
        partitions.pop('id')
        # XXX: In later versions of pyparted the partitiontable structure
        #  added a 'grain' entry that we're not really interested in.
        #  Remove it so we can have the tests working for all series.
        if 'grain' in partitions:
            partitions.pop('grain')
        self.assertEqual(partitions, {
            'label': 'dos',
            'device': self.img,
            'unit': 'sectors',
            'partitions': [{
                'node': '{}1'.format(self.img),
                'start': 33,
                'size': 3000,
                'type': '83',
                'bootable': True,
                }, {
                'node': '{}2'.format(self.img),
                'start': 3033,
                'size': 1000,
                'type': 'dd',
                }],
            })

    def test_set_partition_type_gpt(self):
        image = Image(self.img, MiB(6), VolumeSchema.gpt)
        image.partition(offset=MiB(1), size=MiB(1))
        self.assertEqual(len(image.disk.partitions), 1)
        image.set_parition_type(1, '21686148-6449-6E6F-744E-656564454649')
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         '21686148-6449-6E6F-744E-656564454649')
        image.set_parition_type(1, '00000000-0000-0000-0000-0000DEADBEEF')
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         '00000000-0000-0000-0000-0000DEADBEEF')

    def test_set_partition_type_mbr(self):
        image = Image(self.img, MiB(6), VolumeSchema.mbr)
        image.partition(offset=MiB(1), size=MiB(1))
        self.assertEqual(len(image.disk.partitions), 1)
        image.set_parition_type(1, '83')
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         '83')
        image.set_parition_type(1, 'da')
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         'da')

    def test_set_partition_type_hybrid(self):
        image = Image(self.img, MiB(6), VolumeSchema.mbr)
        image.partition(offset=MiB(1), size=MiB(1))
        self.assertEqual(len(image.disk.partitions), 1)
        image.set_parition_type(
            1, ('83', '00000000-0000-0000-0000-0000DEADBEEF'))
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         '83')
        image.set_parition_type(
            1, ('da', '00000000-0000-0000-0000-0000DEADBEEF'))
        disk_info = image.diagnostics()
        self.assertEqual(disk_info['partitiontable']['partitions'][0]['type'],
                         'da')

    def test_sector_conversion(self):
        # For empty non-partitioned images we default to a 512 sector size.
        image = Image(self.img, MiB(1))
        self.assertEqual(image.sector(10), 5120)
        # In case of using partitioning, be sure we use the sector size as
        # returned by pyparted.
        image = Image(self.img, MiB(5), VolumeSchema.mbr)
        self.assertEqual(image.sector(10), 10 * image.device.sectorSize)

    def test_device_schema_required(self):
        # With no schema, the device cannot be partitioned.
        image = Image(self.img, MiB(1))
        self.assertRaises(TypeError, image.partition, 256, 512)

    def test_small_partition_size_and_offset(self):
        # LP: #1630709 - structure parts with size and offset < 1MB.
        image = Image(self.img, MiB(2), VolumeSchema.mbr)
        image.partition(offset=256, size=512)
        disk_info = image.diagnostics()
        # Even though the offset and size are set at 256 bytes and 512 bytes
        # respectively, the minimum granularity is one sector (i.e. 512
        # bytes).  The start and size returned by diagnostics() are in sector
        # units.
        self.assertEqual(
            disk_info['partitiontable']['partitions'][0]['start'],
            1)
        self.assertEqual(
            disk_info['partitiontable']['partitions'][0]['size'],
            1)
