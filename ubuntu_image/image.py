"""Classes for creating a bootable image."""

import os
import parted

from enum import Enum
from math import ceil
from struct import pack
from ubuntu_image.helpers import run
from ubuntu_image.parser import VolumeSchema


__all__ = [
    'Diagnostics',
    'Image',
    ]


class Diagnostics(Enum):
    mbr = '--print-mbr'
    gpt = '--print'


COMMASPACE = ', '


class Image:
    def __init__(self, path, size, schema=None):
        """Initialize an image file to a given size in bytes.

        :param path: Path to image file on the file system.
        :type path: str
        :param size: Size in bytes to set the image file to.
        :type size: int
        :param schema: The partitioning schema of the volume.
        :type schema: VolumeSchema

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
        # Prepare the device and disk objects for parted to be used for all
        # future partition() calls.  Only do it if we actually care about the
        # partition table.
        if schema:
            self.device = parted.Device(self.path)
            label = 'msdos' if schema is VolumeSchema.mbr else 'gpt'
            self.schema = schema
            self.disk = parted.freshDisk(self.device, label)
            self.sector_size = self.device.sectorSize
        else:
            self.sector_size = 512

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

    def partition(self, offset, size, name=None, is_bootable=False):
        """Add a new partition in the image file.

        The newly added partition will be appended to the existing partition
        table on the image as defined by the volume schema.  This is all done
        by pyparted.  Please note that libparted has no means of changing the
        partition type GUID directly (this can only be done by setting
        partition flags) so this has to be done separately after *all*
        partitions have been added.
        Also, the commit() operation also clobbers the hybrid MBR in GPT labels
        so be sure to first perform partitioning and only afterwards attempting
        copy operations.

        :param offset: Offset (start position) of the partition in bytes.
        :type offset: int
        :param size: Size of partition in bytes.
        :type size: int
        :param name: Name of the partition.
        :type name: str
        :param is_bootable: Toggle if the bootable flag should be set.
        :type name: bool

        """
        # When defining geometries for our partitions we can't use the pyparted
        # parted.sizeToSectors() function as it actually rounds down the sizes
        # instead of rounding up, which means you might end up not having
        # enough sectors for a partition's contents (LP: #1661298).
        geometry = parted.Geometry(
            device=self.device,
            start=ceil(offset / self.sector_size),
            length=ceil(size / self.sector_size))
        partition = parted.Partition(
            disk=self.disk,
            type=parted.PARTITION_NORMAL,
            geometry=geometry)
        # Force an exact geometry constraint as otherwise libparted tries to be
        # too smart and changes our geometry itself.
        constraint = parted.Constraint(
            exactGeom=geometry)
        self.disk.addPartition(partition, constraint)
        # Sadly the current pyparted bindings do not export a setter for the
        # name of a partition (LP: #1661297).  To work-around this we need to
        # reach out to the internal PedPartition object of the partition to
        # call the set_name() function.
        # We also follow the same guideline as before - for mbr labels we just
        # ignore the name as it's not supported.
        if name and self.schema is not VolumeSchema.mbr:
            partition._Partition__partition.set_name(name)
        if is_bootable:
            partition.setFlag(parted.PARTITION_BOOT)
        # Save all the partition changes so far to disk.
        self.disk.commit()

    def set_parition_type(self, partnum, typecode):
        """Set the partition type for selected partition.

        Since libparted is unable to provide this functionality, we use sfdisk
        to be able to set arbitrary type identifiers.  Please note that this
        method needs to be only used after all partition() operations have been
        performed.  Any disk.commit() operation resets the type GUIDs to
        defaults.

        """
        if isinstance(typecode, tuple):
            if self.schema is VolumeSchema.gpt:
                typecode = typecode[1]
            else:
                typecode = typecode[0]
        run(['sfdisk', '--part-type', self.path,
             str(partnum), str(typecode)])

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

    def sector(self, value):
        """Helper function that converts sectors to bytes for the device.
        """
        return value * self.sector_size
