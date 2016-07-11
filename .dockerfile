# Give us a minimal Xenial test environment.

FROM ubuntu:xenial
MAINTAINER foundations https://github.com/CanonicalLtd/ubuntu-image
RUN apt-get update && apt-get dist-upgrade -y

# Get the basic packages we need to clone the repo and calculate the build
# dependencies.
RUN apt-get install -y git devscripts equivs software-properties-common

# For backport of Yakkety's e2fsprogs.
RUN add-apt-repository --yes ppa:canonical-foundations/ubuntu-image
RUN apt-get update && apt-get dist-upgrade -y

# Grab the origin/master branch as a baseline.
RUN git clone --depth=50 https://github.com/CanonicalLtd/ubuntu-image.git /root/code
