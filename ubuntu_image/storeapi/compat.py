try:  # pragma: no cover
    from builtins import open  # noqa
    from urllib.parse import quote_plus, urljoin
except ImportError:  # pragma: no cover
    from __builtin__ import open  # noqa
    from urllib import quote_plus  # noqa
    from urlparse import urljoin  # noqa
