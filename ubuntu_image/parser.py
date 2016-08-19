"""gadget.yaml parsing and validation."""

import re
import attr

from enum import Enum
from io import StringIO
from operator import methodcaller
from ubuntu_image.helpers import as_size, transform
from uuid import UUID
from voluptuous import (
    Any, Coerce, CoerceInvalid, Invalid, Match, Optional, Required, Schema)
from yaml import load


class BootLoader(Enum):
    uboot = 'u-boot'
    grub = 'grub'


class VolumeSchema(Enum):
    mbr = 'mbr'
    gpt = 'gpt'


# XXX Named partition types are still controversial.
class PartitionType(Enum):
    esp = ('EF', UUID(hex='C12A7328-F81F-11D2-BA4B-00A0C93EC93B'))
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


def Id(v):
    """Coerce to either a hex UUID or a 2-digit hex value."""
    if isinstance(v, int):
        # Okay, here's the problem.  If the id value is something like '80' in
        # the yaml file, the yaml parser will turn that into the decimal
        # integer 80, but that's really not what we want!  We want it to be
        # the hex value 0x80.  So we have to turn it back into a string and
        # allow the 2-digit validation matcher to go from there.
        if v >= 100 or v < 0:
            raise ValueError(str(v))
        v = '{:02d}'.format(v)
    elif not isinstance(v, str):
        raise ValueError
    try:
        return UUID(hex=v)
    except ValueError:
        pass
    mo = re.match('^[a-fA-F0-9]{2}$', v)
    if mo is None:
        raise ValueError(v)
    return mo.group(0).upper()


def RelativeOffset(v):
    """From the spec:

    It may be specified relative to another structure item with the
    syntax ``label+1234``.
    """
    label, plus, offset = v.partition('+')
    if len(label) == 0 or plus != '+' or len(offset) == 0:
        raise ValueError(v)
    return label, as_size(offset)


GadgetYAML = Schema({
    Optional('device-tree-origin', default='gadget'): str,
    Optional('device-tree'): str,
    Required('volumes'): {
        Match('^[-a-zA-Z0-9]+$'): Schema({
            Required('schema'): Enumify(VolumeSchema),
            Optional('bootloader'): Enumify(
                BootLoader, preprocessor=methodcaller('replace', '-', '')),
            Optional('id'): Coerce(Id),
            Required('structure'): [Schema({
                Optional('label'): str,
                Optional('offset'): Coerce(as_size),
                Optional('offset-write'): Any(Coerce(as_size), RelativeOffset),
                Optional('size'): Coerce(as_size),
                Required('type'): Any(Coerce(Id), Enumify(PartitionType)),
                Optional('id'): Coerce(UUID),
                Optional('filesystem'): Enumify(FileSystemType),
                Optional('content'): Any(
                    [Schema({
                        Required('source'): str,
                        Required('target'): str,
                        Optional('unpack', default=False): bool,
                        })
                    ],                                  # noqa: E124
                    [Schema({
                        Required('image'): str,
                        Optional('offset'): Coerce(as_size),
                        Optional('offset-write'): Any(
                            Coerce(as_size), RelativeOffset),
                        Optional('size'): Coerce(as_size),
                        Optional('unpack', default=False): bool,
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
    unpack = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        source = content['source']
        target = content['target']
        unpack = content.get('unpack')
        return cls(source, target, unpack)


@attr.s
class ContentSpecB:
    image = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()
    unpack = attr.ib()

    @classmethod
    def from_yaml(cls, content):
        image = content['image']
        offset = content.get('offset')
        offset_write = content.get('offset-write')
        size = content.get('size')
        unpack = content.get('unpack')
        return cls(image, offset, offset_write, size, unpack)


@attr.s
class StructureSpec:
    label = attr.ib()
    offset = attr.ib()
    offset_write = attr.ib()
    size = attr.ib()
    type = attr.ib()
    id = attr.ib()
    filesystem = attr.ib()
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


@transform((KeyError, Invalid), ValueError)
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
    device_tree_origin = validated.get('device-tree-origin')
    device_tree = validated.get('device-tree')
    volume_specs = {}
    bootloader_seen = False
    for image_name, image_spec in validated['volumes'].items():
        if image_name in volume_specs:
            raise ValueError('Duplicate image name: {}'.format(image_name))
        schema = image_spec['schema']
        bootloader = image_spec.get('bootloader')
        bootloader_seen |= (bootloader is not None)
        image_id = image_spec.get('id')
        structures = []
        for structure in image_spec['structure']:
            label = structure.get('label')
            offset = structure.get('offset')
            offset_write = structure.get('offset-write')
            size = structure.get('size')
            structure_type = structure['type']
            structure_id = structure.get('id')
            filesystem = structure.get('filesystem')
            content = structure.get('content')
            content_specs = []
            content_spec_class = None
            if content is not None:
                for item in content:
                    # The content is either of type spec A or B; you cannot
                    # mix them in the same volume.
                    source = item.get('source')
                    image = item.get('image')
                    if source is not None and image is not None:
                        ValueError('Invalid content specification')
                    elif source is not None:
                        if content_spec_class is ContentSpecB:
                            raise ValueError('Mixed content specifications')
                        else:
                            content_spec_class = ContentSpecA
                    elif image is not None:
                        if content_spec_class is ContentSpecA:
                            raise ValueError('Mixed content specifications')
                        else:
                            content_spec_class = ContentSpecB
                    content_specs.append(content_spec_class.from_yaml(item))
            structures.append(StructureSpec(
                label, offset, offset_write, size,
                structure_type, structure_id, filesystem,
                content_specs))
        volume_specs[image_name] = VolumeSpec(
            schema, bootloader, image_id, structures)
    if not bootloader_seen:
        raise ValueError('No bootloader volume named')
    return GadgetSpec(device_tree_origin, device_tree, volume_specs)
