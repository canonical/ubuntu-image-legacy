"""image.yaml parsing and validation."""

import re

from enum import Enum
from io import StringIO
from operator import methodcaller
from ubuntu_image.helpers import as_size, transform
from uuid import UUID
from voluptuous import (
    Any, Coerce, CoerceInvalid, Invalid, Match, Optional, Required, Schema,
    Upper)
from yaml import load


def hex_guid(s):
    """A two-digit hex code, followed by a slash, followed by a GUID.

    This is used to define a partition in a way that it can be reused with a
    partition-scheme of either MBR or GPT without modification.
    """
    mo = re.match('^(?P<hex>[a-fA-F0-9]{2})/(?P<guid>[a-fA-F0-9-]+)$', s)
    if mo is None:
        raise ValueError(s)
    hex_bits = mo.group(1).upper()
    # Let this raise a ValueError to be caught by voluptuous.
    guid_bits = UUID(hex=mo.group(2))
    return hex_bits, guid_bits


class BootLoader(Enum):
    uboot = 'u-boot'
    grub = 'grub'


class PartitionScheme(Enum):
    MBR = 'MBR'
    GPT = 'GPT'


class PartitionType(Enum):
    ESP = ('EF', UUID(hex='C12A7328-F81F-11D2-BA4B-00A0C93EC93B'))
    raw = ('DA', UUID(hex='21686148-6449-6E6F-744E-656564454649'))
    mbr = 'mbr'


class FileSystemType(Enum):
    ext4 = 'ext4'
    vfat = 'vfat'


class Enumify(Coerce):
    def __init__(self, type, msg=None, preprocessor=None):
        super().__init__(type, msg)
        self.preprocessor = preprocessor

    def __call__(self, v):
        try:
            return self.type[
                v if self.preprocessor is None
                else self.preprocessor(v)
                ]
        except (ValueError, TypeError):
            msg = self.msg or ('expected %s' % self.type_name)
            raise CoerceInvalid(msg)


GadgetYAML = Schema({
    Required('bootloader'):
        Enumify(BootLoader, preprocessor=methodcaller('replace', '-', '')),
    Required('volumes'): [Schema({
        Optional('partition-scheme', default=PartitionScheme.GPT):
            Enumify(PartitionScheme),
        Required('partitions'): [Schema({
            Optional('name'): str,
            Required('type'): Any(
                Coerce(UUID),
                Upper(Match('^[a-fA-F0-9]{2}$')),
                Coerce(hex_guid),
                Enumify(PartitionType),
                ),
            Optional('fs-type'): Enumify(FileSystemType),
            Optional('offset'): Coerce(as_size),
            Optional('size'): Coerce(as_size),
            })],
        })],
    })


class PartitionSpec:
    def __init__(self, name, p_type, fs_type, offset, size, content=None):
        self.name = name
        self.type = p_type
        self.fs_type = fs_type
        self.offset = offset
        self.size = size
        self.content = content


class VolumeSpec:
    def __init__(self, scheme, partitions):
        self.partition_scheme = scheme
        self.partitions = partitions


class GadgetSpec:
    def __init__(self, bootloader, volumes):
        self.bootloader = bootloader
        self.volumes = volumes


@transform((KeyError, Invalid), ValueError)
def parse(stream_or_string):
    """Parse the YAML read from the stream or string.

    The YAML is parsed and validated against the schema defined in
    docs/image-yaml.rst.

    :param stream_or_string: Either a string or a file-like object containing
        a gadget.yaml specification.  If stream is given, it must be open for
        reading with a UTF-8 encoding.
    :type stream_or_string: str or file-like object
    :return: A specification of the gadget.
    :rtype: GadgetSpec
    :raises ValueError: If the schema is violated.
    """
    # Do the basic schema validation steps.  There some interdependencies that
    # require post-validation.  E.g. you cannot define the fs-type if the role
    # is ESP.
    if isinstance(stream_or_string, str):
        yaml = load(StringIO(stream_or_string))
    else:
        yaml = load(stream_or_string)
    validated = GadgetYAML(yaml)
    volume_specs = []
    for volume in validated['volumes']:
        scheme = volume['partition-scheme']
        partitions = volume['partitions']
        partition_specs = []
        for partition in partitions:
            name = partition.get('name')
            p_type = partition['type']
            fs_type = partition.get('fs-type')
            offset = partition.get('offset')
            size = partition.get('size')
            # content = partition.get('content')
            #
            # Additional sanity checks which can't be performed as pure schema
            # syntax checks because of cross-item dependencies.
            if p_type is PartitionType.ESP:
                if fs_type is None:
                    fs_type = FileSystemType.vfat
                elif fs_type is FileSystemType.vfat:
                    pass
                else:
                    raise ValueError('ESP partitions must be vfat')
            if isinstance(p_type, UUID):
                if scheme is not PartitionScheme.GPT:
                    raise ValueError('UUID partition type on non-GPT volume')
            partition_specs.append(
                PartitionSpec(name, p_type, fs_type, offset, size))
        volume_specs.append(VolumeSpec(scheme, partition_specs))
    return GadgetSpec(validated['bootloader'], volume_specs)
