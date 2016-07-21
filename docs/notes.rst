Building
========

$ TMPDIR=$(pwd)/grab-output ./ubuntu-image -k -c edge -d \
      amd64-generic-model.assertion -o disk.img

the -k option will save the temp directory containing the output of snap
weld.

$ mkdir -p input-dir
$ mv grab-output/tmp*/root input-dir/root
$ mv grab-output/tmp*/boot/* input-dir/root/boot
$ unsquashfs -d input-dir/unpack canonical-pc_3.2_all.snap
$ cp canonical-pc_3.2_all.snap input-dir/unpack

This gives you an input-dir containing simulated output of 'snap weld'.

Using <https://github.com/CanonicalLtd/ubuntu-image/tree/sideload>, you can
then call 'ubuntu-image-finalize':

$ ./ubuntu-image-finalize -i input-dir -c edge -d \
	amd64-generic-model.assertion -o disk.img


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


That will let you boot as far as GRUB - it won't boot to userspace, because
of the aforementioned problem with root filesystem layout.

Booting a VM with SecureBoot requires more work again - basically, getting
an OVMF_VARS.fd with the right data inside.  We have a TODO this cycle to
produce a prefab SB-enabled VARS image that can be passed around, so people
don't have to do a bunch of manual setup work on each VM.  This doesn't
matter yet for snappy or u-i though, since we don't currently have a
SB-signed grub that supports snappy (LP: #1604499).


<slangasek> btw it's annoying that the test suite will try to write output to
            the same file name as u-i itself when called without a -o argument
            ;)  [18:06]
