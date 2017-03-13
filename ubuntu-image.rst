==============
 ubuntu-image
==============

------------------------------
Generate a bootable disk image
------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2017-03-13
:Copyright: 2016-2017 Canonical Ltd.
:Version: 1.0
:Manual section: 1


SYNOPSIS
========

ubuntu-image [options] model.assertion


DESCRIPTION
===========

``ubuntu-image`` is a program for generating a variety of bootable disk
images.  Currently only snap_ based images are supported, but in the future,
``ubuntu-image`` will support other use cases such as building Ubuntu classic
images.

Images are built from a *model assertion*, which is a YAML_ file describing a
particular combination of core, kernel, and gadget snaps, along with other
declarations, signed with a digital signature asserting its authenticity.  The
assets defined in the model assertion uniquely describe the device for which
the image is built.

As part of the model assertion, a `gadget snap`_ is specified.  The gadget
contains a `gadget.yaml`_ file which contains the exact description of the
disk image's contents, in YAML format.  The ``gadget.yaml`` file describes
such things as the names of all the volumes to be produced [#]_, the
structures [#]_ within the volume, whether the volume contains a bootloader
and if so what kind of bootloader, etc.

Note that ``ubuntu-image`` communicates with the snap store using the ``snap
prepare-image`` subcommand.  The model assertion file is passed to ``snap
prepare-image`` which handles downloading the appropriate gadget and any extra
snaps.  See that command's documentation for additional details.


OPTIONS
=======

-h, --help
    Show the program's message and exit.

--version
    Show the program's version number and exit.


Common options
--------------

There are two general operational modes to ``ubuntu-image``.  The usual mode
is to run the script giving the required model assertion file as a required
positional argument, generating a disk image file.  These options are useful
in this mode of operation.

The second mode of operation is provided for debugging and testing purposes.
It allows you to run the internal state machine step by step, and is described
in more detail below.

model_assertion
    Path to the model assertion file.  This positional argument must be given
    for this mode of operation.

-d, --debug
    Enable debugging output.

-O DIRECTORY, --output-dir DIRECTORY
    Write generated disk image files to this directory.  The files will be
    named after the ``gadget.yaml`` volume names, with ``.img`` suffix
    appended.  If not given, the current working directory is used.  This
    option replaces, and cannot be used with, the deprecated ``--output``
    option.

-o FILENAME, --output FILENAME
    **DEPRECATED** (Use ``--output-dir`` instead.)  The generated disk image
    file.  If not given, the image will be put in a file called ``disk.img``
    in the working directory, in which case, you probably want to specify
    ``--workdir``.  If ``--workdir`` is not given, the image will be written
    to the current working directory.

-i SIZE, --image-size SIZE
    The size of the generated disk image files.  If this size is smaller than
    the minimum calculated size of the volume, a warning will be issued and
    ``--image-size`` will be ignored.  The value is the size in bytes, with
    allowable suffixes 'M' for MiB and 'G' for GiB.

    An extended syntax is supported for gadget.yaml files which specify
    multiple volumes (i.e. disk images).  In that case, a single ``SIZE``
    argument will be used for all the defined volumes, with the same rules for
    ignoring values which are too small.  You can specify the image size for a
    single volume using an indexing prefix on the ``SIZE`` parameter, where
    the index is either a volume name or an integer index starting at zero.
    For example, to set the image size only on the second volume, which might
    be called ``sdcard`` in the gadget.yaml, you could use: ``--image-size
    1:8G`` since the 1-th index names the second volume (volumes are
    0-indexed).  Or you could use ``--image-size sdcard:8G``.

    You can also specify multiple volume sizes by separating them with commas,
    and you can mix and match integer indexes and volume name indexes.  Thus,
    if the gadget.yaml named three volumes, and you wanted to set all three to
    different sizes, you could use ``--image-size 0:2G,sdcard:8G,eMMC:4G``.

    In the case of ambiguities, the size hint is ignored and the calculated
    size for the volume will be used instead.

--image-file-list FILENAME
    Print to ``FILENAME``, a list of the file system paths to all the disk
    images created by the command, if any.


Image content options
---------------------

These are some additional options for defining the contents of snap-based
images.

--extra-snaps EXTRA_SNAPS
    Extra snaps to install. This is passed through to ``snap prepare-image``.

--cloud-init USER-DATA-FILE
    ``cloud-config`` data to be copied to the image.

-c CHANNEL, --channel CHANNEL
    The snap channel to use.


State machine options
---------------------

.. caution:: The options described here are primarily for debugging and
   testing purposes and should not be considered part of the stable, public
   API.  State machine step numbers and names can change between releases.

``ubuntu-image`` internally runs a state machine to create the disk image.
These are some options for controlling this state machine.  Other than
``--workdir``, these options are mutually exclusive.  When ``--until`` or
``--thru`` is given, the state machine can be resumed later with ``--resume``,
but ``--workdir`` must be given in that case since the state is saved in a
``.ubuntu-image.pck`` file in the working directory.

-w DIRECTORY, --workdir DIRECTORY
    The working directory in which to download and unpack all the source files
    for the image.  This directory can exist or not, and it is not removed
    after this program exits.  If not given, a temporary working directory is
    used instead, which *is* deleted after this program exits.  Use
    ``--workdir`` if you want to be able to resume a partial state machine
    run.  As an added bonus, the ``gadget.yaml`` file is copied to the working
    directory after it's downloaded.

-u STEP, --until STEP
    Run the state machine until the given ``STEP``, non-inclusively.  ``STEP``
    can be the name of a state machine method, or a number indicating the
    ordinal of the step.

-t STEP, --thru STEP
    Run the state machine through the given ``STEP``, inclusively.  ``STEP``
    can be the name of a state machine method, or a number indicating the
    ordinal of the step.

-r, --resume
    Continue the state machine from the previously saved state.  It is an
    error if there is no previous state.


FILES
=====

gadget.yaml
    https://github.com/snapcore/snapd/wiki/Gadget-snap#gadget.yaml

model assertion
    https://developer.ubuntu.com/en/snappy/guides/prepare-image/

cloud-config
    https://help.ubuntu.com/community/CloudInit


ENVIRONMENT
===========

The following environment variables are recognized by ``ubuntu-image``.

``UBUNTU_IMAGE_SNAP_CMD``
    ``ubuntu-image`` calls ``snap prepare-image`` to communicate with the
    store, download the gadget, and unpack its contents.  Normally for the
    ``ubuntu-image`` deb, whatever ``snap`` command is first on your ``$PATH``
    is used, while for the classic snap, the bundled ``snap`` command is used.
    Set this environment variable to specify an alternative ``snap`` command
    which ``prepare-image`` is called on.

``UBUNTU_IMAGE_PRESERVE_UNPACK``
    When set, this names a directory for preserving a pristine copy of the
    unpacked gadget contents.  The directory must exist, and an ``unpack``
    directory will be created under this directory.  The full contents of the
    ``<workdir>/unpack`` directory after the ``snap prepare-image`` subcommand
    has run will be copied here.

There are a few other environment variables used for building and testing
only.


SEE ALSO
========

snap(1)


FOOTNOTES
=========

.. [#] Volumes are roughly analogous to disk images.
.. [#] Structures define the layout of the volume, including partitions,
       Master Boot Records, or any other relevant content.


.. _snap: http://snapcraft.io/
.. _YAML: https://developer.ubuntu.com/en/snappy/guides/prepare-image/
.. _`gadget snap`: https://github.com/snapcore/snapd/wiki/Gadget-snap
.. _`gadget.yaml`: https://github.com/snapcore/snapd/wiki/Gadget-snap#gadget.yaml
