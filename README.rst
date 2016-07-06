======================
 Ubuntu image builder
======================

This tool is used to build Ubuntu images.  Currently it only builds Snappy
images from a model assertion, but it will be generalized to build more
(eventually all) Ubuntu images.


Requirements
============

Ubuntu 16.04 (Xenial Xerus) is the minimum platform requirement.  Python 3.5
is the minimum Python version required.  All required third party packages are
available in the Ubuntu archive.

If you want to run the test suite locally, you should install all the build
dependencies named in the `debian/control` file.  The easiest way to do that
is to `apt install devscripts equivs` and then run::

    $ sudo mk-build-deps --remove --install --tool '/usr/bin/apt-get -y'

from the directory containing the `debian` subdirectory.  Alternatively of
course, you can just install the packages named in the `Build-Depends` field.

The test suite will prefer system installed libraries when available instead
of PyPI downloaded libraries, however the following test dependencies will be
downloaded from PyPI on demand, since they aren't yet available in the Ubuntu
archive:

* flake8-respect-noqa

Do **not** use `progressbar <https://pypi.python.org/pypi/progressbar>`__ from
PyPI because of this `upstream open bug`_.  Just ``sudo apt install
python3-progressbar`` instead.


License
=======

``ubuntu-image`` is licensed under the terms of the GPLv3 and Copyright by
Canonical Ltd.

``ubuntu_image/testing/flake8.py`` and ``ubuntu_image/testing/nose.py`` are
copyright Barry Warsaw and licensed under the terms of the Apache License,
2.0.


Project details
===============

* Project home: https://github.com/CanonicalLtd/ubuntu-image
* Report bugs at: https://bugs.launchpad.net/ubuntu-image
* Git clone: https://github.com/CanonicalLtd/ubuntu-image.git
* Documentation: TBD


Developing
==========

You'll need the `tox <https://pypi.python.org/pypi/tox>`__ tool to run the
test suite (see above for testing requirements).  You can run the full test
suite, including coverage and code quality tests via::

    $ tox

You can run individual tests like this::

    $ tox -e py35 -- -P <pattern>

where *<pattern>* is a Python regular expression matching a test name, e.g.::

    $ tox -e py35 -- -P test_smoke


.. _`upstream open bug`: https://github.com/niltonvolpato/python-progressbar/issues/42
