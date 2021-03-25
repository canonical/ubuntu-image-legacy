#!/bin/sh

export UBUNTU_IMAGE_CODENAME=`lsb_release -cs`

# Normally we want to attempt running the tests for all envs, but currently
# in focal we support both 3.7 and 3.8 while pyparted is built and available
# only against 3.8.  So we skip py37 for it.

ENVLIST="py35-nocov,py36-nocov,py37-nocov,py38-nocov,py39-nocov"
if [ "$UBUNTU_IMAGE_CODENAME" = 'focal' ]
then
    ENVLIST="py35-nocov,py36-nocov,py38-nocov,py39-nocov"
fi

tox -e $ENVLIST
