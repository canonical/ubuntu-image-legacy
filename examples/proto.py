#!/usr/bin/python3

from ubuntu_image.image import Diagnostics, GiB, Image

# Create empty image of a fixed size
# TODO: compute rough good size after seeing all the required snaps.

image = Image('img', GiB(4))

# Install GRUB to MBR
# TODO: this has to be represented in the image.yaml
# NOTE: the boot.img has to be a part of the gadget snap itself
# FIXME: embed a pointer to 2nd stage in bios-boot partition
image.copy_blob('blogs/img.mbr', bs=446, count=1, conv='notrunc')

# Create BIOS boot partition
#
# The partition is 1MiB in size, as recommended by various partitioning guides.
# The actual required size is much, much smaller.
#
# https://www.gnu.org/software/grub/manual/html_node/BIOS-installation.html#BIOS-installation
image.partition(new='1:4MiB:+1MiB')
image.partition(typecode='1:21686148-6449-6E6F-744E-656564454649')
image.partition(change_name='1:grub')
image.copy_blob('blobs/img.bios-boot',
                bs='1MiB', seek=4, count=1, conv='notrunc')

# Create EFI system partition
#
# TODO: switch to 512MiB as recommended by the standard
image.partition(new='2:5MiB:+64MiB')
image.partition(typecode='2:C12A7328-F81F-11D2-BA4B-00A0C93EC93B')
image.partition(change_name='2:system-boot')
image.copy_blob('blobs/img.system-boot',
                bs='1MB', seek=4, count=64, conv='notrunc')

# Create main snappy writable partition
image.partition(new='3:72MiB:+3646MiB')
image.partition(typecode='3:0FC63DAF-8483-4772-8E79-3D69D8477DE4')
image.partition(change_name='3:writable')
image.copy_blob('blobs/img.writable',
                bs='1MiB', seek=72, count=3646, conv='notrunc')

# TODO: the partition needs to be populated with skeleton directory layout
# TODO: the partition needs to have all the snaps copied to a
# firstboot-specific location
# TODO: (assertions and side infos)

# Show what we have
print(image.diagnostics(Diagnostics.mbr))
print(image.diagnostics(Diagnostics.gpt))
