"""Testing helpers."""

import os
import shutil
import logging

from contextlib import ExitStack
from hashlib import sha256
from pkg_resources import resource_filename
from tempfile import TemporaryDirectory
from ubuntu_image.builder import ModelAssertionBuilder
from ubuntu_image.helpers import as_bool, run as real_run, snap as real_snap
from unittest.mock import patch
from zipfile import ZipFile


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


# Create a mock for the `sudo snap prepare-image` command.  This is an
# expensive command which hits the actual snap store.  We want this to run at
# least once so we know our tests are valid.  We can cache the results in a
# test-suite-wide temporary directory and simulate future calls by just
# recursively copying the contents to the specified directories.
#
# It's a bit more complicated than that though, because it's possible that the
# channel and model.assertion will be different, so we need to make the cache
# dependent on those values.
#
# Finally, to enable full end-to-end tests, check an environment variable to
# see if the mocking should even be done.  This way, we can make our Travis-CI
# job do at least one real end-to-end test.

def mock_run(command, *, check=True, **args):
    # In the test suite, we have to mock out the run() call to do two things.
    # First, it must not print progress to stdout/stderr since this clutters
    # up the test output.  Since the default is to capture these, it's enough
    # to just remove any keyword arguments from args.
    #
    # Second, it must set UBUNTU_IMAGE_SKIP_COPY_UNVERIFIED_MODEL so that we
    # can use our test data model.assertion, which obviously isn't signed.
    args.pop('stdout', None)
    args.pop('stderr', None)
    env = args.setdefault('env', os.environ)
    env['UBUNTU_IMAGE_SKIP_COPY_UNVERIFIED_MODEL'] = '1'
    real_run(command, check=check, **args)


class MockerBase:
    def __init__(self, tmpdir):
        self._tmpdir = tmpdir
        self.patcher = patch('ubuntu_image.builder.snap', self.snap_mock)

    def snap_mock(self, model_assertion, root_dir,
                  channel=None, extra_snaps=None):
        raise NotImplementedError

    def _checksum(self, model_assertion, channel):
        # Hash the contents of the model.assertion file + the channel name and
        # use that in the cache directory name.  This is more accurate than
        # using the model.assertion basename.
        with open(model_assertion, 'rb') as fp:
            checksum = sha256(fp.read())
        checksum.update(
            ('default' if channel is None else channel).encode('utf-8'))
        return checksum.hexdigest()

    def __enter__(self):
        self.patcher.start()
        return self

    def __exit__(self, *args):
        self.patcher.stop()
        return False


class SecondAndOnwardMock(MockerBase):
    def snap_mock(self, model_assertion, root_dir,
                  channel=None, extra_snaps=None):
        run_tmp = os.path.join(
            self._tmpdir,
            self._checksum(model_assertion, channel))
        tmp_root = os.path.join(run_tmp, 'root')
        if not os.path.isdir(run_tmp):
            os.makedirs(tmp_root)
            with patch('ubuntu_image.helpers.run', mock_run):
                real_snap(model_assertion, tmp_root, channel)
        # copytree() requires that the destination directories do not exist.
        # Since this code only ever executes during the test suite, and even
        # though only when mocking `snap` for speed, this is always safe.
        shutil.rmtree(root_dir, ignore_errors=True)
        shutil.copytree(tmp_root, root_dir)


class AlwaysMock(MockerBase):
    def snap_mock(self, model_assertion, root_dir,
                  channel=None, extra_snaps=None):
        zipfile = resource_filename(
            'ubuntu_image.tests.data',
            '{}.zip'.format(self._checksum(model_assertion, channel)))
        with ZipFile(zipfile, 'r') as zf:
            zf.extractall(root_dir)


def start_test_run(plugin):
    """[flufl.testing]start_run hook."""
    plugin.resources = ExitStack()
    # How should we mock `snap prepare-image`?  If set to 'always' (case
    # insensitive), then use the sample data in the .zip file.  Any other
    # truthy value says to use a second-and-onward mock.
    should_we_mock = os.environ.get('UBUNTU_IMAGE_MOCK_SNAP', 'yes')
    if should_we_mock.lower() == 'always':
        mock_class = AlwaysMock
    elif as_bool(should_we_mock):
        mock_class = SecondAndOnwardMock
    else:
        mock_class = None
    if mock_class is not None:
        tmpdir = plugin.resources.enter_context(TemporaryDirectory())
        # Record the actual snap mocker on the class so that other tests
        # can temporarily disable it.  Some tests need to run the actual
        # snap() helper function.
        plugin.__class__.snap_mocker = plugin.resources.enter_context(
            mock_class(tmpdir))
