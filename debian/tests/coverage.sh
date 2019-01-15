#!/bin/sh

export UBUNTU_IMAGE_CODENAME=`lsb_release -cs`

# Xenial is special; all the others are share a configuration.

if [ "$UBUNTU_IMAGE_CODENAME" != 'xenial' ]
then
    export UBUNTU_IMAGE_CODENAME="devel"
fi

tox -e py35-cov,py36-cov,py37-cov
