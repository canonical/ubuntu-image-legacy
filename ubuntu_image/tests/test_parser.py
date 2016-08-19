"""Tests of the gadget.yaml parser."""

from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.parser import (
    BootLoader, FileSystemType, PartitionType, VolumeSchema, parse)
from unittest import TestCase
from uuid import UUID


class TestParser(TestCase):
    def test_minimal(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
""")
        self.assertEqual(gadget_spec.device_tree_origin, 'gadget')
        self.assertIsNone(gadget_spec.device_tree)
        self.assertEqual(gadget_spec.volumes.keys(), {'first-image'})
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.gpt)
        self.assertEqual(volume0.bootloader, BootLoader.uboot)
        self.assertIsNone(volume0.id)
        self.assertEqual(len(volume0.structures), 1)
        structure0 = volume0.structures[0]
        self.assertIsNone(structure0.label)
        self.assertIsNone(structure0.offset)
        self.assertIsNone(structure0.offset_write)
        self.assertIsNone(structure0.size)
        self.assertEqual(structure0.type, 'EF')
        self.assertIsNone(structure0.id)
        self.assertIsNone(structure0.filesystem)
        self.assertEqual(len(structure0.content), 0)

    def test_device_tree(self):
        gadget_spec = parse("""\
device-tree-origin: kernel
device-tree: dtree
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
""")
        self.assertEqual(gadget_spec.device_tree_origin, 'kernel')
        self.assertEqual(gadget_spec.device_tree, 'dtree')

    def test_mbr(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.mbr)

    def test_bad_schema(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: bad
    bootloader: u-boot
    structure:
        - type: ef
""")

    def test_missing_schema(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
""")

    def test_grub(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: grub
    structure:
        - type: ef
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.bootloader, BootLoader.grub)

    def test_bad_bootloader(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boat
    structure:
        - type: ef
""")

    def test_no_nuthin(self):
        self.assertRaises(ValueError, parse, '')

    def test_no_volumes(self):
        self.assertRaises(ValueError, parse, """\
device-tree-origin: kernel
device-tree: dtree
""")

    def test_guid_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 00000000-0000-0000-0000-0000deadbeef
    structure:
        - type: ef
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(
            volume0.id, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

    def test_2hex_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 80
    structure:
        - type: ef
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.id, '80')

    def test_bad_volume_id(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 3g
    structure:
        - type: ef
""")

    def test_no_structure(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    schema: gpt
""")

    def test_volume_label(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - label: my volume
          type: ef
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.label, 'my volume')

    def test_volume_offset(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          offset: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset, 2112)

    def test_volume_offset_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          offset: 3M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset, MiB(3))

    def test_volume_offset_write(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          offset-write: 1G
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset_write, GiB(1))

    def test_volume_offset_write_relative(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          offset-write: some_label+2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset_write, ('some_label', 2112))

    def test_volume_size(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.size, 2112)

    def test_size_offset_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 3M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.size, MiB(3))

    def test_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          id: 00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(
            partition0.id, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

    def test_volume_id_not_guid(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          id: ef
""")

    def test_volume_filesystem_vfat(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          filesystem: vfat
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.vfat)

    def test_volume_filesystem_ext4(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          filesystem: ext4
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.ext4)

    def test_volume_filesystem_bad(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          filesystem: zfs
""")

    def test_content_spec_a(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - source: subdir/
            target: /
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.source, 'subdir/')
        self.assertEqual(content0.target, '/')
        self.assertFalse(content0.unpack)

    def test_content_spec_a_unpack(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - source: subdir/
            target: /
            unpack: true
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.source, 'subdir/')
        self.assertEqual(content0.target, '/')
        self.assertTrue(content0.unpack)

    def test_content_spec_b(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertIsNone(content0.offset_write)
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_offset(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            offset: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertEqual(content0.offset, 2112)
        self.assertIsNone(content0.offset_write)
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_offset_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            offset: 1M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertEqual(content0.offset, MiB(1))
        self.assertIsNone(content0.offset_write)
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_offset_write(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            offset-write: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertEqual(content0.offset_write, 2112)
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_offset_write_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            offset-write: 1M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertEqual(content0.offset_write, MiB(1))
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_offset_write_label(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            offset-write: label+2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertEqual(content0.offset_write, ('label', 2112))
        self.assertIsNone(content0.size)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_size(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            size: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertIsNone(content0.offset_write)
        self.assertEqual(content0.size, 2112)
        self.assertFalse(content0.unpack)

    def test_content_spec_b_size_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            size: 1M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertIsNone(content0.offset_write)
        self.assertEqual(content0.size, MiB(1))
        self.assertFalse(content0.unpack)

    def test_content_spec_b_unpack(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
            unpack: true
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 1)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo.img')
        self.assertIsNone(content0.offset)
        self.assertIsNone(content0.offset_write)
        self.assertIsNone(content0.size)
        self.assertTrue(content0.unpack)

    def test_content_conflict(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - source: subdir/
            target: /
          - image: foo.img
""")

    def test_content_conflict_swapped(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo.img
          - source: subdir/
            target: /
""")

    def test_content_a_multiple(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - source: subdir1/
            target: 1/
            unpack: true
          - source: subdir2/
            target: 2/
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 2)
        content0 = partition0.content[0]
        self.assertEqual(content0.source, 'subdir1/')
        self.assertEqual(content0.target, '1/')
        self.assertTrue(content0.unpack)
        content1 = partition0.content[1]
        self.assertEqual(content1.source, 'subdir2/')
        self.assertEqual(content1.target, '2/')
        self.assertFalse(content1.unpack)

    def test_content_spec_b_multiple(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          content:
          - image: foo1.img
            unpack: true
          - image: foo2.img
            offset: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 2)
        content0 = partition0.content[0]
        self.assertEqual(content0.image, 'foo1.img')
        self.assertIsNone(content0.offset)
        self.assertIsNone(content0.offset_write)
        self.assertIsNone(content0.size)
        self.assertTrue(content0.unpack)
        content1 = partition0.content[1]
        self.assertEqual(content1.image, 'foo2.img')
        self.assertEqual(content1.offset, 2112)
        self.assertIsNone(content1.offset_write)
        self.assertIsNone(content1.size)
        self.assertFalse(content1.unpack)

    # XXX Named partition types are still controversial.
    def test_partition_esp(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: esp
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.type, PartitionType.esp)

    def test_partition_type_raw(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: raw
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.type, PartitionType.raw)

    def test_partition_type_mbr(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: mbr
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.type, PartitionType.mbr)

    def test_multiple_volumes_no_bootloader(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: ef
  second-image:
    schema: gpt
    structure:
        - type: a0
  third-image:
    schema: gpt
    structure:
        - type: b1
""")

    def test_multiple_volumes_with_bootloader(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: ef
  second-image:
    schema: gpt
    structure:
        - type: a0
  third-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: b1
""")
        self.assertEqual(len(gadget_spec.volumes), 3)
        self.assertEqual({
            'first-image': None,
            'second-image': None,
            'third-image': BootLoader.uboot,
            },
            {key: gadget_spec.volumes[key].bootloader
             for key in gadget_spec.volumes}
            )
