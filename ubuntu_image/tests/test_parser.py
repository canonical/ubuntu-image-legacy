"""Tests of the gadget.yaml parser."""

from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.parser import (
    BootLoader, FileSystemType, VolumeSchema, parse)
from unittest import TestCase
from uuid import UUID


class TestParser(TestCase):
    def test_minimal(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
        self.assertIsNone(structure0.name)
        self.assertIsNone(structure0.offset)
        self.assertIsNone(structure0.offset_write)
        self.assertEqual(structure0.size, MiB(400))
        self.assertEqual(structure0.type, 'EF')
        self.assertIsNone(structure0.id)
        self.assertEqual(structure0.filesystem, FileSystemType.none)
        self.assertIsNone(structure0.filesystem_label)
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
          size: 400M
""")
        self.assertEqual(gadget_spec.device_tree_origin, 'kernel')
        self.assertEqual(gadget_spec.device_tree, 'dtree')
        self.assertEqual(gadget_spec.volumes.keys(), {'first-image'})

    def test_mbr(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
          size: 400M
""")

    def test_missing_schema(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.gpt)

    def test_grub(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: grub
    structure:
        - type: ef
          size: 400M
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
          size: 400M
""")

    def test_missing_bootloader(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: ef
          size: 400M
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
    bootloader: u-boot
    id: 00000000-0000-0000-0000-0000deadbeef
    structure:
        - type: ef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(
            volume0.id, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

    def test_2hex_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    id: 80
    structure:
        - type: ef
          size: 400M
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
          size: 400M
""")

    def test_bad_integer_volume_id(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 3g
    structure:
        - type: 801
          size: 400M
""")

    def test_no_structure(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
""")

    def test_volume_name(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - name: my volume
          type: ef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.name, 'my volume')
        self.assertEqual(partition0.filesystem_label, 'my volume')

    def test_duplicate_volume_name(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first:
    bootloader: u-boot
    structure:
        - name: one
          type: ef
          size: 400M
  second:
    structure:
        - name: two
          type: ef
          size: 400M
  first:
    structure:
        - name: three
          type: ef
          size: 400M
""")

    def test_volume_offset(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          offset: 2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset, 2112)

    def test_volume_offset_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
          size: 400M
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
          size: 400M
          offset-write: some_label+2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset_write, ('some_label', 2112))

    def test_volume_offset_write_relative_syntax_error(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          offset-write: some_label%2112
""")

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

    def test_no_size(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
""")

    def test_hybrid_volume_type(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(
            partition0.type,
            ('80', UUID(hex='00000000-0000-0000-0000-0000deadbeef')))

    def test_mbr_structure(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: mbr
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.type, 'mbr')
        self.assertEqual(partition0.filesystem, FileSystemType.none)

    def test_mbr_structure_conflicting_filesystem(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: mbr
          size: 400M
          filesystem: ext4
""")

    def test_bad_hybrid_volume_type_1(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,80
          size: 400M
""")

    def test_bad_hybrid_volume_type_2(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,\
00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")

    def test_bad_hybrid_volume_type_3(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,ab
          size: 400M
""")

    def test_bad_hybrid_volume_type_4(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,
          size: 400M
""")

    def test_bad_hybrid_volume_type_5(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ,00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")

    def test_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
          size: 400M
          id: ef
""")

    def test_volume_id_mbr(self):
        # Allowed, but ignored.
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          id: 00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(
            partition0.id, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

    def test_disallow_hybrid_volume_id(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          id: 80,00000000-0000-0000-0000-0000deadbeef
""")

    def test_volume_filesystem_vfat(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
          size: 400M
          filesystem: ext4
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.ext4)

    def test_volume_filesystem_none(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: none
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.none)

    def test_volume_filesystem_default_none(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.none)

    def test_volume_filesystem_bad(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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
          size: 400M
          filesystem: ext4
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

    def test_content_spec_b(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: none
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

    def test_content_spec_b_offset(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_offset_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_offset_write(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_offset_write_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_offset_write_label(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_size(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_content_spec_b_size_suffix(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
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

    def test_wrong_content_1(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: none
          content:
          - source: subdir/
            target: /
""")

    def test_wrong_content_2(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: ext4
          content:
          - image: foo.img
""")

    def test_content_conflict(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: ext4
          content:
          - source: subdir/
            target: /
          - image: foo.img
""")

    def test_content_a_multiple(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          filesystem: ext4
          content:
          - source: subdir1/
            target: 1/
          - source: subdir2/
            target: 2/
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(len(partition0.content), 2)
        content0 = partition0.content[0]
        self.assertEqual(content0.source, 'subdir1/')
        self.assertEqual(content0.target, '1/')
        content1 = partition0.content[1]
        self.assertEqual(content1.source, 'subdir2/')
        self.assertEqual(content1.target, '2/')

    def test_content_spec_b_multiple(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
          content:
          - image: foo1.img
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
        content1 = partition0.content[1]
        self.assertEqual(content1.image, 'foo2.img')
        self.assertEqual(content1.offset, 2112)
        self.assertIsNone(content1.offset_write)
        self.assertIsNone(content1.size)

    def test_multiple_volumes_no_bootloader(self):
        self.assertRaises(ValueError, parse, """\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: ef
          size: 400M
  second-image:
    schema: gpt
    structure:
        - type: a0
          size: 400M
  third-image:
    schema: gpt
    structure:
        - type: b1
          size: 400M
""")

    def test_multiple_volumes_with_bootloader(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: ef
          size: 100
  second-image:
    schema: gpt
    structure:
        - type: a0
          size: 200
  third-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: b1
          size: 300
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
