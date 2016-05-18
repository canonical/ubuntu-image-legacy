import sys
import locale
import gettext
import argparse

_ = gettext.gettext


# Allow the test framework to override sys.argv.
def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]                         # pragma: nocover
    locale.setlocale(locale.LC_ALL, '')
    parser = argparse.ArgumentParser(
        prog='ubuntu-image', add_help=True,
        description=_(
            'Build bootable Snappy Ubuntu image from a model assertion.'),
        epilog=_(
            """Strategy can be used to alter partition layouts.
            Try --strategy=? for a list of available choices."""))
    parser.add_argument(
        'model', metavar=_('MODEL-ASSERTION'),
        help=_('model assertion file to use'))
    parser.add_argument(
        '--strategy', help=_('Use this alternate layout strategy'))
    args = parser.parse_args(argv)
    # Stub out execution.
    print(args)                                     # pragma: nocover
    return 0                                        # pragma: nocover


if __name__ == '__main__':                          # pragma: nocover
    sys.exit(main())
