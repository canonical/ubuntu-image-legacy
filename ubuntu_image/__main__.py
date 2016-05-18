import argparse
import gettext
import locale

_ = gettext.gettext


def main():
    locale.setlocale(locale.LC_ALL, '')
    parser = argparse.ArgumentParser(
        prog='ubuntu-image', add_help=True,
        description=_(
            "Build bootable Snappy Ubuntu image from a model assertion."),
        epilog=_(
            "Strategy can be used to alter partition layouts. "
            "Try --strategy=? for a list of available choices."))
    parser.add_argument(
        'model', metavar=_('MODEL-ASSERTION'),
        help=_("model assertion file to use"))
    parser.add_argument(
        '--strategy', help=_("Use this alternate layout strategy"))
    ns = parser.parse_args()
    print(ns)
    raise NotImplementedError('this is just a stub')


if __name__ == '__main__':
    main()
