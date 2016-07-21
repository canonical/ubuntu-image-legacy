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

qemu -bios OVMF.fd

<slangasek> the more recent, fancier way is cp /usr/share/OVMF/OVMF_VARS.fd
            /path/to/OVMF_VARS.fd; qemu -drive
            file=/usr/share/OVMF/OVMF_CODE.fd,if=pflash,format=raw,unit=0,readonly=on
            -drive file=/path/to/OVMF_VARS.fd,if=pflash,format=raw,unit=1

<slangasek> (which is what recent virt-manager will give you, and that way you
            have persistent nvram space for your VM)

<slangasek> btw it's annoying that the test suite will try to write output to
            the same file name as u-i itself when called without a -o argument
            ;)  [18:06]
