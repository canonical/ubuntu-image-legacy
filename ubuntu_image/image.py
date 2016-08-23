"""Classes for creating a bootable image."""

import os

from enum import Enum
from subprocess import PIPE, run
from tempfile import TemporaryDirectory
from ubuntu_image.parser import parse


__all__ = [
    'Diagnostics',
    'Image',
    ]


class Diagnostics(Enum):
    mbr = '--print-mbr'
    gpt = '--print'


class Image:
    def __init__(self, path, size):
        """Initialize an image file to a given size in bytes.

        :param path: Path to image file on the file system.
        :type path: str
        :param size: Size in bytes to set the image file to.
        :type size: int

        Public attributes:

        * path - Path to the image file.
        """
        self.path = path
        # Create an empty image file of a fixed size.  Unlike
        # truncate(1) --size 0, os.truncate(path, 0) doesn't touch the
        # file; i.e. it must already exist.
        with open(path, 'wb'):
            pass
        # Truncate to zero, so that extending the size in the next call
        # will cause all the bytes to read as zero.  Stevens $4.13
        os.truncate(path, 0)
        os.truncate(path, size)

    def copy_blob(self, blob_path, **dd_args):
        """Copy a blob to the image file.

        The copy is done using ``dd`` for consistency.  The keyword arguments
        are passed directly to the ``dd`` call.  See the dd(1) manpage for
        details.

        :param blob_path: File system path to the input file.
        :type blob_path: str
        """
        # Put together the dd command.
        args = ['dd', 'of={}'.format(self.path), 'if={}'.format(blob_path),
                'conv=sparse']
        for key, value in dd_args.items():
            args.append('{}={}'.format(key, value))
        # Run the command.  We'll capture stderr for logging purposes.
        #
        # TBD:
        # - check status of the returned CompletedProcess
        # - handle errors
        # - log stdout/stderr
        run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)

    def partition(self, **sgdisk_args):
        """Manipulate the GPT contained in the image file.

        The manipulation is done using ``sgdisk`` for consistency.  The
        device operated on is the image file represented by this
        instance.  The keyword arguments are passed directly to the
        ``sgdisk`` call (after tweaking to prefix the keys with ``--``
        for the command line switch syntax).  See the sgdisk(8) manpage
        for details.

        Underscores in argument keys will be changed to dashes.
        E.g. change_name='1:grub' becomes ``--change-name=1:grub``
        """
        # Put together the sgdisk command.
        args = ['sgdisk']
        for key, value in sgdisk_args.items():
            args.append('--{}={}'.format(key.replace('_', '-'), value))
        # End the command args with the image file.
        args.append(self.path)
        # Run the command.  We'll capture stderr for logging purposes.
        #
        # TBD:
        # - check status of the returned CompletedProcess
        # - handle errors
        # - log stdout/stderr
        run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)

    def diagnostics(self, which):
        """Return diagnostics string.

        :param which: An enum value describing which diagnostic to
            return.  Must be either Diagnostics.mbr or Diagnostics.gpt
        :type which: Diagnostics enum item.
        :return: Printed output from the chosen ``sgdisk`` command.
        :rtype: str
        """
        args = ('sgdisk', which.value, self.path)
        status = run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        # TBD:
        # - check status
        # - log stderr
        return status.stdout


def extract(snap_path):                             # pragma: nocover
    """Extract the gadget.yml file from a path to a .snap.

    :param snap_path: File system path to a .snap.
    :type snap_path: str
    :return: The dictionary represented by the meta/gadget.yaml file contained
        in the snap.
    :rtype: dict
    """
    with TemporaryDirectory() as destination:
        gadget_dir = os.path.join(destination, 'gadget')
        run(['unsquashfs', '-d', gadget_dir, snap_path],
            stderr=PIPE, stdout=PIPE)
        gadget_yaml = os.path.join(gadget_dir, 'meta', 'gadget.yaml')
        return parse(gadget_yaml)
