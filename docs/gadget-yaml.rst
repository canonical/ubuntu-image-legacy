The new "gadget.yaml":

platform: msm8916-mtp # possibly needed for dtb names to copy into uboot partition; kill for now?
bootloader: u-boot         # or grub; this tells snapd whether to create grubenv or uboot.env
volumes:                      # each volume is a distinct disk image
    name-of-the-image:   # XXX: figure out size limit if we want to write this somewhere (MBR, GPT?)
         - name: sbl1
           type: DEA0BA2C-CBDD-4805-B4F9-F428251C3E98 #
           offset: 512
           data: sbl1.mbn
        - name: foxy
           type: vfat
           size: 1024M
         - name: system-boot # filesystem label
           type: vfat
           size: 512M
           content:
               - uboot.env
               - EFI/  # subdirs allowed
         - name: uboot
           type: raw
           data: u-boot.img
           offset: 393216
           offset-write: mbr+30
        - name: foo
          type: raw
          size: 12MB
          content:
              - data: one.img
              - data: two.img # if no offset specified, goes immediately after preceding block
                offset: 1234
        - name: bar
          type: dump
          data: foo.img
          offset: foo+50
       -

    name-of-the-other-image:
         - name: writable
           label: writable
           type: ext4


Example: grub

Example: beaglebone
