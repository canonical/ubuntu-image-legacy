export UBUNTU_IMAGE_CODENAME=`lsb_release -cs`

tox -e coverage
