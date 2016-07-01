# Give us a minimal Xenial test environment.

FROM ubuntu:xenial
MAINTAINER foundations https://github.com/CanonicalLtd/ubuntu-image
RUN apt-get update && apt-get dist-upgrade -y

# We need tox to run the test suite, python3-debian to process the setup.py,
# and python3-progressbar because the PyPI version isn't usable inside virtual
# environments.
RUN apt-get install -y python3-debian python3-progressbar \
                       python3-guacamole python3-xdg python3-ssoclient \
                       python3-requests python3-requests-oauthlib \
                       python3-requests-toolbelt \
                       tox git gdisk

# Grab the branch.
RUN git clone https://github.com/CanonicalLtd/ubuntu-image.git /root/code
RUN cd /root/code && git checkout $TRAVIS_BRANCH
