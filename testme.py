import os
import sys
from ubuntu_image.image import parse

r = parse(os.path.normpath(os.path.expanduser(sys.argv[1])))
