import os

from pkg_resources import resource_string as resource_bytes


# Try to get the version number, which will be different if we're living in a
# snap world or a deb.  Actually, I'd prefer to not even have the -NubuntuY
# version string when we're running from source, but that's trickier, so don't
# worry about it.
__version__ = os.environ.get('SNAP_VERSION')
if __version__ is None:                                      # pragma: nocover
    try:
        __version__ = resource_bytes(
            'ubuntu_image', 'version.txt').decode('utf-8')
    except FileNotFoundError:
        # Probably, setup.py hasn't been run yet to generate the version.txt.
        __version__ = 'dev'
