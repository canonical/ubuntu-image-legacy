Building
========

This is a another test.


$ ./ubuntu-image -w ../workdir -c edge -d -u load_gadget_yaml \
  amd64-generic-mode.assertion

$ pushd ..
$ bzr branch lp:~vorlon/snappy-hub/snappy-systems
$ rm -r workdir/unpack/gadget
$ cp -a snappy-systems/generic-amd64 workdir/unpack/gadget

$ popd
$ ./ubuntu-image -w ../workdir -d --resume


Mounting
========

Since the current image only supports UEFI, you need to tell qemu to use
UEFI instead of BIOS.

I do this by managing all my VMs with virt-manager.  You can launch qemu
directly using UEFI by:

  $ sudo apt install ovmf
  $ cp /usr/share/OVMF/OVMF_VARS.fd /path/to/OVMF_VARS.fd
  $ qemu-system-x86_64 \
    -drive file=/usr/share/OVMF/OVMF_CODE.fd,if=pflash,format=raw,unit=0,readonly=on \
    -drive file=/path/to/OVMF_VARS.fd,if=pflash,format=raw,unit=1 \
    disk.img


That should let you boot the snappy system to userspace.

Booting a VM with SecureBoot requires more work again - basically, getting
an OVMF_VARS.fd with the right data inside.  We have a TODO this cycle to
produce a prefab SB-enabled VARS image that can be passed around, so people
don't have to do a bunch of manual setup work on each VM.  This doesn't
matter yet for snappy or u-i though, since we don't currently have a
SB-signed grub that supports snappy (LP: #1604499).


<slangasek> btw it's annoying that the test suite will try to write output to
            the same file name as u-i itself when called without a -o argument
            ;)  [18:06]
