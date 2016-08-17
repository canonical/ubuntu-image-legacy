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


def Hex2(v):
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
    Required('bootloader'): Enumify(
        BootLoader, preprocessor=methodcaller('replace', '-', '')),
    Required('volumes'): {
        Match('^[-a-zA-Z0-9]+$'): Schema({
            Required('schema'): Enumify(VolumeSchema),
            Optional('id'): Any(Coerce(UUID), Hex2),
            Required('structure'): [Schema({
                Optional('label'): str,
                Optional('offset'): Coerce(as_size),
                Optional('offset-write'): Any(Coerce(as_size), RelativeOffset),
                Optional('size'): Coerce(as_size),
                Required('type'): Any(
                    Coerce(UUID),
                    Hex2,
                    Enumify(PartitionType),
                    ),
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
        offset_write = content.get('offset_write')
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
    id = attr.ib()
    structure = attr.ib()


@attr.s
class GadgetSpec:
    bootloader = attr.ib()
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
    bootloader = validated['bootloader']
    volume_specs = {}
    for image_name, image_spec in validated['volumes'].items():
        if image_name in volume_specs:
            raise ValueError('Duplicate image name: {}'.format(image_name))
        schema = image_spec['schema']
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
                    source = content.get('source')
                    image = content.get('image')
                    if source is not None and image is not None:
                        ValueError('Invalid content specification')
                    elif source is not None:
                        if content_spec_class is ContentSpecB:
                            raise ValueError('Mixed content specifications')
                        else:
                            content_spec_class is ContentSpecA
                    elif image is not None:
                        if content_spec_class is ContentSpecA:
                            raise ValueError('Mixed content specifications')
                        else:
                            content_spec_class is ContentSpecB
                    content_specs.append(content_spec_class.from_yaml(content))
            structures.append(StructureSpec(
                label, offset, offset_write, size,
                structure_type, structure_id, filesystem,
                content_specs))
        volume_specs[image_name] = VolumeSpec(schema, image_id, structures)
    return GadgetSpec(bootloader, volume_specs)
