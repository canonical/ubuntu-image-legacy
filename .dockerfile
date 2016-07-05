# Give us a minimal Xenial test environment.

FROM ubuntu:xenial
MAINTAINER foundations https://github.com/CanonicalLtd/ubuntu-image
RUN apt-get update && apt-get dist-upgrade -y

# Get the basic packages we need to clone the repo and calculate the build
# dependencies.
RUN apt-get install -y git devscripts equivs

# Grab the origin/master branch as a baseline.
RUN git clone --depth=50 https://github.com/CanonicalLtd/ubuntu-image.git /root/code

# Install the build dependencies.  mk-build-deps(1) doesn't tell you that
# "install -f" are default options. :/
RUN cd /root/code && mk-build-deps --install --tool '/usr/bin/apt-get -y'

# For some unknown reason, in Travis, not everything gets installed by
# mk-build-deps even though in a local Xenial schroot, they do. :(
RUN apt-get install -y tox
