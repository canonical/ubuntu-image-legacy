"""Testing helpers."""

import os
import shutil

from pkg_resources import resource_filename
from ubuntu_image.builder import ModelAssertionBuilder


IN_TRAVIS = 'IN_TRAVIS' in os.environ


class XXXModelAssertionBuilder(ModelAssertionBuilder):
    image_yaml = 'image.yaml'

    # We need this class because the current gadget snap we get from the store
    # does not contain an image.yaml or grub files, although it (probably)
    # will eventually.  For now, this copies sample files into the expected
    # case, and should be used in tests which require that step.
    def load_gadget_yaml(self):
        gadget_dir = os.path.join(self.unpackdir, 'gadget')
        meta_dir = os.path.join(gadget_dir, 'meta')
        os.makedirs(meta_dir, exist_ok=True)
        shutil.copy(
            resource_filename('ubuntu_image.tests.data', 'image.yaml'),
            os.path.join(meta_dir, self.image_yaml))
        shutil.copy(
            resource_filename('ubuntu_image.tests.data', 'grubx64.efi'),
            os.path.join(gadget_dir, 'grubx64.efi'))
        shutil.copy(
            resource_filename('ubuntu_image.tests.data', 'shim.efi.signed'),
            os.path.join(gadget_dir, 'shim.efi.signed'))
        super().load_gadget_yaml()


class CrashingModelAssertionBuilder(XXXModelAssertionBuilder):
    def make_temporary_directories(self):
        raise RuntimeError


class EarlyExitModelAssertionBuilder(XXXModelAssertionBuilder):
    def prepare_image(self):
        # Do nothing, but let the state machine exit.
        pass


class DoNothingBuilder(XXXModelAssertionBuilder):
    def prepare_image(self):
        self._next.append(self.load_gadget_yaml)

    def populate_rootfs_contents(self):
        self._next.append(self.calculate_rootfs_size)

    def populate_bootfs_contents(self):
        self._next.append(self.calculate_bootfs_size)


class EarlyExitLeaveATraceAssertionBuilder(XXXModelAssertionBuilder):
    def prepare_image(self):
        # Similar to above, but leave a trace that this method ran, so that we
        # have something to positively test.
        with open(os.path.join(self.workdir, 'success'), 'w'):
            pass
