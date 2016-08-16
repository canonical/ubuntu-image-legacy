"""Tests of the gadget.yaml parser."""

from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.parser import (
    BootLoader, FileSystemType, PartitionScheme, PartitionType, parse)
from unittest import TestCase
from uuid import UUID


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

    def test_grub(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
""")
        self.assertEqual(gadget_spec.bootloader, BootLoader.grub)

    def test_explicit_gpt(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partition-scheme: GPT
   partitions:
   - type: ESP
""")
        self.assertEqual(len(gadget_spec.volumes), 1)
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.GPT)

    def test_bad_bootloader(self):
        self.assertRaises(ValueError, parse, """\
bootloader: u-boat
volumes:
 - partitions:
   - type: ESP
""")

    def test_no_volumes(self):
        self.assertRaises(ValueError, parse, """\
bootloader: u-boot
""")

    def test_bad_partition_scheme(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partition-scheme: BAD
   partitions:
   - type: ESP
""")

    def test_no_partitions(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partition-scheme: GPT
""")

    def test_partition_type_guid(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: 00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.GPT)
        partition0 = volume0.partitions[0]
        self.assertEqual(
            partition0.type, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

    def test_conflicting_partition_schemes_UUID_MBR(self):
        # We can't have an explicit partition schema of MBR when using a GUID
        # partition type.
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partition-scheme: MBR
   partitions:
   - type: 00000000-0000-0000-0000-0000deadbeef
""")

    def test_2HEX_partition_type(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partition-scheme: MBR
   partitions:
   - type: EF
""")
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.MBR)
        partition0 = volume0.partitions[0]
        self.assertEqual(partition0.type, 'EF')

    def test_2HEX_partition_type_casefold(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partition-scheme: MBR
   partitions:
   - type: ef
""")
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.MBR)
        partition0 = volume0.partitions[0]
        self.assertEqual(partition0.type, 'EF')

    def test_conflicting_partition_schemes_2HEX_implicit_GPT(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partitions:
   - type: EF
""")

    def test_conflicting_partition_schemes_2HEX_explicit_GPT(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partition-scheme: GPT
   partitions:
   - type: EF
""")

    def test_hybrid_partition_type_GPT(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partition-scheme: GPT
   partitions:
   - type: ef/00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.GPT)
        partition0 = volume0.partitions[0]
        self.assertEqual(
            partition0.type,
            ('EF', UUID(hex='00000000-0000-0000-0000-0000deadbeef')))

    def test_hybrid_partition_type_MBR(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partition-scheme: MBR
   partitions:
   - type: ef/00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes[0]
        self.assertEqual(volume0.partition_scheme, PartitionScheme.MBR)
        partition0 = volume0.partitions[0]
        self.assertEqual(
            partition0.type,
            ('EF', UUID(hex='00000000-0000-0000-0000-0000deadbeef')))

    def test_bad_partition_type(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partitions:
   - type: not-a-type
""")

    def test_short_partition_type(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partitions:
   - type: X
""")

    def test_partition_name(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - name: whatever partition
     type: ESP
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.name, 'whatever partition')

    def test_partition_offset(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     offset: 1024
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.offset, 1024)

    def test_partition_offset_M(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     offset: 1M
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.offset, MiB(1))

    def test_partition_offset_G(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     offset: 2G
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.offset, GiB(2))

    def test_partition_offset_bad_suffix(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     offset: 2Q
""")

    def test_partition_size(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     size: 1024
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.size, 1024)

    def test_partition_size_M(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     size: 1M
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.size, MiB(1))

    def test_partition_size_G(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     size: 2G
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.size, GiB(2))

    def test_partition_size_bad_suffix(self):
        self.assertRaises(ValueError, parse, """\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     size: 2Q
""")

    def test_content_paths(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     content:
        - uboot.env
        - EFI/
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.content, ['uboot.env', 'EFI/'])

    def test_content_data(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     content:
        - data: one.img
        - data: two.img
          offset: 1024
        - data: three.img
        - data: four.img
          offset: 1M
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.content, [
            dict(data='one.img'),
            dict(data='two.img', offset=1024),
            dict(data='three.img'),
            dict(data='four.img', offset=MiB(1)),
            ])

    def test_content_source_target(self):
        gadget_spec = parse("""\
bootloader: grub
volumes:
 - partitions:
   - type: ESP
     content:
        - source: one
        - source: two
          target: three
        - source: four
          target: five
          unpack: false
        - source: six
          target: seven
          unpack: true
""")
        partition0 = gadget_spec.volumes[0].partitions[0]
        self.assertEqual(partition0.content, [
            dict(source='one', target='/', unpack=False),
            dict(source='two', target='three', unpack=False),
            dict(source='four', target='five', unpack=False),
            dict(source='six', target='seven', unpack=True),
            ])
