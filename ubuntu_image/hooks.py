"""A general hook mechanism.

This module defines a HookManager that will run all the executable scripts
found in the passed-in hooks directory(s) for defined hook execution points.

Each supported hook trigger can pass different values through the overlay_env
argument, which will be made visible in the hook scripts as environment
variables."""

import os
import logging

from ubuntu_image.helpers import run
from ubuntu_image.state import ExpectedError


_logger = logging.getLogger('ubuntu-image')


# List of hooks currently provided by ubuntu-image.
# This list will be used by our test infrastructure to make sure we're
# supporting all hooks.  The test_hook_official_support unit test checks if
# all the listed hooks are correctly fired during image build time.
supported_hooks = [
    'post-populate-rootfs',
    ]


class HookError(ExpectedError):
    """Exception raised whenever a hook script returns a non-zero value."""
    def __init__(self, hook_name, hook_path, hook_retcode, hook_stderr):
        self.hook_name = hook_name
        self.hook_path = hook_path
        self.hook_retcode = hook_retcode
        self.hook_stderr = hook_stderr


class HookManager:
    def __init__(self, dirs=[]):
        self._hook_dirs = [os.path.abspath(
            os.path.expanduser(x)) for x in dirs]

    def _run_hook(self, name, path, env):
        _logger.debug('Running hook script at path {} for hook named '
                      '{}.'.format(path, name))
        proc = run(path, check=False, env=env)
        # We handle the error separately as we want to raise our own exception.
        if proc.returncode != 0:
            raise HookError(name, path, proc.returncode, proc.stderr)

    def fire(self, name, overlay_env={}):
        """Method called to run a specified hook."""
        env = os.environ.copy()
        env.update(overlay_env)
        name_d = '{}.d'.format(name)
        for hook_dir in self._hook_dirs:
            # Hook scripts can be either present in the hook directory as
            # single hook-named files or in a hook-name.d directory.
            # We go and execute all of them in the order directory > file.
            abspath = os.path.join(hook_dir, name_d)
            if os.path.isdir(abspath):
                for hook in sorted(os.listdir(abspath)):
                    abspath_d = os.path.join(name, abspath, hook)
                    self._run_hook(name, abspath_d, env)
            abspath = os.path.join(hook_dir, name)
            if os.path.isfile(abspath):
                self._run_hook(name, abspath, env)
