==============
 ubuntu-image
==============

------------------------------
Generate a bootable disk image
------------------------------

:Author: Barry Warsaw <barry@ubuntu.com>
:Date: 2017-01-24
:Copyright: 2016-2017 Canonical Ltd.
:Version: 0.15
:Manual section: 1


SYNOPSIS
========

ubuntu-image [options] model.assertion


DESCRIPTION
===========

``ubuntu-image`` is a program for generating a variety of bootable disk
images.  Currently only snap_ based images are supported, but ``ubuntu-image``
is intended to support other use cases such as Ubuntu classic images.

Images are built from a *model assertion*, which is a YAML_ file describing a
particular combination of core, kernel, and gadget snaps, along with other
declarations, and signed with a digital signature asserting its authenticity.
The assets defined in the model assertion uniquely describe the device for
which the image is built.

As part of the model assertion, a `gadget snap`_ is specified.  The gadget
contains a `gadget.yaml`_ file which contains the exact description of the
disk image's contents, in YAML format.  The ``gadget.yaml`` file describes
such things as the names of all the volumes to be produced [#]_, the
structures [#]_ within the volume, whether the volume contains a bootloader
and if so what kind of bootloader, etc.


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

model_assertion
    Path to the model assertion file.  This positional argument must be given
    for this mode of operation.

-d, --debug
    Enable debugging output.

-o FILENAME, --output FILENAME
    The generated disk image file.  If not given, the image will be put in a
    file called ``disk.img`` in the working directory, in which case, you
    probably want to specify ``--workdir``.  If ``--workdir`` is not given,
    the image will be written to the current working directory.  **NOTE** when
    run as a snap, ``ubuntu-image`` refuses to write to ``/tmp`` since this
    directory is not accessible outside of the snap environment.

-O DIRECTORY, --output-dir DIRECTORY
    Write generated disk image files to this directory.  The files will be
    named after the ``gadget.yaml`` volume name, with ``.img`` suffix
    appended.  **NOTE** when run as a snap, this directory cannot be ``/tmp``.

--image-size SIZE
    The size of the generated disk image file (see ``--output``).  If this
    size is smaller than the minimum calculated size of the image, a warning
    will be issued and ``--image-size`` will be ignored.  The value is the
    size in bytes, with allowable suffixes 'M' for MiB and 'G' for GiB.


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

``ubuntu-image`` internally runs a state machine to create the disk image.
These are some options for controlling this state machine.  Other than
``--workdir``, these options are mutually exclusive.  When ``--until`` or
`--thru`` is given, the state machine can be resumed later with ``--resume``,
but ``--workdir`` must be given in that case since the state is saved in a
``.ubuntu-image.pck`` file in the working directory.

-w DIRECTORY, --workdir DIRECTORY
    The working directory in which to download and unpack all the source files
    for the image.  This directory can exist or not, and it is not removed
    after this program exits.  If not given, a temporary working directory is
    used instead, which *is* deleted after this program exits.  Use
    ``--workdir`` if you want to be able to resume a partial state machine
    run.

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


SEE ALSO
========

snap(1)


FOOTNOTES
=========

.. [#] Volumes are analogous to disk images, although ``ubuntu-image``
       currently only supports a single volume per ``gadget.yaml`` file.
.. [#] Structures define the layout of the volume, including partitions,
       Master Boot Records, or any other relevant content.


.. _snap: http://snapcraft.io/
.. _YAML: https://developer.ubuntu.com/en/snappy/guides/prepare-image/
.. _`gadget snap`: https://github.com/snapcore/snapd/wiki/Gadget-snap
.. _`gadget.yaml`: https://github.com/snapcore/snapd/wiki/Gadget-snap#gadget.yaml
