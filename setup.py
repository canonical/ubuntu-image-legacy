#!/usr/bin/env python3
from setuptools import setup

setup(
    name='ubuntu-image',
    version='0.1',
    description='construct snappy images out of a model assertion',
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
    tests_require=[
        'responses',
    ],
    test_suite='ubuntu_image',
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
