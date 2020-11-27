#!/bin/sh

export UBUNTU_IMAGE_CODENAME=`lsb_release -cs`

# Normally we want to attempt running the tests for all envs, but currently
# in focal we support both 3.7 and 3.8 while pyparted is built and available
# only against 3.8.  So we skip py37 for it.

ENVLIST="py35-cov,py36-cov,py37-cov,py38-cov,py39-cov"

if [ "$UBUNTU_IMAGE_CODENAME" = 'focal' ]
then
    ENVLIST="py35-cov,py36-cov,py38-cov,py39-cov"
fi

# Xenial is special; all the others are share a configuration.

if [ "$UBUNTU_IMAGE_CODENAME" != 'xenial' ]
then
    export UBUNTU_IMAGE_CODENAME="devel"
fi

tox -e $ENVLIST
