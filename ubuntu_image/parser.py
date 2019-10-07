"""gadget.yaml parsing and validation."""

import re
import attr
import logging

from enum import Enum
from io import StringIO
from operator import attrgetter, methodcaller
from pkg_resources import parse_version
from ubuntu_image.helpers import GiB, MiB, as_size, get_default_sector_size
from uuid import UUID
from voluptuous import (
    Any, Coerce, Invalid, Match, Optional, Required, Schema,
    __version__ as voluptuous_version)
from warnings import warn
from yaml import load
from yaml.loader import SafeLoader
from yaml.parser import ParserError, ScannerError


COLON = ':'
_logger = logging.getLogger('ubuntu-image')


class GadgetSpecificationError(Exception):
    """An exception occurred during the parsing of the gadget.yaml file."""


# By default PyYAML allows duplicate mapping keys, even though the YAML spec
# prohibits this.  We can't validate this after parsing because PyYAML just
# gives us a normal dictionary, which of course does not have duplicate keys.
# We use the basic YAML SafeLoader but override the mapping constructor to
# raise an exception if we see a key twice.

class StrictLoader(SafeLoader):
    def construct_mapping(self, node):
        pairs = self.construct_pairs(node)
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise GadgetSpecificationError('Duplicate key: {}'.format(key))
            mapping[key] = value
        return mapping


StrictLoader.add_constructor(
    'tag:yaml.org,2002:map', StrictLoader.construct_mapping)
# LP: #1640523
StrictLoader.add_constructor(
    'tag:yaml.org,2002:int', StrictLoader.construct_yaml_str)


# Helper function to keep compatibility between voluptuous versions.
def has_new_voluptuous():
    return parse_version(voluptuous_version) >= parse_version('0.11.0')


# Decorator for naming the path -as best we can statically- within the
# gadget.yaml file where this enum is found.  Used in error reporting.
def yaml_path(path):
    def inner(cls):
        cls.yaml_path = path
        return cls
    return inner


@yaml_path('volumes:<volume name>:bootloader')
class BootLoader(Enum):
    uboot = 'u-boot'
    grub = 'grub'


@yaml_path('volumes:<volume name>:schema')
class VolumeSchema(Enum):
    mbr = 'mbr'
    gpt = 'gpt'


@yaml_path('volumes:<volume name>:structure:<N>:filesystem')
class FileSystemType(Enum):
    none = 'none'
    ext4 = 'ext4'
    vfat = 'vfat'


@yaml_path('volumes:<volume name>:structure:<N>:role')
class StructureRole(Enum):
    mbr = 'mbr'
    system_boot = 'system-boot'
    system_data = 'system-data'
    system_seed = 'system-seed'
    system_save = 'system-save'


class Enumify:
    def __init__(self, enum_class, msg=None, preprocessor=None):
        self.enum_class = enum_class
        self.preprocessor = preprocessor

    def __call__(self, v):
        # Turn KeyErrors into spec errors.
        try:
            return self.enum_class[
                v if self.preprocessor is None
                else self.preprocessor(v)
                ]
        except KeyError as error:
            raise GadgetSpecificationError(
                "Invalid gadget.yaml value '{}' @ {}".format(
                    v, self.enum_class.yaml_path)) from error


def Size32bit(v):
    """Coerce size to being a 32 bit integer."""
    return as_size(v, max=GiB(4))


def Id(v):
    """Coerce to either a hex UUID, a 2-digit hex value."""
    # Yes, we actually do want this function to raise ValueErrors instead of
    # GadgetSpecificationErrors.
    try:
        return UUID(hex=v)
    except ValueError:
        pass
    mo = re.match('^[a-fA-F0-9]{2}$', v)
    if mo is None:
        raise ValueError(v)
    return mo.group(0).upper()


def HybridId(v):
    """Like above, but allows for hybrid Ids."""
    # Yes, we actually do want this function to raise ValueErrors instead of
    # GadgetSpecificationErrors.
    code, comma, guid = v.partition(',')
    if comma == ',':
        # Two digit hex code must appear before GUID.
        if len(code) != 2 or len(guid) != 36:
            raise ValueError(v)
        hex_code = Id(code)
        guid_code = Id(guid)
        return hex_code, guid_code
    return Id(v)


def RelativeOffset(v):
    """From the spec:

    It may be specified relative to another structure item with the
    syntax ``label+1234``.
    """
    # Yes, we actually do want this function to raise ValueErrors instead of
    # GadgetSpecificationErrors.
    label, plus, offset = v.partition('+')
    if len(label) == 0 or plus != '+' or len(offset) == 0:
        raise ValueError(v)
    return label, Size32bit(offset)


def YAMLFormat(v):
    """Verify supported gadget.yaml format versions."""
    # Allow ValueError to percolate up.
    unsupported = False
    try:
        value = int(v)
    except ValueError:
        unsupported = True
    else:
        unsupported = (value != 0)
    if unsupported:
        raise GadgetSpecificationError(
            'Unsupported gadget.yaml format version: {}'.format(v))
    return value


GadgetYAML = Schema({
    Optional('defaults'): {
        str: {
            str: object
        }
    },
    Optional('connections'): [Schema({
        Required('plug'): str,
        Optional('slot'): str,
        })
    ],
    Optional('device-tree-origin', default='gadget'): str,
    Optional('device-tree'): str,
    Optional('format'): YAMLFormat,
    Required('volumes'): {
        Match('^[a-zA-Z0-9][-a-zA-Z0-9]*$'): Schema({
            Optional('schema', default='gpt' if has_new_voluptuous()
                     else VolumeSchema.gpt):
                Enumify(VolumeSchema),
            Optional('bootloader'): Enumify(
                BootLoader, preprocessor=methodcaller('replace', '-', '')),
            Optional('id'): Coerce(Id),
            Required('structure'): [Schema({
                Optional('name'): str,
                Optional('offset'): Coerce(as_size),
                Optional('offset-write'): Any(
                    Coerce(Size32bit), RelativeOffset),
                Required('size'): Coerce(as_size),
                Required('type'): Any('mbr', 'bare', Coerce(HybridId)),
                Optional('role'): Enumify(
                    StructureRole,
                    preprocessor=methodcaller('replace', '-', '_')),
                Optional('id'): Coerce(UUID),
                Optional('filesystem', default='none' if has_new_voluptuous()
                         else FileSystemType.none):
                    Enumify(FileSystemType),
                Optional('filesystem-label'): str,
                Optional('content'): Any(
                    [Schema({
                        Required('source'): str,
                        Required('target'): str,
                        })
                    ],                                  # noqa: E124
                    [Schema({
                        Required('image'): str,
                        Optional('offset'): Coerce(as_size),
                        Optional('offset-write'): Any(
                            Coerce(Size32bit), RelativeOffset),
                        Optional('size'): Coerce(as_size),
                        })
                    ],
                )
            })]
        })
    }
})


@attr.s
class ContentSpecA:
    source = attr.ib()
    target = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        source = content['source']
        target = content['target']
        return cls(source, target)


@attr.s
class ContentSpecB:
    image = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        image = content['image']
        offset = content.get('offset')
        offset_write = content.get('offset-write')
        size = content.get('size')
        return cls(image, offset, offset_write, size)


@attr.s
class StructureSpec:
    name = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()
    type = attr.ib()
    id = attr.ib()
    role = attr.ib()
    filesystem = attr.ib()
    filesystem_label = attr.ib()
    content = attr.ib()


@attr.s
class VolumeSpec:
    schema = attr.ib()
    bootloader = attr.ib()
    id = attr.ib()
    structures = attr.ib()


@attr.s
class GadgetSpec:
    device_tree_origin = attr.ib()
    device_tree = attr.ib()
    volumes = attr.ib()
    defaults = attr.ib()
    format = attr.ib()
    # Additional u-i internal metadata, not part of the spec
    seeded = attr.ib()


def parse(stream_or_string):
    """Parse the YAML read from the stream or string.

    The YAML is parsed and validated against the schema defined in
    docs/gadget-yaml.rst.

    :param stream_or_string: Either a string or a file-like object containing
        a gadget.yaml specification.  If stream is given, it must be open for
        reading with a UTF-8 encoding.
    :type stream_or_string: str or file-like object
    :return: A specification of the gadget.
    :rtype: GadgetSpec
    :raises GadgetSpecificationError: If the schema is violated.
    """
    # Do the basic schema validation steps.  There some interdependencies that
    # require post-validation.  E.g. you cannot define the fs-type if the role
    # is ESP.
    stream = (StringIO(stream_or_string)
              if isinstance(stream_or_string, str)
              else stream_or_string)
    try:
        yaml = load(stream, Loader=StrictLoader)
    except (ParserError, ScannerError) as error:
        raise GadgetSpecificationError(
            'gadget.yaml file is not valid YAML') from error
    try:
        validated = GadgetYAML(yaml)
    except Invalid as error:
        if len(error.path) == 0:
            raise GadgetSpecificationError('Empty gadget.yaml')
        path = COLON.join(str(component) for component in error.path)
        # It doesn't look like voluptuous gives us the bogus value, but it
        # does give us the path to it.  The str(error) contains some
        # additional information of dubious value, so just use the path.
        raise GadgetSpecificationError('Invalid gadget.yaml @ {}'.format(path))
    device_tree_origin = validated.get('device-tree-origin')
    device_tree = validated.get('device-tree')
    defaults = validated.get('defaults')
    format = validated.get('format')
    volume_specs = {}
    bootloader_seen = False
    sector_size = get_default_sector_size()
    # These two variables only exist to support backwards compatibility in the
    # single-volume, implicit-root-fs case, and are ignored when multiple
    # volumes are defined.  We have no b/c considerations for implicit-root-fs
    # in the multi-volume case.
    rootfs_seen = False
    # For UC20 a new gadget layout is used, in which only the seed partition
    # needs to be explicitly created by ubuntu-image.  In ubuntu-image we will
    # call this state as 'seeded'.
    is_seeded = False
    farthest_offset = 0
    # This item is a dictionary so it can't possibly have duplicate keys.
    # That's okay because our StrictLoader above will already raise an
    # exception if it sees a duplicate key.
    for image_name, image_spec in validated['volumes'].items():
        schema = image_spec['schema']
        bootloader = image_spec.get('bootloader')
        bootloader_seen |= (bootloader is not None)
        image_id = image_spec.get('id')
        structures = []
        structure_names = set()
        last_offset = 0
        for structure in image_spec['structure']:
            name = structure.get('name')
            if name is not None:
                if name in structure_names:
                    raise GadgetSpecificationError(
                        'Structure name "{}" is not unique'.format(name))
                structure_names.add(name)
            offset = structure.get('offset')
            offset_write = structure.get('offset-write')
            size = structure['size']
            structure_type = structure['type']
            structure_role = structure.get('role')
            # Structure types and roles work together to define how the
            # structure is laid out on disk, along with any disk partitions
            # wrapping the structure.  In general, the type field names the
            # disk partition type code for the wrapping partition, and it will
            # either be a GUID for GPT disk schemas, a two hex digit string
            # for MBR disk schemas, or a hybrid type where a tuple-like string
            # names both type codes.
            #
            # The role specifies how the structure is to be used.  It may be a
            # partition holding boot assets, or a partition holding the
            # operating system data.  Without a role specification, we drop
            # back to the filesystem label to determine this.
            #
            # There are two complications.  Disks can have a special
            # non-partition wrapped Master Boot Record section on the disk
            # containing bootstrapping code.  MBRs must start at offset 0 and
            # be no larger than 446 bytes (there is some variability for other
            # MBR layouts, but 446 is the max).  The Wikipedia page has some
            # good diagrams: https://en.wikipedia.org/wiki/Master_boot_record
            #
            # MBR sections are identified by a role:mbr key, and in that case,
            # the gadget.yaml may not include a type field (since the MBR
            # isn't a partition).
            #
            # Some use cases involve putting bootstrapping code at other
            # locations on the disk, with offsets other than zero and
            # arbitrary sizes.  This bootstrapping code is also not wrapped in
            # a disk partition.  For these, type:none is the way to specify
            # that, but in that case, you cannot include a role key.
            # Technically speaking though, role:mbr is allowed, but somewhat
            # redundant.  All other roles with type:none are prohibited.
            #
            # For backward compatibility, we still allow the type:mbr field,
            # which is exactly equivalent to the preferred role:mbr field,
            # however a deprecation warning is issued in the former case.
            if structure_type == 'mbr':
                if structure_role is not None:
                    raise GadgetSpecificationError(
                        'Type mbr and role fields assigned at the same time, '
                        'please use the mbr role instead')
                warn("volumes:<volume name>:structure:<N>:type = 'mbr' is "
                     'deprecated; use role instead', DeprecationWarning)
                structure_role = StructureRole.mbr
            # For now, the structure type value can be of several Python
            # types. 1) a UUID for GPT schemas; 2) a 2-letter str for MBR
            # schemas; 3) a 2-tuple of #1 and #2 for mixed schemas; 4) the
            # special strings 'mbr' and 'bare' which can appear for either GPT
            # or MBR schemas.  type:mbr is deprecated and will eventually go
            # away.  What we're doing here is some simple validation of #1 and
            # #2.
            if (isinstance(structure_type, UUID) and
                    schema is not VolumeSchema.gpt):
                raise GadgetSpecificationError(
                    'MBR structure type with non-MBR schema')
            elif structure_type == 'bare':
                if structure_role not in (None, StructureRole.mbr):
                    raise GadgetSpecificationError(
                        'Invalid gadget.yaml: structure role/type conflict')
            elif (isinstance(structure_type, str) and
                    structure_role is not StructureRole.mbr and
                    schema is not VolumeSchema.mbr):
                raise GadgetSpecificationError(
                    'GUID structure type with non-GPT schema')
            # Check for implicit vs. explicit partition offset.
            if offset is None:
                # XXX: Ensure the special case of the mbr role doesn't
                # extend beyond the confines of the mbr.
                if (structure_role is not StructureRole.mbr and
                        last_offset < MiB(1)):
                    offset = MiB(1)
                else:
                    offset = last_offset
            # Extract the rest of the structure data.
            structure_id = structure.get('id')
            filesystem = structure['filesystem']
            if structure_role is StructureRole.mbr:
                if size > 446:
                    raise GadgetSpecificationError(
                        'mbr structures cannot be larger than 446 bytes.')
                if offset != 0:
                    raise GadgetSpecificationError(
                        'mbr structure must start at offset 0')
                if structure_id is not None:
                    raise GadgetSpecificationError(
                        'mbr structures must not specify partition id')
                if filesystem is not FileSystemType.none:
                    raise GadgetSpecificationError(
                        'mbr structures must not specify a file system')
            else:
                # Size and offset constraints on other partitions mandate
                # sector size alignment.
                if (size % sector_size) != 0 or (offset % sector_size) != 0:
                    # Provide some hint as to which partition is unaligned.
                    # Only the structure type is required, but if the name or
                    if name is None:
                        if structure_role is None:
                            whats_wrong = 'type {}'.format(structure_type)
                        else:
                            whats_wrong = 'role {}'.format(
                                structure_role.value)
                    else:
                        whats_wrong = name

                    _logger.warning(
                        'Partition {} size/offset need to be a multiple of '
                        'sector size ({}).  The size/offset will be rounded '
                        'up to the nearest sector.'.format(
                            whats_wrong, sector_size))
            last_offset = offset + size
            farthest_offset = max(farthest_offset, last_offset)
            filesystem_label = structure.get('filesystem-label', name)
            # Support the legacy mode setting of partition roles through
            # filesystem labels.
            if structure_role is None:
                if filesystem_label == 'system-boot':
                    structure_role = StructureRole.system_boot
                    warn('volumes:<volume name>:structure:<N>:filesystem_label'
                         ' used for defining partition roles; use role '
                         'instead.', DeprecationWarning)
            elif structure_role is StructureRole.system_data:
                rootfs_seen = True
                # For images to work the system-data (rootfs) partition needs
                # to have the 'writable' filesystem label set.
                if filesystem_label not in (None, 'writable'):
                    raise GadgetSpecificationError(
                        '`role: system-data` structure must have an implicit '
                        "label, or 'writable': {}".format(filesystem_label))
            elif structure_role is StructureRole.system_seed:
                # The seed is good enough as a rootfs, snapd will create the
                # writable partition on demand
                rootfs_seen = True
                # Also, since the gadget.yaml defines a system-seed partition,
                # we can consider the image to be 'seeded'.  This basically
                # changes the u-i build mechanism to only create the
                # system-seed partition + all the the mbr/role-less partitions
                # defined on the gadget.  All the others (system-boot,
                # system-data etc.) will be created by snapd.
                is_seeded = True
            # The content will be one of two formats, and no mixing is
            # allowed.  I.e. even though multiple content sections are allowed
            # in a single structure, they must all be of type A or type B.  If
            # the filesystem type is vfat or ext4, then type A *must* be used;
            # likewise if filesystem is none or missing, type B must be used.
            content = structure.get('content')
            content_specs = []
            if content is not None:
                if filesystem is FileSystemType.none:
                    for item in content:
                        try:
                            spec = ContentSpecB.from_yaml(item)
                        except KeyError:
                            raise GadgetSpecificationError(
                                'filesystem: none missing image file name')
                        else:
                            content_specs.append(spec)
                else:
                    for item in content:
                        try:
                            spec = ContentSpecA.from_yaml(item)
                        except KeyError:
                            raise GadgetSpecificationError(
                                'filesystem: vfat|ext4 missing source/target')
                        else:
                            content_specs.append(spec)
            structures.append(StructureSpec(
                name, offset, offset_write, size,
                structure_type, structure_id, structure_role,
                filesystem, filesystem_label,
                content_specs))
        # Sort structures by their offset.
        volume_specs[image_name] = VolumeSpec(
            schema, bootloader, image_id, structures)
        # Sanity check the partition offsets to ensure that there is no
        # overlap conflict where a part's offset begins before the previous
        # part's end.
        last_end = -1
        for part in sorted(structures, key=attrgetter('offset')):
            if part.offset < last_end:
                raise GadgetSpecificationError(
                    'Structure conflict! {}: {} <  {}'.format(
                        part.type if part.name is None else part.name,
                        part.offset, last_end))
            last_end = part.offset + part.size
    if not rootfs_seen and len(volume_specs) == 1:
        # We still need to handle the case of unspecified system-data
        # partition where we simply attach the rootfs at the end of the
        # partition list.
        #
        # Since so far we have no knowledge of the rootfs contents, the
        # size is set to 0, knowing that the builder code will resize it
        # to fit all the contents.
        warn('No role: system-data partition found, a implicit rootfs '
             'partition will be appended at the end of the partition '
             'list.  An explicit system-data partition is now required.',
             DeprecationWarning)
        structures.append(StructureSpec(
            None,                             # name
            farthest_offset, None,            # offset, offset_write
            None,                             # size; None == calculate
            (                                 # type; hybrid mbr/gpt
                '83', '0FC63DAF-8483-4772-8E79-3D69D8477DE4'),
            None, StructureRole.system_data,  # id, role
            FileSystemType.ext4,              # file system type
            'writable',                       # file system label
            []))                              # contents
    if not bootloader_seen:
        raise GadgetSpecificationError('No bootloader structure named')
    return GadgetSpec(device_tree_origin, device_tree, volume_specs,
                      defaults, format, is_seeded)
