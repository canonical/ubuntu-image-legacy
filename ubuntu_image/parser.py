"""image.yaml parsing and validation."""

from enum import Enum
from operator import attrgetter
from ubuntu_image.helpers import MiB, as_size, transform
from uuid import UUID
from voluptuous import (
    All, Any, Coerce, Invalid, Match, Optional, Required, Schema, Upper)
from yaml import load


ImageYAML = Schema({
    Optional('partition-scheme', default='GPT'): Any('GPT', 'MBR'),
    Required('partitions'): [
        Schema({
            Optional('name'): str,
            Required('role'): Any('ESP', 'raw', 'custom'),
            Optional('fs-type'): Any('ext4', 'vfat'),
            Optional('guid'): Coerce(UUID),
            Optional('type'): All(Upper, Match('^[a-z0-9A-Z0-9]{2}$')),
            Optional('offset'): Coerce(as_size),
            Optional('size'): Coerce(as_size),
            Optional('files'): [
                Schema({
                    Required('source'): str,
                    Optional('dest'): str,
                    Optional('offset'): Coerce(as_size),
                    })
                ],
            })],
    })


class ESPTypeID(Enum):
    MBR = 'EF'
    GPT = 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'


class RawTypeID(Enum):
    MBR = 'DA'
    GPT = '21686148-6449-6E6F-744E-656564454649'


class CustomTypeID(Enum):
    MBR = '83'
    GPT = '0FC63DAF-8483-4772-8E79-3D69D8477DE4'


class PartitionSpec:
    def __init__(self,
                 name, role, guid, type_id, offset, size, fs_type, files):
        self.name = name
        self.role = role
        self.guid = guid
        self.type_id = type_id
        self.offset = offset
        self.size = size
        self.fs_type = fs_type
        self.files = files


class ImageSpec:
    def __init__(self, scheme, partitions):
        self.scheme = scheme
        self.partitions = partitions


@transform((KeyError, Invalid), ValueError)
def parse(stream):
    """Parse the YAML read from the stream.

    The YAML is parsed and validated against the schema defined in
    docs/image-yaml.rst.

    :param stream: A file-like object containing an image.yaml
        specification.  The file should be open for reading with a UTF-8
        encoding.
    :type image_yaml: file
    :return: A specification of the image.
    :rtype: ImageSpec
    :raises ValueError: If the schema is violated.
    """
    # Do the basic schema validation steps.  There some interdependencies that
    # require post-validation.  E.g. you cannot define the fs-type if the role
    # is ESP.
    yaml = load(stream)
    validated = ImageYAML(yaml)
    scheme = validated['partition-scheme']
    partitions = []
    for partition in validated['partitions']:
        name = partition.get('name')
        role = partition['role']
        guid = partition.get('guid')
        partition_offset = partition.get('offset')
        size = partition.get('size')
        fs_type = partition.get('fs-type')
        # Sanity check the values for the partition role.
        if role == 'ESP':
            if fs_type is not None:
                raise ValueError(
                    'Invalid explicit fs-type: {}'.format(fs_type))
            fs_type = 'vfat'
            if guid is not None:
                raise ValueError('Invalid explicit guid: {}'.format(guid))
            if partition.get('type') is not None:
                raise ValueError('Invalid explicit type id: {}'.format(
                    partition.get('type')))
            type_id = ESPTypeID[scheme].value
            # Default size, which is more than big enough for all of the EFI
            # executables that we might want to install.
            if size is None:
                size = MiB(64)
        elif role == 'raw':
            if fs_type is not None:
                raise ValueError(
                    'No fs-type allowed for raw partitions: {}'.format(
                        fs_type))
            type_id = RawTypeID[scheme].value
        elif role == 'custom':
            if fs_type is None:
                raise ValueError('fs-type is required')
            type_id = CustomTypeID[scheme].value
        else:
            raise AssertionError('Should never get here!')   # pragma: nocover
        # Sanity check other values.
        if scheme == 'MBR':
            guid = None
            # Allow MBRs to override the partition type identifier.
            type_id = partition.get('type', type_id)
        # Handle files.
        files = []
        offset_defaulted = False
        for section in partition.get('files', []):
            source = section['source']
            if fs_type is None:
                if 'dest' in section:
                    raise ValueError('No dest allowed')
                offset = section.get('offset')
                if offset is None:
                    if offset_defaulted:
                        raise ValueError('Only one default offset allowed')
                    offset = 0
                    offset_defaulted = True
                files.append((source, offset))
            else:
                if 'offset' in section:
                    raise ValueError('offset not allowed')
                dest = section.get('dest')
                if dest is None:
                    raise ValueError(
                        'dest required for source: {}'.format(source))
                files.append((source, dest))
        # XXX "It is also an error for files in the list to overlap."
        partitions.append(PartitionSpec(
            name, role, guid, type_id, partition_offset, size, fs_type, files))
    partitions.sort(key=attrgetter('offset'))
    min_offset = 0
    for part in partitions:
        # XXX certain offsets are illegal to specify because they overlap the
        # partition table.  Should these limits be implemented here in the
        # parser, or only in the partitioner code?
        if not part.offset:
            continue
        if part.offset < min_offset:
            raise ValueError('overlapping partitions defined')
        if part.size:
            min_offset = part.offset + part.size
    return ImageSpec(scheme, partitions)
