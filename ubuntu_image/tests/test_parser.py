"""image.yaml parsing."""

from io import StringIO
from ubuntu_image.helpers import MiB
from ubuntu_image.parser import parse
from unittest import TestCase


class TestYAML(TestCase):
    def test_parse(self):
        # Parse an image.yaml into a partitioning role instance.
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
        stream = StringIO('partition-scheme: XXX\n')
        self.assertRaises(ValueError, parse, stream)

    def test_raw(self):
        
