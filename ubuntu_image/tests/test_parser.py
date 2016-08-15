"""gadget.yaml parsing."""

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
