# Copyright (C) 2016 Barry Warsaw
#
# This project is licensed under the terms of the Apache 2.0 License.

"""nose2 test infrastructure."""

import os
import re
import shutil
import doctest

from contextlib import ExitStack
from hashlib import sha256
from nose2.events import Plugin
from pkg_resources import resource_filename
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import as_bool, run as real_run, snap as real_snap
from unittest.mock import patch
from zipfile import ZipFile


FLAGS = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE | doctest.REPORT_NDIFF
TOPDIR = os.path.dirname(resource_filename('ubuntu_image', '__init__.py'))


def setup(testobj):
    """Global doctest setup."""


def teardown(testobj):
    """Global doctest teardown."""


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
    env = args.setdefault('env', {})
    env['UBUNTU_IMAGE_SKIP_COPY_UNVERIFIED_MODEL'] = '1'
    real_run(command, check=check, **args)


class MockerBase:
    def __init__(self, tmpdir):
        self._tmpdir = tmpdir
        self._patcher = patch('ubuntu_image.builder.snap', self.snap_mock)

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
        self._patcher.start()

    def __exit__(self, *args):
        self._patcher.stop()
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


class NosePlugin(Plugin):
    configSection = 'ubuntu-image'

    def __init__(self):
        super().__init__()
        self.patterns = []
        self.addArgument(self.patterns, 'P', 'pattern',
                         'Add a test matching pattern')

    def getTestCaseNames(self, event):
        if len(self.patterns) == 0:
            # No filter patterns, so everything should be tested.
            return
        # Does the pattern match the fully qualified class name?
        for pattern in self.patterns:
            full_class_name = '{}.{}'.format(
                event.testCase.__module__, event.testCase.__name__)
            if re.search(pattern, full_class_name):
                # Don't suppress this test class.
                return
        names = filter(event.isTestMethod, dir(event.testCase))
        for name in names:
            full_test_name = '{}.{}.{}'.format(
                event.testCase.__module__,
                event.testCase.__name__,
                name)
            for pattern in self.patterns:
                if re.search(pattern, full_test_name):
                    break
            else:
                event.excludedNames.append(name)

    def handleFile(self, event):
        path = event.path[len(TOPDIR)+1:]
        if len(self.patterns) > 0:
            for pattern in self.patterns:
                if re.search(pattern, path):
                    break
            else:
                # Skip this doctest.
                return
        base, ext = os.path.splitext(path)
        if ext != '.rst':
            return
        test = doctest.DocFileTest(
            path, package='ubuntu_image',
            optionflags=FLAGS,
            setUp=setup,
            tearDown=teardown)
        # Suppress the extra "Doctest: ..." line.
        test.shortDescription = lambda: None
        event.extraTests.append(test)

    def startTestRun(self, event):
        # Create a mock for the `sudo snap prepare-image` command.  This is an
        # expensive command which hits the actual snap store.  We want this to
        # run at least once so we know our tests are valid.  We can cache the
        # results in a test-suite-wide temporary directory and simulate future
        # calls by just recursively copying the contents to the specified
        # directories.
        #
        # It's a bit more complicated than that though, because it's possible
        # that the channel and model.assertion will be different, so we need
        # to make the cache dependent on those values.
        #
        # Finally, to enable full end-to-end tests, check an environment
        # variable to see if the mocking should even be done.  This way, we
        # can make our Travis-CI job do at least one real end-to-end test.
        self.resources = ExitStack()
        # How should we mock `snap prepare-image`?  If set to 'always' (case
        # insensitive), then use the sample data in the .zip file.  Any other
        # truthy value says to use a second-and-onward mock.
        should_we_mock = os.environ.get('UBUNTUIMAGE_MOCK_SNAP', 'yes')
        if should_we_mock.lower() == 'always':
            mock_class = AlwaysMock
        elif as_bool(should_we_mock):
            mock_class = SecondAndOnwardMock
        else:
            mock_class = None
        if mock_class is not None:
            tmpdir = self.resources.enter_context(TemporaryDirectory())
            self.resources.enter_context(mock_class(tmpdir))

    def stopTestRun(self, event):
        self.resources.close()

    # def startTest(self, event):
    #     import sys; print('vvvvv', event.test, file=sys.stderr)

    # def stopTest(self, event):
    #     import sys; print('^^^^^', event.test, file=sys.stderr)
