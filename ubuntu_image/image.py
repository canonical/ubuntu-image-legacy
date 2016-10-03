"""Classes for creating a bootable image."""

import os

from enum import Enum
from struct import pack
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import run
from ubuntu_image.parser import parse


__all__ = [
    'Diagnostics',
    'Image',
    ]


class Diagnostics(Enum):
    mbr = '--print-mbr'
    gpt = '--print'


COMMASPACE = ', '


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
        run(args)

    def partition(self, partnum, **sgdisk_args):
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
        for key, value in sorted(sgdisk_args.items(),
                                 key=lambda x: '' if x[0] == 'new' else x[0]):
            # special case of gpt vs. mbr type codes
            if key == 'typecode' and isinstance(value, tuple):
                value = value[1]
            args.append('--{}={}:{}'
                        .format(key.replace('_', '-'), partnum, value))
        # End the command args with the image file.
        args.append(self.path)
        # Run the command.  We'll capture stderr for logging purposes.
        #
        # TBD:
        # - check status of the returned CompletedProcess
        # - handle errors
        # - log stdout/stderr
        run(args)

    def diagnostics(self, which):
        """Return diagnostics string.

        :param which: An enum value describing which diagnostic to
            return.  Must be either Diagnostics.mbr or Diagnostics.gpt
        :type which: Diagnostics enum item.
        :return: Printed output from the chosen ``sgdisk`` command.
        :rtype: str
        """
        status = run(['sgdisk', which.value, self.path])
        # TBD:
        # - check status
        # - log stderr
        return status.stdout

    def write_value_at_offset(self, value, offset):
        """Write the given value to the specified absolute offset.

        The value is interpreted as a 32-bit integer, and is written out
        in little-endian format.

        :param value: A value to be written to disk; max 32-bits in size.
        :type value: int
        :param offset: The offset in bytes into the image where the value
            should be written.
        :type size: int
        """
        # We do not want to allow writing past the end of the file to silently
        # extend it, but because we open the file in + mode, a seek past the
        # end of the file plus the write *will* silently extend it.  LBYL, but
        # don't forget we start at zero!  And don't forget that we're writing
        # 4 bytes so we can't seek to a position >= size + 4.
        if os.path.getsize(self.path) - 4 < offset:
            raise ValueError('write offset beyond end of file')
        binary_value = pack('<I', value)
        with open(self.path, 'rb+') as fp:
            fp.seek(offset)
            fp.write(binary_value)


class MBRImage(Image):
    def __init__(self, path, size):
        """Create an MBR image.

        sfdisk needs different options for new disks vs. existing
        partition tables, so cope with that here.
        """
        super().__init__(path, size)
        self.initialized = False

    def partition(self, partnum, **sfdisk_args):
        """Manipulate the MBR contained in the image file.

        The manipulation is done using ``sfdisk`` for consistency.  The
        device operated on is the image file represented by this
        instance.  The keyword arguments are given in ``sgdisk`` format,
        so are parsed for handing off to ``sfdisk`` instead.
        """
        # Put together the sfdisk command.
        args = ['sfdisk', self.path]
        if self.initialized:
            args.append('--append')
        self.initialized = True
        command_input = []
        for key, value in sfdisk_args.items():
            if key == 'new':
                offset, size = value.split(':')
                command_input.extend([
                    'start={}'.format(offset),
                    'size={}'.format(size),
                    ])
            elif key == 'activate':
                command_input.append('bootable')
            elif key == 'typecode':
                if isinstance(value, tuple):
                    value = value[0]
                command_input.append('type={}'.format(value))
            else:
                raise ValueError('{} option not supported for MBR partitions'
                                 .format(key))
        input_arg = 'part{}: {}'.format(
            partnum, COMMASPACE.join(command_input))
        # Run the command.  We'll capture stderr for logging purposes.
        #
        # TBD:
        # - check status of the returned CompletedProcess
        # - handle errors
        # - log stdout/stderr
        run(args, input=input_arg)


def extract(snap_path):
    """Extract the gadget.yml file from a path to a .snap.

    :param snap_path: File system path to a .snap.
    :type snap_path: str
    :return: The dictionary represented by the meta/gadget.yaml file contained
        in the snap.
    :rtype: dict
    """
    with TemporaryDirectory() as destination:
        gadget_dir = os.path.join(destination, 'gadget')
        run(['/usr/bin/unsquashfs', '-d', gadget_dir, snap_path])
        gadget_yaml = os.path.join(gadget_dir, 'meta', 'gadget.yaml')
        return parse(gadget_yaml)
