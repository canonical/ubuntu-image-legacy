==========
 Overview
==========

The ``image.yaml`` a new concept, added to Snappy in the series 16 release to
support standardized image building tooling for snappy.  The file is embedded
in the *gadget* snap. Unlike other YAML files it is *not* consumed by snappy.
Instead the file is read and processed by the image toolkit (ubuntu-image) to
produce a bootable image and supporting assets (e.g. recovery or installer
support).


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

The YAML file has the following keys:

partition-scheme
    Defines the type of supported partition tables. Legal values are ``MBR``
    and ``GPT``.

partitions
    Defines a list of partitions present that must be present, their
    properties and content. In general all of the content of the image is
    either pre-computed as a part of the gadget snap or must be assembled as a
    filesystem from the content provided by the gadget snap.

    Each partition is an object with the following properties:

    name
        (*optional*) Partition name. There's an implementation specific
        constraint on the maximum length.
    role
        Role of this partition in the image. Roles are specific to snappy. The
        currently defined roles are as follows:
            ESP
                (U)EFI System Partition.  VFAT filesystem; partition type
                EF (for MBR partition table),
                C12A7328-F81F-11D2-BA4B-00A0C93EC93B (for GPT partition
                table).  It is an error to specify guid, type, or fs-type
                values for partitions of this role.
            raw
                No filesystem.  Files will be written to raw block offsets
                within the partition.
                By default these partitions will have type DA ("Non-FS data")
                on MBR disks, and type 21686148-6449-6E6F-744E-656564454649
                ("BIOS Boot") on GPT.
            custom (default value)
                If a partition is needed which does not fit any of the above
                roles, use this role.  The fs-type field is required for
                partitions of this role.  By default, a custom partition is
                given type 83 ("Linux") on MBR, and type
                0FC63DAF-8483-4772-8E79-3D69D8477DE4 on GPT.
    guid
        Optional override of the GPT partition type identifier.  If
        partition-scheme is MBR, this value is ignored.
    type
        Optional override of the MBR partition type identifier, given as a
        two-digit hex code.  If partition-scheme is GPT, this value is
        ignored.
    offset
        Optional partition offset from the beginning of the image. Offset can
        be used to tweak the position of the first partition.
    size
        Optional size of the partition.  If not specified, will be
        automatically computed based on the size of contents, the partition
        role, and any limits imposed by offsets specified for partitions
        located after this one on the disk.
    content
        Optional partition content. This must be a relative path to a file or
        directory in the gadget snap. The path is used to either fetch a
        pre-made content (path to a file) or to combine pre-made content as a
        filesystem (path to a directory).
    fs-type
        Type of the filesystem to use. This can be only ``ext4`` or ``vfat``.


Example
=======

::

    partition-scheme: gpt
    partitions:
     - role: raw
       offset: 2M
       size: 1M
       content: assets/grub/core.img
    ...
