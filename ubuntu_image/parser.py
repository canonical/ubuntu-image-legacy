"""image.yaml parsing and validation."""


from ubuntu_image.helpers import as_size, transform
from yaml import load


@transform(KeyError, ValueError)
def parse(image_yaml):
    """Parse the given YAML.

    The YAML is parsed and validated against the schema defined in
    docs/image-yaml.rst.

    :param image_yaml: YAML text, usually read from an image.yaml file.
    :type image_yaml: str
    :return: A specification of the image.
    :rtype: ImageSpec
    :raises ValueError: If the schema is violated.
    """
    # For now, all the logic and constraints are codified in this
    # function.  At some point it may make sense to refactor that into
    # subclasses, but for now there's enough cross-level requirements
    # that it makes that refactoring tricky.
    with open(image_yaml, 'r', encoding='utf-8') as fp:
        yaml = load(fp)
    scheme = yaml['partition-scheme']
    if scheme not in ('MBR', 'GPT'):
        raise ValueError(scheme)
    partitions = []
    for partition in yaml['partitions']:
        name = partition.get('name')
        role = partitions['role']
        guid = partition.get('guid')
        type_id = partition.get('type')
        offset = partition.get('offset')
        size = partition.get('size')
        fs_type = partitions.get('fs-type')
        # Sanity check the values for the partition role.
        if role not in ('ESP', 'raw', 'custom'):
            raise ValueError('Bad role: {}'.format(role))
        if role == 'ESP':
            if fs_type is not None:
                raise ValueError('Bad fs-type: {}'.format(fs_type))
            fs_type = 'vfat'
            if guid is not None:
                raise ValueError('Bad guid: {}'.format(guid))
            if type_id is not None:
                raise ValueError('Bad partition type id: {}'.format(type_id))
            type_id = ('EF' if scheme == 'MBR'
                       else 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B')
        elif role == 'raw':
            type_id = ('DA' if scheme == 'MBR'
                       else '21686148-6449-6E6F-744E-656564454649')
        elif role == 'custom':
            if fs_type is None:
                raise ValueError('fs-type is required')
            if type_id is not None:
                raise ValueError('Bad type_id: {}'.format(type_id))
            type_id = ('83' if scheme == 'MBR'
                       else '0FC63DAF-8483-4772-8E79-3D69D8477DE4')
        # Sanity check other values.
        if scheme == 'MBR':
            guid = None
        if scheme == 'GPT':
            type_id = None
        if offset is not None:
            offset = as_size(offset)
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
                else:
                    offset = as_size(offset)
                files.append((source, offset))
            else:
                if 'offset' in section:
                    raise ValueError('offset not allowed')
                dest = section.get('dest')
                if dest is None:
                    raise ValueError('dest required')
                files.append((source, dest))
        # XXX "It is also an error for files in the list to overlap."
