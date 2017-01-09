"""Testing helpers."""

import os
import shutil
import logging

from contextlib import ExitStack, contextmanager
from pkg_resources import resource_filename
from ubuntu_image.builder import ModelAssertionBuilder
from unittest.mock import patch


class XXXModelAssertionBuilder(ModelAssertionBuilder):
    exitcode = 0
    gadget_yaml = 'gadget.yaml'

    # We need this class because the current gadget snap we get from the store
    # does not contain a gadget.yaml or grub files, although it (probably)
    # will eventually.  For now, this copies sample files into the expected
    # case, and should be used in tests which require that step.
    def load_gadget_yaml(self):
        gadget_dir = os.path.join(self.unpackdir, 'gadget')
        meta_dir = os.path.join(gadget_dir, 'meta')
        os.makedirs(meta_dir, exist_ok=True)
        shutil.copy(
            resource_filename('ubuntu_image.tests.data', self.gadget_yaml),
            os.path.join(meta_dir, 'gadget.yaml'))
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


class LogCapture:
    def __init__(self):
        self.logs = []
        self._resources = ExitStack()

    def capture(self, *args, **kws):
        level, fmt, fmt_args = args
        self.logs.append((level, fmt % fmt_args))
        # Was .exception() called?
        exc_info = kws.pop('exc_info', None)
        assert len(kws) == 0, kws
        if exc_info:
            self.logs.append('IMAGINE THE TRACEBACK HERE')

    def __enter__(self):
        log = logging.getLogger('ubuntu-image')
        self._resources.enter_context(patch.object(log, '_log', self.capture))
        return self

    def __exit__(self, *exception):
        self._resources.close()
        # Don't suppress any exceptions.
        return False


@contextmanager
def envar(key, value):
    missing = object()
    # Temporarily set an environment variable.
    old_value = os.environ.get(key, missing)
    os.environ[key] = value
    try:
        yield
    finally:
        if old_value is missing:
            del os.environ[key]
        else:
            os.environ[key] = old_value
