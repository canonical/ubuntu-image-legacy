"""Tests of the gadget.yaml parser."""

from contextlib import ExitStack
from ubuntu_image.helpers import GiB, MiB
from ubuntu_image.parser import (
    BootLoader, FileSystemType, GadgetSpecificationError, StructureRole,
    VolumeSchema, parse)
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID


class TestParser(TestCase):
    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Many of the tests existed before the sector size warning was added,
        # and rather than change all those tests, let's just quiet the
        # warnings.
        self._resources.enter_context(
            patch('ubuntu_image.parser._logger.warning'))

    def test_minimal(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
        - type: 83,00000000-0000-0000-0000-0000feedface
          role: system-data
          size: 100M
""")
        self.assertEqual(gadget_spec.device_tree_origin, 'gadget')
        self.assertIsNone(gadget_spec.device_tree)
        self.assertEqual(gadget_spec.volumes.keys(), {'first-image'})
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.gpt)
        self.assertEqual(volume0.bootloader, BootLoader.uboot)
        self.assertIsNone(volume0.id)
        self.assertEqual(len(volume0.structures), 2)
        structure0 = volume0.structures[0]
        self.assertIsNone(structure0.name)
        self.assertEqual(structure0.offset, MiB(1))
        self.assertIsNone(structure0.offset_write)
        self.assertEqual(structure0.size, MiB(400))
        self.assertEqual(
            structure0.type, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))
        self.assertIsNone(structure0.id)
        self.assertEqual(structure0.filesystem, FileSystemType.none)
        self.assertIsNone(structure0.filesystem_label)
        self.assertEqual(len(structure0.content), 0)

    def test_connections_supported(self):
        parse("""\
connections:
  - plug: aaaa:bbbb
    slot: cccc:dddd
  - plug: aaaa:bbbb
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        # We're just making sure that the parser doesn't die when
        # encountering the connections: stanza.

    def test_device_tree(self):
        gadget_spec = parse("""\
device-tree-origin: kernel
device-tree: dtree
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(gadget_spec.device_tree_origin, 'kernel')
        self.assertEqual(gadget_spec.device_tree, 'dtree')
        self.assertEqual(gadget_spec.volumes.keys(), {'first-image'})

    def test_mbr_schema(self):
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

    def test_missing_schema(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.gpt)

    def test_mbr_with_hybrid_type(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef,00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.schema, VolumeSchema.mbr)
        partition0 = volume0.structures[0]
        self.assertEqual(
            partition0.type,
            ('EF', UUID(hex='00000000-0000-0000-0000-0000deadbeef')))

    def test_implicit_gpt_with_hybrid_type(self):
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

    def test_explicit_gpt_with_hybrid_type(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
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

    def test_grub(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.bootloader, BootLoader.grub)

    def test_guid_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    id: 00000000-0000-0000-0000-0000deadbeef
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(volume0.id, '80')

    def test_volume_name(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - name: my volume
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.name, 'my volume')
        self.assertEqual(partition0.filesystem_label, 'my volume')

    def test_duplicate_volume_name(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first:
    bootloader: u-boot
    structure:
        - name: one
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
  second:
    structure:
        - name: two
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
  first:
    structure:
        - name: three
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception), 'Duplicate key: first')

    def test_volume_offset(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          offset-write: some_label+2112
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset_write, ('some_label', 2112))

    def test_volume_offset_write_is_just_under_4G(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          offset-write: 4294967295
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.offset_write, GiB(4) - 1)

    def test_volume_size(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 3M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.size, MiB(3))

    def test_no_size(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:size')

    def test_bad_hybrid_volume_type_1(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,80
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_2(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,\
00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_3(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,ab
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_4(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_5(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ,00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'gadget.yaml file is not valid YAML')

    def test_volume_id(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          id: 00000000-0000-0000-0000-0000deadbeef
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(
            partition0.id, UUID(hex='00000000-0000-0000-0000-0000deadbeef'))

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

    def test_volume_filesystem_vfat(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.filesystem, FileSystemType.none)

    def test_volume_filesystem_bad(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: zfs
""")
        self.assertEqual(
            str(cm.exception),
            ("Invalid gadget.yaml value 'zfs' @ "
             'volumes:<volume name>:structure:<N>:filesystem'))

    def test_volume_structure_role(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 100
          role: mbr
  second-image:
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
          role: system-boot
  third-image:
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
          size: 300
          role: system-data
  fourth-image:
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
          size: 400
  fifth-image:
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
          size: 500
          role: system-recovery
""")
        self.assertEqual(len(gadget_spec.volumes), 5)
        self.assertEqual({
            'first-image': StructureRole.mbr,
            'second-image': StructureRole.system_boot,
            'third-image': StructureRole.system_data,
            'fourth-image': None,
            'fifth-image': StructureRole.system_recovery,
            },
            {key: gadget_spec.volumes[key].structures[0].role
             for key in gadget_spec.volumes}
            )

    def test_volume_structure_role_system_data_bad_label(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
          role: system-data
          filesystem-label: foobar
""")
        self.assertEqual(
            str(cm.exception),
            ('`role: system-data` structure must have an implicit label, '
             "or 'writable': foobar"))

    def test_volume_structure_type_none(self):
        gadget_spec = parse("""
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 100
          role: mbr
  second-image:
    structure:
        - type: bare
          size: 200
""")
        self.assertEqual(len(gadget_spec.volumes), 2)
        self.assertEqual({
            'first-image': 'EF',
            'second-image': 'bare',
            },
            {key: gadget_spec.volumes[key].structures[0].type
             for key in gadget_spec.volumes}
             )

    def test_volume_structure_type_role_conflict_1(self):
        # type:none means there's no partition, so you can't have a role of
        # system-{boot,data}.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 100
          role: mbr
  second-image:
    structure:
        - type: bare
          size: 200
          role: system-boot
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml: structure role/type conflict')

    def test_volume_structure_type_role_conflict_2(self):
        # type:none means there's no partition, so you can't have a role of
        # system-{boot,data}.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: 100
          role: mbr
  second-image:
    structure:
        - type: bare
          size: 200
          role: system-data
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml: structure role/type conflict')

    def test_volume_structure_type_role_redundant(self):
        # type:none means there's no partition.  It's valid, but redundant to
        # also give a role:mbr.
        gadget_spec = parse("""
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: bare
          size: 100
          role: mbr
        - type: 83,00000000-0000-0000-0000-0000feedface
          role: system-data
          size: 100M
""")
        self.assertEqual(len(gadget_spec.volumes), 1)
        volume = gadget_spec.volumes['first-image']
        self.assertEqual(len(volume.structures), 2)
        structure = volume.structures[0]
        self.assertEqual(structure.role, StructureRole.mbr)
        self.assertEqual(structure.type, 'bare')

    def test_volume_structure_invalid_role(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 100
          role: foobar
""")
        self.assertEqual(
            str(cm.exception),
            ("Invalid gadget.yaml value 'foobar' @ "
             'volumes:<volume name>:structure:<N>:role'))

    def test_volume_structure_mbr_role_sizes(self):
        exception = 'mbr structures cannot be larger than 446 bytes.'
        cases = {
            '445': False,
            '446': False,
            '447': True,
            '1M': True,
            }
        for size, raises in cases.items():
            with ExitStack() as resources:
                if raises:
                    cm = resources.enter_context(
                        self.assertRaises(GadgetSpecificationError))
                parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          size: {}
          role: mbr
""".format(size))
            if raises:
                self.assertEqual(
                    str(cm.exception),
                    exception)

    def test_volume_structure_mbr_conflicting_id(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          role: mbr
          size: 100
          id: 00000000-0000-0000-0000-0000deadbeef
""")
        self.assertEqual(
            str(cm.exception),
            'mbr structures must not specify partition id')

    def test_volume_structure_mbr_conflicting_filesystem(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: ef
          role: mbr
          size: 100
          filesystem: ext4
""")
        self.assertEqual(
            str(cm.exception),
            'mbr structures must not specify a file system')

    def test_volume_special_type_mbr(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: mbr
          size: 100
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        self.assertEqual(partition0.type, 'mbr')
        self.assertEqual(partition0.role, StructureRole.mbr)
        self.assertEqual(partition0.filesystem, FileSystemType.none)

    def test_volume_special_type_mbr_and_role(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: mbr
          role: mbr
          size: 100
""")
        self.assertEqual(
            str(cm.exception),
            'Type mbr and role fields assigned at the same time, please use '
            'the mbr role instead')

    def test_volume_special_type_mbr_and_filesystem(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: mbr
          size: 100
          filesystem: ext4
""")
        self.assertEqual(
            str(cm.exception),
            'mbr structures must not specify a file system')

    def test_volume_special_label_system_boot(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
          filesystem-label: system-boot
""")
        volume0 = gadget_spec.volumes['first-image']
        partition = volume0.structures[0]
        self.assertEqual(partition.filesystem_label, 'system-boot')
        self.assertEqual(partition.role, StructureRole.system_boot)

    def test_volume_special_label_system_recovery(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
          filesystem-label: system-recovery
""")
        volume0 = gadget_spec.volumes['first-image']
        partition = volume0.structures[0]
        self.assertEqual(partition.filesystem_label, 'system-recovery')
        self.assertEqual(partition.role, StructureRole.system_recovery)

    def test_content_spec_a(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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

    def test_content_spec_b_offset_write_is_just_under_4G(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          content:
          - image: foo.img
            offset-write: 4294967295
""")
        volume0 = gadget_spec.volumes['first-image']
        partition0 = volume0.structures[0]
        content0 = partition0.content[0]
        self.assertEqual(content0.offset_write, GiB(4) - 1)

    def test_content_spec_b_size(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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

    def test_content_a_multiple(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
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
        - type: 00000000-0000-0000-0000-0000deadbeef
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

    def test_multiple_volumes_with_bootloader(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 100
  second-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
  third-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
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

    def test_defaults_proper(self):
        gadget_spec = parse("""\
defaults:
  mfq0tsAY:
    some-key: some-value
    other-key: 42
volumes:
  first-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 100
  second-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
  third-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
          size: 300
""")
        self.assertEqual(len(gadget_spec.defaults), 1)
        self.assertEqual(len(gadget_spec.defaults['mfq0tsAY']), 2)
        self.assertEqual(
            gadget_spec.defaults['mfq0tsAY']['some-key'],
            'some-value')
        self.assertEqual(
            gadget_spec.defaults['mfq0tsAY']['other-key'],
            '42')

    def test_defaults_with_dot(self):
        gadget_spec = parse("""\
defaults:
  mfq0tsAY:
    some-key.disable: true
volumes:
  first-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 100
  second-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000feedface
          size: 200
  third-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deafbead
          size: 300
""")
        self.assertEqual(len(gadget_spec.defaults), 1)
        self.assertEqual(len(gadget_spec.defaults['mfq0tsAY']), 1)
        self.assertTrue(gadget_spec.defaults['mfq0tsAY']['some-key.disable'])

    def test_parser_format_version(self):
        gadget_spec = parse("""\
format: 0
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(gadget_spec.format, 0)

    def test_parser_format_version_legacy(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertIsNone(gadget_spec.format)


class TestParserWarnings(TestCase):
    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        self._mock = self._resources.enter_context(
            patch('ubuntu_image.parser._logger.warning'))

    def test_sector_misalign_size_type(self):
        self._resources.enter_context(
            patch('ubuntu_image.parser.get_default_sector_size',
                  return_value=111))
        parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 590
""")
        self.assertEqual(len(self._mock.call_args_list), 1)
        posargs, kwargs = self._mock.call_args_list[0]
        self.assertEqual(
            posargs[0],
            'Partition type 00000000-0000-0000-0000-0000deadbeef size/offset '
            'need to be a multiple of sector size (111).  The size/offset '
            'will be rounded up to the nearest sector.')

    def test_sector_misalign_size_name(self):
        self._resources.enter_context(
            patch('ubuntu_image.parser.get_default_sector_size',
                  return_value=111))
        parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          name: beefy
          size: 590
""")
        self.assertEqual(len(self._mock.call_args_list), 1)
        posargs, kwargs = self._mock.call_args_list[0]
        self.assertEqual(
            posargs[0],
            'Partition beefy size/offset need to be a multiple of sector '
            'size (111).  The size/offset will be rounded up to the '
            'nearest sector.')

    def test_sector_misalign_offset_role(self):
        self._resources.enter_context(
            patch('ubuntu_image.parser.get_default_sector_size',
                  return_value=111))
        parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          role: system-data
          size: 1M
          offset: 590
""")
        self.assertEqual(len(self._mock.call_args_list), 1)
        posargs, kwargs = self._mock.call_args_list[0]
        self.assertEqual(
            posargs[0],
            'Partition role system-data size/offset need to be a multiple of '
            'sector size (111).  The size/offset will be rounded up to the '
            'nearest sector.')


class TestParserErrors(TestCase):
    # Test corner cases, as well as YAML, schema, and specification violations.

    def setUp(self):
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Many of the tests existed before the sector size warning was added,
        # and rather than change all those tests, let's just quiet the
        # warnings.
        self._resources.enter_context(
            patch('ubuntu_image.parser._logger.warning'))

    def test_not_yaml(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""foo: bar: baz""")
        self.assertEqual(str(cm.exception),
                         'gadget.yaml file is not valid YAML')

    def test_bad_schema(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: bad
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            "Invalid gadget.yaml value 'bad' @ volumes:<volume name>:schema")

    def test_implicit_gpt_with_two_digit_type(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'GUID structure type with non-GPT schema')

    def test_explicit_gpt_with_two_digit_type(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: ef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'GUID structure type with non-GPT schema')

    def test_mbr_with_guid_type(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'MBR structure type with non-MBR schema')

    def test_mbr_with_bogus_type(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: mbr
    bootloader: u-boot
    structure:
        - type: 801
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_bootloader(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boat
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            ("Invalid gadget.yaml value 'u-boat' @ "
             'volumes:<volume name>:bootloader'))

    def test_missing_bootloader(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception), 'No bootloader structure named')

    def test_missing_bootloader_multiple_volumes(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
  second-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
  third-image:
    schema: gpt
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception), 'No bootloader structure named')

    def test_no_nuthin(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse('')
        self.assertEqual(str(cm.exception), 'Empty gadget.yaml')

    def test_no_volumes(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
device-tree-origin: kernel
device-tree: dtree
""")
        self.assertEqual(str(cm.exception), 'Invalid gadget.yaml @ volumes')

    def test_mixed_offset_conflict(self):
        # Most of the structures have an offset, but one doesn't.  The
        # bb00deadbeef part is implicitly offset at 700MiB which because it is
        # 200MiB in size, conflicts with the offset @ 800M of dd00deadbeef.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
          offset: 800M
        - type: 00000000-0000-0000-0000-cc00deadbeef
          size: 500M
          offset: 200M
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 200M
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
          offset: 1M
""")
        self.assertEqual(
            str(cm.exception),
            ('Structure conflict! 00000000-0000-0000-0000-dd00deadbeef: '
             '838860800 <  943718400'))

    def test_explicit_offset_conflict(self):
        # All of the structures have an offset, but they conflict.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
          offset: 800M
          name: dd
        - type: 00000000-0000-0000-0000-cc00deadbeef
          size: 500M
          offset: 350M
          name: cc
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 100M
          offset: 1200M
          name: bb
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
          offset: 1M
          name: aa
""")
        self.assertEqual(str(cm.exception),
                         'Structure conflict! dd: 838860800 <  891289600')

    def test_bad_volume_id(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 3g
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'Invalid gadget.yaml @ volumes:first-image:id')

    def test_bad_integer_volume_id(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    id: 801
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'Invalid gadget.yaml @ volumes:first-image:id')

    def test_disallow_hybrid_volume_id(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          id: 80,00000000-0000-0000-0000-0000deadbeef
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:id')

    def test_volume_id_not_guid(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          id: ef
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:id')

    def test_no_structure(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure')

    def test_volume_offset_write_relative_syntax_error(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          offset-write: some_label%2112
""")
        self.assertEqual(
            str(cm.exception),
            ('Invalid gadget.yaml @ '
             'volumes:first-image:structure:0:offset-write'))

    def test_volume_offset_write_larger_than_32bit(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          offset-write: 8G
""")
        self.assertEqual(
            str(cm.exception),
            ('Invalid gadget.yaml @ '
             'volumes:first-image:structure:0:offset-write'))

    def test_volume_offset_write_is_4G(self):
        # 4GiB is just outside 32 bits.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          offset-write: 4G
""")
        self.assertEqual(
            str(cm.exception),
            ('Invalid gadget.yaml @ '
             'volumes:first-image:structure:0:offset-write'))

    def test_no_size(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:size')

    def test_bad_hybrid_volume_type_1(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,80
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_2(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef,\
00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_3(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,ab
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_4(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 80,
          size: 400M
""")
        self.assertEqual(
            str(cm.exception),
            'Invalid gadget.yaml @ volumes:first-image:structure:0:type')

    def test_bad_hybrid_volume_type_5(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: ,00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'gadget.yaml file is not valid YAML')

    def test_volume_filesystem_bad(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: zfs
""")
        self.assertEqual(
            str(cm.exception),
            ("Invalid gadget.yaml value 'zfs' @ "
             'volumes:<volume name>:structure:<N>:filesystem'))

    def test_content_spec_b_offset_write_larger_than_32bit(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          content:
          - image: foo.img
            offset-write: 8G
""")
        # XXX https://github.com/alecthomas/voluptuous/issues/239
        front, colon, end = str(cm.exception).rpartition(':')
        self.assertEqual(
            front,
            'Invalid gadget.yaml @ volumes:first-image:structure:0:content:0')
        self.assertIn(end, ['offset-write', 'image'])

    def test_content_spec_b_offset_write_is_4G(self):
        # 4GiB is just outside 32 bits.
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          content:
          - image: foo.img
            offset-write: 4G
""")
        # XXX https://github.com/alecthomas/voluptuous/issues/239
        front, colon, end = str(cm.exception).rpartition(':')
        self.assertEqual(
            front,
            'Invalid gadget.yaml @ volumes:first-image:structure:0:content:0')
        self.assertIn(end, ['offset-write', 'image'])

    def test_wrong_content_1(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: none
          content:
          - source: subdir/
            target: /
""")
        self.assertEqual(str(cm.exception),
                         'filesystem: none missing image file name')

    def test_wrong_content_2(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: ext4
          content:
          - image: foo.img
""")
        self.assertEqual(str(cm.exception),
                         'filesystem: vfat|ext4 missing source/target')

    def test_content_conflict_1(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: ext4
          content:
          - source: subdir/
            target: /
          - image: foo.img
""")
        # https://github.com/alecthomas/voluptuous/issues/239
        #
        # XXX Because of the above bug, we get a sort of confusing error
        # message.  The voluptuous constraint engine will throw an exception
        # with a less than helpful message, but it's the best we can do.
        self.assertEqual(
            str(cm.exception),
            ('Invalid gadget.yaml @ '
             'volumes:first-image:structure:0:content:1:image'))

    def test_content_conflict_2(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    schema: gpt
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
          filesystem: ext4
          content:
          - image: foo.img
          - source: subdir/
            target: /
""")
        # https://github.com/alecthomas/voluptuous/issues/239
        #
        # XXX Because of the above bug, we get a sort of confusing error
        # message.  The voluptuous constraint engine will throw an exception
        # with a less than helpful message, but it's the best we can do.
        self.assertEqual(
            str(cm.exception),
            ('Invalid gadget.yaml @ '
             'volumes:first-image:structure:0:content:0:image'))

    def test_parser_format_version_error(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
format: 1
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'Unsupported gadget.yaml format version: 1')

    def test_parser_format_version_negative(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
format: -1
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'Unsupported gadget.yaml format version: -1')

    def test_parser_format_version_bogus(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
format: bogus
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
""")
        self.assertEqual(str(cm.exception),
                         'Unsupported gadget.yaml format version: bogus')

    def test_mbr_structure_not_at_offset_zero_explicit(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - role: mbr
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 446
          offset: 10
""")
        self.assertEqual(str(cm.exception),
                         'mbr structure must start at offset 0')

    def test_mbr_structure_not_at_offset_zero_implicit(self):
        with ExitStack() as resources:
            cm = resources.enter_context(
                self.assertRaises(GadgetSpecificationError))
            parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 2M
        - role: mbr
          type: 00000000-0000-0000-0000-0000deadbeef
          size: 446
""")
        self.assertEqual(str(cm.exception),
                         'mbr structure must start at offset 0')

    def test_implicit_system_data_partition(self):
        gadget_spec = parse("""\
volumes:
  first-image:
    bootloader: u-boot
    structure:
        - type: 00000000-0000-0000-0000-0000deadbeef
          size: 400M
        - type: 00000000-0000-0000-0000-0000feedface
          size: 100M
""")
        volume0 = gadget_spec.volumes['first-image']
        self.assertEqual(len(volume0.structures), 3)
        partition2 = volume0.structures[2]
        self.assertEqual(partition2.role, StructureRole.system_data)
        self.assertEqual(partition2.offset, MiB(501))
        self.assertEqual(partition2.size, None)
        self.assertEqual(partition2.filesystem, FileSystemType.ext4)
        self.assertEqual(partition2.filesystem_label, 'writable')


class TestPartOrder(TestCase):
    # LP: #1631423
    maxDiff = None

    def test_implicit_offset_ordering(self):
        # None of the structures have an offset.  They get ordered in yaml
        # appearance order with offsets calculated to be the end of the
        # previous structure.
        gadget_spec = parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
        - type: 00000000-0000-0000-0000-cc00deadbeef
          role: system-data
          size: 500M
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 100M
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
""")
        parts = gadget_spec.volumes['first'].structures
        self.assertEqual(
            [(part.type, part.offset) for part in parts], [
                (UUID('00000000-0000-0000-0000-dd00deadbeef'), MiB(1)),
                (UUID('00000000-0000-0000-0000-cc00deadbeef'), MiB(401)),
                (UUID('00000000-0000-0000-0000-bb00deadbeef'), MiB(901)),
                (UUID('00000000-0000-0000-0000-aa00deadbeef'), MiB(1001)),
                ])

    def test_explicit_offset_ordering(self):
        # All of the structures have an offset, specified in an order that
        # does not match their partitioning order.
        gadget_spec = parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
          offset: 800M
        - type: 00000000-0000-0000-0000-cc00deadbeef
          role: system-data
          size: 500M
          offset: 200M
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 100M
          offset: 1200M
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
          offset: 1M
""")
        parts = gadget_spec.volumes['first'].structures
        self.assertEqual(
            [(part.type, part.offset) for part in parts], [
                (UUID('00000000-0000-0000-0000-dd00deadbeef'), MiB(800)),
                (UUID('00000000-0000-0000-0000-cc00deadbeef'), MiB(200)),
                (UUID('00000000-0000-0000-0000-bb00deadbeef'), MiB(1200)),
                (UUID('00000000-0000-0000-0000-aa00deadbeef'), MiB(1)),
                ])

    def test_mixed_offset_ordering(self):
        # Most of the structures have an offset, but one doesn't.  The
        # bb00deadbeef part is implicitly offset at 700MiB.
        gadget_spec = parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
          offset: 800M
        - type: 00000000-0000-0000-0000-cc00deadbeef
          role: system-data
          size: 500M
          offset: 200M
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 100M
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
          offset: 1M
""")
        parts = gadget_spec.volumes['first'].structures
        self.assertEqual(
            [(part.type, part.offset) for part in parts], [
                (UUID('00000000-0000-0000-0000-dd00deadbeef'), MiB(800)),
                (UUID('00000000-0000-0000-0000-cc00deadbeef'), MiB(200)),
                (UUID('00000000-0000-0000-0000-bb00deadbeef'), MiB(700)),
                (UUID('00000000-0000-0000-0000-aa00deadbeef'), MiB(1)),
                ])

    def test_mixed_offset_ordering_implicit_rootfs(self):
        gadget_spec = parse("""\
volumes:
  first:
    schema: gpt
    bootloader: grub
    structure:
        - type: 00000000-0000-0000-0000-dd00deadbeef
          size: 400M
          offset: 800M
        - type: 00000000-0000-0000-0000-cc00deadbeef
          size: 500M
          offset: 200M
        - type: 00000000-0000-0000-0000-bb00deadbeef
          size: 100M
        - type: 00000000-0000-0000-0000-aa00deadbeef
          size: 100M
          offset: 1M
""")
        volume0 = gadget_spec.volumes['first']
        self.assertEqual(len(volume0.structures), 5)
        partition4 = volume0.structures[4]
        self.assertEqual(partition4.role, StructureRole.system_data)
        self.assertEqual(partition4.offset, MiB(1200))
