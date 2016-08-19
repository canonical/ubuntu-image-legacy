==========
 Overview
==========

The ``gadget.yaml`` is a new concept, added to Snappy in the series 16 release
to support standardized image building tooling for snappy.  The file is
embedded in the *gadget* snap. It is consumed by snappy, but also read and
processed by the image toolkit (ubuntu-image) to produce a bootable image and
supporting assets (e.g. recovery or installer support).

Design
======

The design of ubuntu-image is based on earlier lessons from
``linaro-media-create``, linaro *hardware packs* and
``ubuntu-device-flash``. The tool has the following goals and assumptions in
place:

- Stable support for very wide array of images, most of which are not created
  by Canonical engineers.
- Store oriented workflow. It is expected that the tool can obtain all required
  bits from the Ubuntu store, in the form of snaps, assertions and
  store-specific snap meta-data.
- The build process is taking only two bits of input: the model assertion
  (optionally looked up from the store) and the *partitioning strategy* which
  can influence the layout of the image in certain ways. Everything else is a
  well-defined fact stored as either an assertion or as a snap published in the
  Ubuntu store.
- Some tasks are delegated to a support tool generated from snappy code base
  (or perhaps just snap CLI itself). The tool will have a stable interface
  (input, output and expected behavior) and should shield ubuntu-image from
  ongoing system design evolution.
- There is a strong preference for user-space code over kernel code. We had
  many issues caused by leftover loopback devices and kpartx errors. While it
  may appear that those issues are no longer affecting the most recent versions
  of the kernel it is our belief that this task can be accomplished with no
  kernel support.


Draft Specification
===================

The YAML file has the following top-level keys:

device-tree-origin
    (*optional*) Where to find the device tree.  Defaults to ``gadget``.

device-tree
    (*optional*) The file nameof the device tree.  If specified
    ``dtbs/<filename>`` must exist in kernel or gadget snap, depending on
    ``device-tree-origin``.

volumes
    (*required*) Collection of one or more disk images to be created.  The sub
    keys of this field are the names of the volumes.  The value associated
    with each volume name is a structure describing the layout to record in
    this volume.

XXX: how do we know which volume the writable partition is supposed to be
placed on?


Volume subkeys
--------------

The volume section is a mapping between names (an arbitrary string, containing
only ASCII alphanumeric characters and dash), to an *image spec* with the
following fields:

name-of-the-image
    (*required*) An arbitrary string naming this volume's image.


Within the ``name-of-the-image`` section are the following keys:

schema
    (*optional*) Defines the type of supported partition tables. Legal values
    are ``mbr`` and ``gpt``.  If not specified, the default is ``gpt``.

bootloader
    (*at least one*) Instructs snapd which format of bootloader environment to
    create.  Currently permitted values are ``u-boot`` and ``grub``.  This key
    is required on exactly one volume, and may be optional for other volumes.

id
    (*optional*) Defines the disk ID which can be either a 2-digit hex code
    representing an MBR disk ID, or a GUID representing a GPT disk id.

structure
    (*required*) A list of one or more layouts that must be present in this
    volume, their properties and content. In general all of the content of the
    image is either pre-computed as a part of the gadget snap or must be
    assembled as a filesystem from the content provided by the gadget snap.


Structure subkeys
-----------------

Each structure is an object with the following properties:

label
    (*optional*) File system name.  There's an implementation specific
    constraint on the maximum length.

    XXX: Figure out what the implementation-specific lengths are and document.

offset
    (*optional*) The offset in bytes from the beginning of the image.  If not
    specified, placement of the structure within the disk image is
    implementation-dependent.

offset-write
    (*optional*) Location in which the offset of this structure is written
    into.  It may be specified relative to another structure item with the
    syntax ``label+1234``.

size
    (*optional*) Size of the structure.  If not specified, the size will be
    automatically computed based on the size of contents, other gadget
    specifications, and any limits imposed by offsets specified for structures
    located after this one on the disk.

type
    (*required*) The type of the structure.  This field takes one of these
    formats:

    - A GUID, representing a value used as a GPT partition type identifier.

    - A two-digit hex code, representing an MBR partition type identifier.

    - A two-digit hex code, followed by a comma, followed by a GUID.  This is
      used to define a structure in a way that it can be reused with a schema
      of either MBR or GPT without modification.

    - A name.  Valid values for named partition types are defined below.  To
      avoid ambiguity, named types must be at least three characters in length
      and not contain hyphens or commas.

id
    (*optional*) A GUID, to be used as a GPT unique partition id.  This field
    is unused on MBR volumes.

filesystem
    (*optional*) Type of the filesystem to use.  Legal values are ``ext4`` or
    ``vfat``.  If no type is specified, the default is a raw image with no
    filesystem (see below).

    If the structure has a named type, and that type has an implied filesystem
    type, it is an error to explicitly declare a value for ``filesystem``.

content
    (*optional*) Content to be copied from the gadget snap into the structure.
    This field takes a list of one of the following formats:

    ``source``
        (*required*) The file or directory to copy from the gadget snap into
        the filesystem, relative to the gadget snap's root directory.  End the
        path with a slash to indicate a recursive directory copy.
    ``target``
        (*required*) The location to copy the source into, relative to the
        file system's root.  If ``source`` is a file and target ends in a
        slash, a directory is created.
    ``unpack``
        (*optional*) When true, the ``source`` must be a tarball, which will
        be decompressed and extracted from the source into the target.
        XXX: Need to specify supported compressors.

    or

    ``image``
        (*required*) The image of the raw data to be copied as-is into the
        structure at the given offset.
    ``offset``
        (*optional*) Position in bytes to copy the image to, relative to the
        start of the structure item.  Defaults to offset(last-content-image) +
        size(last-content-image).
    ``offset-write``
        (*optional*) Optional location into which the offset of this content
        entry is to be written.  It may be specified relative to another
        structure item with the syntax ``label+1234``.
    ``size``
        (*optional*) Size of the content bits.  If not specified, defaults to
        the total length of the contained data.
    ``unpack``
        (*optional*) When true, the ``source`` must be a compressed file,
        which will be decompressed before writing.
        XXX: Need to specify supported compressors.

    A structure with a filesystem of ``ext4`` or ``vfat`` (explicit or
    implied) may only use a content field with the first format.  A structure
    with an implied filesystem of ``raw`` may only use a content field with
    the second format.


Named partition types
---------------------

The following named partition types are currently recognized.

esp
    (U)EFI System Partition.  Implies ``filesystem`` value of ``vfat``.  Maps
    to a numeric partition type of ``EF/C12A7328-F81F-11D2-BA4B-00A0C93EC93B``.

raw
    No filesystem.  Implies ``filesystem`` value of ``raw``.  Maps to a
    numeric partition type of ``DA/21686148-6449-6E6F-744E-656564454649``
    ("Non-FS data", "BIOS Boot").

mbr
    Special partition type referring to the Master Boot Record of a disk.
    Implies ``filesystem`` value of ``raw``.  This partition type accepts a
    maximum data size of 446 bytes, and is not recorded as an entry in the
    partition table (and therefore has no mapping to a numeric partition
    type).


Example
-------

::

    device-tree-origin: kernel
    device-tree: <filename>    # Optional, if specified dtbs/<filename> must
                               # exist in kernel or gadget snap (depends on
                               # origin) Note: snap_device_tree_origin and
                               # snap_device_tree are available for u-boot and
                               # grub .
    volumes:
      name-of-the-image:
        schema: mbr
        bootloader: u-boot
        id: <id>,<guid>
        structure:
          - label: foo
            offset: 12345
            offset-write: 777
            size: 88888
            type: <id>,<guid>
            id: <guid>
            filesystem: vfat
            content:
              - source: subdir/
                target: /
                unpack: false
              - image: foo.img
                offset: 4321
                offset-write: 8888
                size: 88888
                unpack: false
