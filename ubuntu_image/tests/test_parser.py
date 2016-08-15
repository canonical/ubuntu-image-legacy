"""gadget.yaml parsing."""

from io import StringIO
from ubuntu_image.helpers import MiB
from ubuntu_image.parser import (
    BootLoader, FileSystemType, PartitionScheme, PartitionType, parse)
from unittest import TestCase


class TestParser(TestCase):
    def test_minimal(self):
        gadget_spec = parse("""\
bootloader: u-boot
volumes:
 - partitions:
   - type: ESP
""")
        self.assertEqual(gadget_spec.bootloader, BootLoader.uboot)
        self.assertEqual(len(gadget_spec.volumes), 1)
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.GPT)
        self.assertEqual(len(volume0.partitions), 1)
        partition0 = volume0.partitions[0]
        self.assertIsNone(partition0.name)
        self.assertEqual(partition0.type, PartitionType.ESP)
        self.assertEqual(partition0.fs_type, FileSystemType.vfat)
        self.assertIsNone(partition0.offset)
        self.assertIsNone(partition0.size)
        self.assertIsNone(partition0.content)

    def test_parse(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: ESP
   size: 50M
   files:
    - source: grubx64.efi.signed
      dest: EFI/boot/grubx64.efi
    - source: shim.efi.signed
      dest: EFI/boot/bootx64.efi
    - source: grub.cfg
      dest: EFI/boot/grub.cfg
""")
        image_spec = parse(stream)
        self.assertEqual(image_spec.scheme, 'MBR')
        self.assertEqual(len(image_spec.partitions), 1)
        partition = image_spec.partitions[0]
        self.assertIsNone(partition.name)
        self.assertEqual(partition.role, 'ESP')
        self.assertIsNone(partition.guid)
        self.assertEqual(partition.type_id, 'EF')
        self.assertIsNone(partition.offset)
        self.assertEqual(partition.size, MiB(50))
        self.assertEqual(partition.fs_type, 'vfat')
        self.assertEqual(partition.files, [
            ('grubx64.efi.signed', 'EFI/boot/grubx64.efi'),
            ('shim.efi.signed', 'EFI/boot/bootx64.efi'),
            ('grub.cfg', 'EFI/boot/grub.cfg'),
            ])

    def test_bad_scheme(self):
        self.assertRaises(
            ValueError, parse, StringIO('partition-scheme: XXX\n'))

    def test_raw_mbr(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: raw
""")
        image_spec = parse(stream)
        self.assertEqual(image_spec.partitions[0].type_id, 'DA')

    def test_raw_gpt(self):
        stream = StringIO("""\
partition-scheme: GPT
partitions:
 - role: raw
""")
        image_spec = parse(stream)
        self.assertEqual(
            image_spec.partitions[0].type_id,
            '21686148-6449-6E6F-744E-656564454649')

    def test_custom_with_fs_type(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: custom
   fs-type: ext4
""")
        image_spec = parse(stream)
        self.assertEqual(image_spec.partitions[0].fs_type, 'ext4')
        self.assertEqual(image_spec.partitions[0].type_id, '83')

    def test_custom_without_fs_type(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: custom
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'fs-type is required')

    def test_custom_mbr_type_id(self):
        stream = StringIO("""\
partition-scheme: GPT
partitions:
 - role: custom
   fs-type: ext4
""")
        image_spec = parse(stream)
        self.assertEqual(image_spec.partitions[0].type_id,
                         '0FC63DAF-8483-4772-8E79-3D69D8477DE4')

    def test_raw_destination(self):
        # With fs-type 'raw', no file destination is allowed.
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: raw
   files:
   - source: a/b/c
     dest: e/f/g
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'No dest allowed')

    def test_raw_offsets(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: raw
   files:
   - source: a/b/c
     offset: 1M
   - source: d/e/f
   - source: g/h/i
     offset: 1024
""")
        image_spec = parse(stream)
        self.assertEqual(len(image_spec.partitions), 1)
        self.assertEqual(image_spec.partitions[0].files, [
            # This are file sources and offsets.
            ('a/b/c', MiB(1)),
            ('d/e/f', 0),
            ('g/h/i', 1024),
            ])

    def test_offsets_not_allowed_for_fs_type(self):
        # With an explicit fs-type, only source/dest are allowed.
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: custom
   fs-type: ext4
   files:
   - source: a/b/c
     offset: 1M
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'offset not allowed')

    def test_missing_dest_for_fs_type(self):
        # With an explicit fs-type, only source/dest are required.
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: custom
   fs-type: ext4
   files:
   - source: a/b/c
   - source: d/e/f
     dest: g/h/i
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'dest required for source: a/b/c')

    def test_raw_too_many_default_offsets(self):
        # With fs-type 'raw' only one file is allowed to have a default offset.
        stream = StringIO("""\
partition-scheme: MBR
partitions:
 - role: raw
   files:
   - source: a/b/c
   - source: d/e/f
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'Only one default offset allowed')

    def test_bad_partition_role(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: with-the-punches
""")
        self.assertRaises(ValueError, parse, stream)

    def test_explicit_fs_type_for_esp(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
    fs-type: ext4
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'Invalid explicit fs-type: ext4')

    def test_explicit_guid_for_esp(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
    guid: 00000000-0000-0000-0000-000000abcdef
""")
        self.assertRaises(ValueError, parse, stream)

    def test_explicit_type_for_esp(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
    type: XX
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'Invalid explicit type id: XX')

    def test_explicit_fs_type_for_raw(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: raw
    fs-type: ext4
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(
            str(cm.exception),
            'No fs-type allowed for raw partitions: ext4')

    def test_invalid_fs_type_for_custom(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: custom
    fs-type: zfs
""")
        self.assertRaises(ValueError, parse, stream)

    def test_partition_offset(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: custom
    fs-type: ext4
    offset: 108
""")
        image_spec = parse(stream)
        self.assertEqual(len(image_spec.partitions), 1)
        self.assertEqual(image_spec.partitions[0].offset, 108)

    def test_partition_offset_units(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: custom
    fs-type: ext4
    offset: 1M
""")
        image_spec = parse(stream)
        self.assertEqual(len(image_spec.partitions), 1)
        self.assertEqual(image_spec.partitions[0].offset, MiB(1))

    def test_default_ESP_size(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
""")
        image_spec = parse(stream)
        partition = image_spec.partitions[0]
        self.assertEqual(partition.size, MiB(64))

    def test_explicit_ESP_size(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
    size: 99M
""")
        image_spec = parse(stream)
        partition = image_spec.partitions[0]
        self.assertEqual(partition.size, MiB(99))

    def test_overlapping_partitions(self):
        stream = StringIO("""\
partition-scheme: MBR
partitions:
  - role: ESP
    size: 99M
    offset: 5M
  - role: raw
    offset: 20M
""")
        with self.assertRaises(ValueError) as cm:
            parse(stream)
        self.assertEqual(str(cm.exception), 'overlapping partitions defined')
