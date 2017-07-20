[ -z "$UPSTREAM_PULL_REQUEST" ] && ( echo "Skipping test, not ran as part of a pull request."; exit 0; )

sudo snap install core

snapcraft
snapfile=`find . -maxdepth 1 -name \*.snap`

sudo snap install $snapfile --classic --dangerous

here=`pwd`
cd $ADTTMP
mkdir clean
cd clean

dpkg --status ubuntu-image || echo "ubuntu-image is missing; as expected"

ubuntu-image --version
ubuntu-image -d -O $ADTTMP $here/debian/tests/models/pc-amd64-model.assertion
ls -l $ADTTMP/pc.img
