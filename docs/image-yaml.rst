Overview
========

The `image.yaml` a new concept, added to Snappy in the series 16 release to
support standardized image building tooling for snappy.  The file is embedded
in the *gadget* snap. Unlike other yaml files it is *not* consumed by snappy.
Instead the file is read and processed by the image toolkit (ubuntu-image) to
produce a bootable image and supporting assets (e.g. recovery or installer
support).

Design
======

The design of ubuntu-image is based on earlier lessons from
`linaro-media-create`, linaro *hardware packs* and `ubuntu-device-flash`. The
tool has the following goals and assumptions in place:

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
- Some tasks are delegated to a support tool generated from snappy codebase (or
  perhaps just snap CLI itself). The tool will have a stable interface (input,
  output and expected behavior) and should shield ubuntu-image from ongoing
  system design evolution.
- There is a strong preference for user-space code over kernel code. We had
  many issues caused by leftover loopback devices and kpartx errors. While it
  may appear that those issues are no longer affecting the most recent versions
  of the kernel it is our belief that this task can be accomplished with no
  kernel support.


Draft Specification
===================

The YAML file has the following keys:

partition-scheme
----------------

Defines the type of supported partition tables. Legal values are MBR and GPT.

partitions
----------

Defines a list of partitions present that must be present, their properties and
content. In general all of the content of the image is either pre-computed as a
part of the gadget snap or must be assembled as a filesystem from the content
provided by the gadget snap.

Each partition is an object with the following properties:

name
^^^^

Partition name. There's an implementation specific constraint on the maximum
length. This field is optional.

role
^^^^
Role of this partition in the image. Roles are specific to snappy. The roles are
as follows. (TBD)

guid
^^^^

GPT partition type identifier. Necessary for bootloaders to correctly identify
and support booting of the snappy system.

offset
^^^^^^
Optional partition offset from the beginning of the image. Offset can be used
to tweak the position of the first partition. 

size
^^^^

Size of the partition. This can be a fixed quantity (such as 1M) or an
automatically computed guesstimate, based on content size. Size of the writable
snappy partition can be as small as possible, it is expanded on first boot.

content
^^^^^^^

Optional partition content. This must be a relative path to a file or directory
in the gadget snap. The path is used to either fetch a pre-made content (path to a file)
or to combine pre-made content as a filesystem (path to a directory).

fs-type
^^^^^^^

Type of the filesystem to use. This can be only *ext4* or *vfat*.

Exapmle
=======

::

    partition-scheme: gpt
    partitions:
     - role: bios-boot
       guid: 21686148-6449-6E6F-744E-656564454649
       offset: 2M
       size: 1M
       content: assets/grub/core.img
    ...
