"""image.yaml parsing and validation."""


from ubuntu_image.helpers import as_size, transform
from yaml import load


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


@transform(KeyError, ValueError)
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
    # For now, all the logic and constraints are codified in this
    # function.  At some point it may make sense to refactor that into
    # subclasses, but for now there's enough cross-level requirements
    # that it makes that refactoring tricky.
    yaml = load(stream)
    try:
        scheme = yaml['partition-scheme']
    except KeyError:
        scheme = 'GPT'
    if scheme not in ('MBR', 'GPT'):
        raise ValueError(scheme)
    partitions = []
    for partition in yaml['partitions']:
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
            type_id = ('EF' if scheme == 'MBR'
                       else 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B')
            # default size, which is more than big enough for all of the
            # EFI executables that we might want to install.
            if size is None:
                size = '64M'
        elif role == 'raw':
            if fs_type is not None:
                raise ValueError(
                    'No fs-type allowed for raw partitions: {}'.format(
                        fs_type))
            type_id = ('DA' if scheme == 'MBR'
                       else '21686148-6449-6E6F-744E-656564454649')
        elif role == 'custom':
            fs_type = partition.get('fs-type')
            if fs_type is None:
                raise ValueError('fs-type is required')
            elif fs_type not in ('vfat', 'ext4'):
                raise ValueError('Invalid fs-type: {}'.format(fs_type))
            type_id = ('83' if scheme == 'MBR'
                       else '0FC63DAF-8483-4772-8E79-3D69D8477DE4')
        else:
            raise ValueError('Bad role: {}'.format(role))
        # Sanity check other values.
        if scheme == 'MBR':
            guid = None
            # Allow MBRs to override the partition type identifier.
            type_id = partition.get('type', type_id)
        if partition_offset is not None:
            # If there is no unit suffix, then the YAML parser will have
            # already converted it to an integer, which we'll interpret
            # as a byte count.
            if not isinstance(partition_offset, int):
                partition_offset = as_size(partition_offset)
        if size is not None:
            size = as_size(size)
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
                else:
                    # Similar to above, if there was no unit suffix,
                    # offset will already be an integer.
                    if not isinstance(offset, int):
                        offset = as_size(offset)
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
    # XXX reject a yaml that defines overlapping partitions
    return ImageSpec(scheme, partitions)
