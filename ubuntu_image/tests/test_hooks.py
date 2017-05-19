"""Test the hook mechanism."""

import os

from contextlib import ExitStack
from tempfile import TemporaryDirectory
from ubuntu_image.hooks import HookError, HookManager
from unittest import TestCase


class TestHooks(TestCase):
    def test_hook_compatibility(self):
        # This test should be updated whenever NEW hooks are added.  It is NOT
        # allowed to remove any hooks from this test - it's present here to
        # make sure no existing hooks have been
        pass

    def test_hook_fired(self):
        with ExitStack() as resources:
            hooksdir = resources.enter_context(TemporaryDirectory())
            hookfile = os.path.join(hooksdir, 'test-hook')
            resultfile = os.path.join(hooksdir, 'result')
            env = {'UBUNTU_IMAGE_TEST_ENV': 'true'}
            with open(hookfile, 'w') as fp:
                fp.write("""\
#!/bin/sh
echo -n "$UBUNTU_IMAGE_TEST_ENV" >>{}
""".format(resultfile))
            os.chmod(hookfile, 0o744)
            manager = HookManager([hooksdir])
            manager.fire('test-hook', env)
            # Check if the script ran once as expected.
            self.assertTrue(os.path.exists(resultfile))
            with open(resultfile, 'r') as fp:
                self.assertEqual(fp.read(), 'true')

    def test_hook_fired_multiple_scripts(self):
        with ExitStack() as resources:
            hooksdir = resources.enter_context(TemporaryDirectory())
            hookdir = os.path.join(hooksdir, 'test-hook.d')
            hookfile1 = os.path.join(hookdir, 'dir-test-01')
            hookfile2 = os.path.join(hookdir, 'dir-test-02')
            hookfile3 = os.path.join(hooksdir, 'test-hook')
            resultfile = os.path.join(hooksdir, 'result')
            os.mkdir(hookdir)

            def create_hook(path):
                with open(path, 'w') as fp:
                    fp.write("""\
#!/bin/sh
echo "{}" >>{}
""".format(path, resultfile))
                os.chmod(path, 0o744)
            create_hook(hookfile1)
            create_hook(hookfile2)
            create_hook(hookfile3)
            manager = HookManager([hooksdir])
            manager.fire('test-hook')
            # Check if all the scripts for the hook were run and in the right
            # order.
            self.assertTrue(os.path.exists(resultfile))
            with open(resultfile, 'r') as fp:
                lines = fp.read().splitlines()
                self.assertListEqual(
                    lines, [hookfile1, hookfile2, hookfile3])

    def test_hook_multiple_directories(self):
        with ExitStack() as resources:
            hooksdir1 = resources.enter_context(TemporaryDirectory())
            hooksdir2 = resources.enter_context(TemporaryDirectory())
            hookdir = os.path.join(hooksdir1, 'test-hook.d')
            hookfile1 = os.path.join(hookdir, 'dir-test-01')
            hookfile2 = os.path.join(hooksdir2, 'test-hook')
            # We write the results to one file to check if order is proper.
            resultfile = os.path.join(hooksdir1, 'result')
            os.mkdir(hookdir)

            def create_hook(path):
                with open(path, 'w') as fp:
                    fp.write("""\
#!/bin/sh
echo "{}" >>{}
""".format(path, resultfile))
                os.chmod(path, 0o744)
            create_hook(hookfile1)
            create_hook(hookfile2)
            manager = HookManager([hooksdir1, hooksdir2])
            manager.fire('test-hook')
            # Check if all the scripts for the hook were run and in the right
            # order.
            self.assertTrue(os.path.exists(resultfile))
            with open(resultfile, 'r') as fp:
                lines = fp.read().splitlines()
                self.assertListEqual(
                    lines, [hookfile1, hookfile2])

    def test_hook_error(self):
        with ExitStack() as resources:
            hooksdir = resources.enter_context(TemporaryDirectory())
            hookfile = os.path.join(hooksdir, 'test-hook')
            with open(hookfile, 'w') as fp:
                fp.write("""\
#!/bin/sh
echo -n "error" 1>&2
exit 1
""")
            os.chmod(hookfile, 0o744)
            manager = HookManager([hooksdir])
            # Check if hook script failures are properly reported
            with self.assertRaises(HookError) as cm:
                manager.fire('test-hook')
            self.assertEqual(cm.exception.hook_name, 'test-hook')
            self.assertEqual(cm.exception.hook_path, hookfile)
            self.assertEqual(cm.exception.hook_retcode, 1)
            self.assertEqual(cm.exception.hook_stderr, 'error')
