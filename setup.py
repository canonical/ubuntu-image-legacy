#!/usr/bin/env python3

from debian.changelog import Changelog
from setup_helpers import require_python
from setuptools import setup


require_python(0x30500f0)

with open('debian/changelog', encoding='utf-8') as fp:
    __version__ = str(Changelog(fp).get_version())


setup(
    name='ubuntu-image',
    version=__version__,
    description='Construct snappy images out of a model assertion',
    author_email='snapcraft@lists.ubuntu.com',
    url='https://github.com/CanonicalLtd/ubuntu-image',
    packages=['ubuntu_image', 'ubuntu_image.storeapi'],
    scripts=['ubuntu-image'],
    install_requires=[
        'progressbar',
        'requests',
        'requests-oauthlib',
        'requests-toolbelt',
        'ssoclient',
        ],
    entry_points={
        'flake8.extension': ['B40 = ubuntu_image.testing.flake8:ImportOrder'],
        },
    license='GPLv3',
    classifiers=(
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Topic :: Software Development :: Build Tools',
        'Topic :: System :: Software Distribution',
        ),
    )
