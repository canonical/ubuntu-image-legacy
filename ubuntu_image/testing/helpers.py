"""Testing helpers."""

import os
import shutil
import logging

from contextlib import ExitStack, contextmanager
from pkg_resources import resource_filename
from subprocess import PIPE, run as subprocess_run
from types import SimpleNamespace
from ubuntu_image.assertion_builder import ModelAssertionBuilder
from ubuntu_image.classic_builder import ClassicBuilder
from unittest.mock import patch


DIRS_UNDER_ROOTFS = ['bin', 'boot', 'dev', 'etc', 'home', 'lib',
                     'lib64', 'media', 'initrd.img', 'mnt', 'opt',
                     'proc', 'root', 'run', 'sbin', 'snap', 'srv',
                     'sys', 'tmp', 'usr', 'var', 'vmlinuz']


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
        self.yaml_file_path = os.path.join(meta_dir, 'gadget.yaml')
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


class XXXClassicBuilder(ClassicBuilder):
    pass


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
        self._next.append(self.populate_rootfs_contents_hooks)

    def populate_bootfs_contents(self):
        self._next.append(self.prepare_filesystems)


class EarlyExitLeaveATraceAssertionBuilder(XXXModelAssertionBuilder):
    def prepare_image(self):
        # Similar to above, but leave a trace that this method ran, so that we
        # have something to positively test.
        with open(os.path.join(self.workdir, 'success'), 'w'):
            pass


class DummyPrepareAssertionBuilder(XXXModelAssertionBuilder):
    def prepare_image(self):
        # Similar to above, but actually proceed with the build further.
        prepare_path = os.path.join(self.unpackdir, 'image')
        os.makedirs(prepare_path)
        # Touch a few files so that later steps have anything to copy.
        with open(os.path.join(prepare_path, 'file1'), 'w'):
            pass
        with open(os.path.join(prepare_path, 'file2'), 'w'):
            pass
        self._next.append(self.load_gadget_yaml)


class EarlyExitLeaveATraceClassicBuilder(XXXClassicBuilder):
    def prepare_gadget_tree(self):
        # We're skipping the gadget tree build as we're leaving early and will
        # not use it for the tests.
        self._next.append(self.prepare_image)

    def prepare_image(self):
        # Similar to above, but leave a trace that this method ran, so that we
        # have something to positively test.
        with open(os.path.join(self.workdir, 'success'), 'w'):
            pass


class CallLBLeaveATraceClassicBuilder(XXXClassicBuilder):
    def prepare_gadget_tree(self):
        # We're skipping the gadget tree build as we're leaving early and will
        # not use it for the tests.
        self._next.append(self.prepare_image)

    def load_gadget_yaml(self):
        # This time we want to call prepare_image for the live-build call but
        # then finish after leaving a trace
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


class LiveBuildMocker:
    def __init__(self, root_dir):
        self.call_args_list = []
        self.root_dir = root_dir

    def run(self, command, *args, **kws):
        cmd_str = command if isinstance(command, str) else ' '.join(command)
        if 'lb config' in cmd_str:
            self.call_args_list.append(command)
            return SimpleNamespace(returncode=1)
        elif 'lb build' in cmd_str:
            self.call_args_list.append(command)
            # Create dummy top-level filesystem layout.
            chroot_dir = os.path.join(self.root_dir, 'chroot')
            for dir_name in DIRS_UNDER_ROOTFS:
                os.makedirs(os.path.join(chroot_dir, dir_name))
            return SimpleNamespace(returncode=1)
        elif cmd_str.startswith('dpkg -L'):
            self.call_args_list.append(command)
            stdout = kws.pop('stdout', PIPE)
            stderr = kws.pop('stderr', PIPE)
            return subprocess_run(
                command,
                stdout=stdout, stderr=stderr,
                universal_newlines=True,
                **kws)
        elif cmd_str.startswith('dpkg --print-architecture'):
            self.call_args_list.append(command)
            return SimpleNamespace(stdout='amd64', returncode=0)


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
