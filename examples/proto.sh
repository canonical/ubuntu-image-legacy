#!/bin/sh
set -x
set -e
# Create empty image of a fixed size
# TODO: compute rough good size after seeing all the required snaps.
truncate --size=0 img
truncate --size=4GiB img

# Install GRUB to MBR
# TODO: this has to be represented in the image.yaml
# NOTE: the boot.img has to be a part of the gadget snap itself
# FIXME: embed a pointer to 2nd stage in bios-boot partition
dd if=blobs/img.mbr of=img bs=446 count=1 conv=notrunc

# Create BIOS boot partition
#
# The partition is 1MiB in size, as recommended by various partitioning guides.
# The actual required size is much, much smaller.
#
# https://www.gnu.org/software/grub/manual/html_node/BIOS-installation.html#BIOS-installation
sgdisk --new=1:4MiB:+1MiB img
sgdisk --typecode=1:21686148-6449-6E6F-744E-656564454649 img
sgdisk --change-name=1:grub img
dd if=blobs/img.bios-boot of=img bs=1MiB seek=4 count=1 conv=notrunc

# Create EFI system partition
#
# TODO: switch to 512MiB as recommended by the standard
sgdisk --new=2:5MiB:+64MiB img
sgdisk --typecode=2:C12A7328-F81F-11D2-BA4B-00A0C93EC93B img
sgdisk --change-name=2:system-boot img
dd if=blobs/img.system-boot conv=notrunc of=img bs=1MB seek=4 count=64

# Create main snappy writable partition
sgdisk --new=3:72MiB:+3646MiB img
sgdisk --typecode=3:0FC63DAF-8483-4772-8E79-3D69D8477DE4 img
sgdisk --change-name=3:writable img
dd if=blobs/img.writable of=img bs=1MiB seek=72 count=3646 conv=notrunc

# TODO: the partition needs to be populated with skeleton directory layout
# TODO: the partition needs to have all the snaps copied to a firstboot-specific
# location
# TODO: (assertions and side infos)

# Show what we have
sgdisk --print-mbr img
sgdisk --print img
