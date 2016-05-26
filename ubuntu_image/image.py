"""Classes for creating a bootable image."""

import os

from subprocess import PIPE, run


__all__ = [
    'GiB',
    'Image',
    ]


def GiB(count):
    return count * 2**30


def MiB(count):
    return count * 2**20


class Image:
    def __init__(self, path, size):
        """Initialize an image file to a given size in bytes.

        :param path: Path to image file on the file system.
        :type path: str
        :param size: Size in bytes to set the image file to.
        :type size: int

        Public attributes:

        * path       - Path to the image file.
        """
        self.path = path
        # Create an empty image file of a fixed size.  Unlike
        # truncate(1) --size 0, os.truncate(path, 0) doesn't touch the
        # file; i.e. it must already exist.
        with open(path, 'wb'):
            pass
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
        args = ['dd', 'of={}'.format(self.path), 'if={}'.format(blob_path)]
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
        """
        # Put together the sgdisk command.
        args = ['sgdisk']
        for key, value in sgdisk_args:
            args.append('--{}={}'.format(key, value))
        # End the command args with the image file.
        args.append(self.path)
        # Run the command.  We'll capture stderr for logging purposes.
        #
        # TBD:
        # - check status of the returned CompletedProcess
        # - handle errors
        # - log stdout/stderr
        run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)

    def diagnostics_mbr(self):
        args = ('sgdisk', '--print-mbr', self.path)
        status = run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        # TBD:
        # - check status
        # - log stderr
        return status.stdout

    def diagnostics_gpt(self):
        args = ('sgdisk', '--print', self.path)
        status = run(args, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        # TBD:
        # - check status
        # - log stderr
        return status.stdout
