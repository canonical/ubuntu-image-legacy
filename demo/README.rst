==================
 Demo gadget snap
==================

When support was added for gadget.yaml files containing `multiple volumes`_
there weren't any blessed gadget snaps containing such definitions.  In order
to complete the testing of this feature we needed to create a custom gadget
snap that demonstrated this feature.   Since that process involves multiple
steps, the code for that is contained in this directory.

In order to reproduce the stack of bits to flex multiple volumes, we need to
do a few things:

* Create a gadget snap with the multi-volume gadget.yaml
* Create a model assertion containing the gadget snap
* Sign the model assertion

To make things simpler, we'll reuse the pc-amd64 model as much as possible,
along with the pc-kernel kernel snap.

**NOTE**: If you need to reproduce this, you will have to edit the model.json
to include your authority-id and brand-id, since these are tied to Barry
Warsaw's developers key.  The best place to start is with the `image building
tutorial`_ which explains how to create a key and how to produce a signed
model assertion file.

You'll also want to consult the `board enablement documentation`_ which
explains how to create the gadget snap.


Create the gadget snap
======================

The first step is to create the gadget snap which contains the multi-volume
gadget.yaml.  From the directory containing this README and a directory called
``gadget``, run the following command::

    $ snapcraft snap gadget

This will leave you with a ``pc-multivolume_16.04-0.8_amd64.snap`` file in the
current directory.  This is your gadget snap.


Create and sign the model assertion
===================================

Now you need to create and sign the model assertion, which is the input file
for ``ubuntu-image`` and which is used during the autopkgtest.  Here's where
you need to know your authority-id and brand-id, and have created and uploaded
a snap key.  This means you'll have to edit the ``model.json`` file in the
current directory.

To create the model assertion, run the following command from the same
directory::

    $ cat model.json | snap sign > model.assertion

That uses your default signing key.


Test build the image
====================

Now let's build a test image with the newly minted model.assertion.  We'll put
the artifacts in a temporary directory.

    $ cd ..
    $ mkdir /tmp/images
    $ ./ubuntu-image -O /tmp/images -c stable --extra-snaps demo/pc-multivolume_16.04-0.8_amd64.snap -d demo/model.assertion

You should now have three ``.img`` files in ``/tmp/images``::

    % ls /tmp/images
    hello.img  pc.img  world.img

The ``pc.img`` file is the boot image and doesn't really contain anything
different than the normal ``pc-amd64`` gadget.  The other two will contain
some special contents, and demonstrate the multi-volume support.  Let's check
their contents::

    $ mkdir /tmp/images/mnt

    $ sudo kpartx -avs /tmp/images/hello.img
    add map loop3p1 (253:1): 0 2048 linear 7:3 2048
    $ sudo mount /dev/mapper/loop3p1 /tmp/images/mnt
    $ cat /tmp/images/mnt/hello.txt
    HELLO!
    $ sudo umount /tmp/images/mnt
    $ sudo kpartx -dvs /tmp/images/hello.img

    $ sudo kpartx -avs /tmp/images/world.img
    add map loop4p1 (253:1): 0 2048 linear 7:3 2048
    $ sudo mount /dev/mapper/loop4p1 /tmp/images/mnt
    $ cat /tmp/images/mnt/world.txt
    WORLD!
    $ sudo umount /tmp/images/mnt
    $ sudo kpartx -dvs /tmp/images/world.img


**NOTE**: The actual devmapper loopback mount points may differ, so adjust
accordingly.


Update the tests
================

Assuming you've seen everything you were supposed to see, you know now that
your custom gadget snap and model assertions are ready to be integrated into
the autopkgtests.  Move them into place::

    $ mv demo/model.assertion debian/tests/models/multivol.assertion
    $ mv demo/pc-multivolume_16.04-0.8_amd64.snap debian/tests/snaps

And now you can run the ubuntu-image multivol autopkgtest as normal.


.. _`multiple volumes`: https://bugs.launchpad.net/ubuntu-image/+bug/1641727
.. _`image building tutorial: https://tutorials.ubuntu.com/tutorial/create-your-own-core-image#0
.. _`board enablement documentation`: https://docs.ubuntu.com/core/en/guides/build-device/board-enablement#the-gadget-snap
