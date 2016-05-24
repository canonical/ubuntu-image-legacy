# Give us a minimal Xenial test environment.

FROM ubuntu:xenial
MAINTAINER foundations https://github.com/CanonicalLtd/ubuntu-image
RUN apt-get update && apt-get dist-upgrade -y

# We need tox to run the test suite, python3-debian to process the setup.py,
# and python3-progressbar because the PyPI version isn't usable inside virtual
# environments.
RUN apt-get install -y python3-debian python3-progressbar tox
