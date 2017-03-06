========================
 echo-service boot test
========================

The autopkgtests include a boot test, which creates a bootable amd64 image
with an extra snap.  This extra snap implements a simple "echo service" daemon
which starts on image boot, listening on localhost:8888, which returns
whatever bytes are sent to it.

The test boots this image under QEMU, forwarding the VM's port 8888 to the
autopkgtest process.  Then the test connects to port 8888 and sends it a
string.  If the string is returned, the test succeeds.

Usually you won't have to interfere with this since the echo service snap is
included in this repository in ``debian/tests``, but sometimes you might have
to modify or rebuild this echo service snap.  Here's how to do that.


Create the snap
===============

In this directory, just run ``snapcraft``::

    $ snapcraft

After all is said and done, you should now have a ``echo-service*.snap`` file
along with a bunch of snapcraft artifact directories.  Move the snap to the
repo's top-level ``debian/tests/snaps`` directory and then clean up::

    $ mv echo-service_<version>_amd64.snap ../../debian/tests/snaps/
    $ snapcraft clean

Be sure to ``git add`` the new ``.snap`` and ``git rm`` the old ``.snap``.

**VERY IMPORTANT**: Be sure to call that ``snapcraft clean`` command.  If you
don't you'll get a ton of extra cruft in your source package, if it even
builds.
