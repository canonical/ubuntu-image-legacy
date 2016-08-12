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

bootloader
    (*required*) Instructs snapd which format of bootloader environment to
    create.  Currently permitted values are ``u-boot`` and ``grub``.

volumes
    (*required*) Collection of one or more disk images to be created.  The sub
    keys of this field are the names of the volumes.  The value associated
    with each volume name is a structure describing the partition layout to
    record in this volume.

XXX: how do we know which volume the writable partition is supposed to be
placed on?


Volume subkeys
--------------

The volume structure has the following keys:

partition-scheme
    (*optional*) Defines the type of supported partition tables. Legal values
    are ``MBR`` and ``GPT``.  If not specified, the default is ``GPT``.

partitions
    (*required*) Defines a list of partitions that must be present in this
    volume, their properties and content. In general all of the content of the
    image is either pre-computed as a part of the gadget snap or must be
    assembled as a filesystem from the content provided by the gadget snap.


Partition subkeys
-----------------

Each partition is an object with the following properties:

name
    (*optional*) Partition name. There's an implementation specific
    constraint on the maximum length.
    XXX: figure out what the implementation-specific lengths are and document.

type
    (*required*) The type of the partition.  This field takes one of four
    formats:

    - A GUID, representing a value used as a GPT partition type identifier.

    - A two-digit hex code, representing an MBR partition type identifier.

    - A two-digit hex code, followed by a slash, followed by a GUID.  This is
      used to define a partition in a way that it can be reused with a
      partition-scheme of either MBR or GPT without modification.

    - A name.  Valid values for named partition types are defined below.  To
      avoid ambiguity, named types must be at least three characters in length
      and not contain slashes or hyphens.

fs-type
    (*optional*) Type of the filesystem to use.  Legal values are ``ext4``
    or ``vfat``.  If no type is specified, the default is a raw partition
    with no filesystem (see below).

    If the partition has a named partition type, and that partition type has
    an implied fs-type, it is an error to explicitly declare a value for
    fs-type.

offset
    (*optional*) The partition's offset from the beginning of the image.
    If not specified, placement of the partition within the disk image is
    implementation-dependent.

size
    (*optional*) Size of the partition.  If not specified, will be
    automatically computed based on the size of contents, the partition
    role, and any limits imposed by offsets specified for partitions
    located after this one on the disk.

content
    (*optional*) Content to be copied from the gadget snap into the partition.
    This field takes one of two formats:

    - A list of files and/or directories in the gadget snap to be copied to
      the same location within the filesystem on the partition.  Directories
      are copied recursively into the filesystem and must be declared as
      directories in the yaml by using a trailing slash.

    - A list of objects consisting of a ``data`` field an an optional
      ``offset`` field.  The ``data`` field specifies the name of a file
      within the gadget snap.  The ``offset`` field specifies the offset
      relative to the start of the partition at which to write the data.
      If no ``offset`` field is specified for a given entry, the file is
      written immediately after the end of the previous entry.  If the first
      entry has no ``offset`` field, an offset of 0 is used.

    A partition with an fs-type of ``ext4`` or ``vfat`` (explicit or implied)
    may only use a content field with the first format.  A partition with an
    implied fs-type of ``raw`` may only use a content field with the second
    format.

Named partition types
---------------------

The following named partition types are currently recognized.

ESP
    (U)EFI System Partition.  Implies fs-type of ``vfat``.  Maps to a numeric
    partition type of ``EF/C12A7328-F81F-11D2-BA4B-00A0C93EC93B``.

raw
    No filesystem.  Implies fs-type of ``raw``.  Maps to a numeric partition
    type of ``DA/21686148-6449-6E6F-744E-656564454649``
    ("Non-FS data", "BIOS Boot").

mbr
    Special partition type referring to the Master Boot Record of a disk.
    Implies fs-type of ``raw``.  This partition type accepts a maximum data
    size of 446 bytes, and is not recorded as an entry in the partition table
    (and therefore has no mapping to a numeric partition type).


Example
=======

::

    platform: msm8916-mtp # possibly needed for dtb names to copy into uboot partition; kill for now?
    bootloader: u-boot         # or grub; this tells snapd whether to create grubenv or uboot.env
    volumes:                      # each volume is a distinct disk image
        name-of-the-image:   # XXX: figure out size limit if we want to write this somewhere (MBR, GPT?)
            partitions:
                - name: sbl1
                  type: DEA0BA2C-CBDD-4805-B4F9-F428251C3E98 #
                  offset: 512
                  content:
                      - data: sbl1.mbn
                - name: foxy
                  fs-type: vfat
                  size: 1024M
                - name: system-boot # filesystem label
                  fs-type: vfat
                  size: 512M
                  content:
                      - uboot.env
                      - EFI/  # subdirs allowed
                - name: uboot
                  type: raw
                  content:
                      - data: u-boot.img
                  offset: 393216
                  offset-write: mbr+30
                - name: foo
                  type: raw
                  size: 12MB
                  content:
                      - data: one.img
                      - data: two.img # if no offset specified, goes immediately after preceding block
                        offset: 1234
                - name: bar
                  type: dump
                  content:
                      - data: foo.img
                  offset: foo+50
                -

        name-of-the-other-image:
            partitions:
                - name: writable
                  fs-type: ext4


Example: grub

Example: beaglebone
