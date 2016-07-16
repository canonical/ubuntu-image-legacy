from io import StringIO
from ubuntu_image._unstable import load_rfc822_records


__all__ = ('Assertion', 'ModelAssertion')


class Assertion:
    """Assertion is a fact encoded in a text file.

    Assertions are used heavily in snappy. The format of an assertion is
    similar to RFC822 but they are not meant to be read or written by humans
    and they contain a cryptographic signature.
    """

    def __init__(self, headers, body=None):
        """Initialize an assertion with the following data (headers)."""
        self.headers = headers
        self.body = body

    @classmethod
    def from_string(cls, text):
        """Load assertion from a string."""
        # XXX: This is a temporary stop-gap. The proper way to do this is to
        # invoke yet-unimplemented go executable that reads an assertion on
        # stdin, validates it and outputs the same assertion as JSON on stdout.
        (fields, signature) = text.rsplit('\n\n', 1)
        records = load_rfc822_records(StringIO(fields))
        if len(records) != 1:
            raise ValueError('Expected exactly one assertion')
        headers = records[0].data
        body = None  # XXX: body is not required here
        return cls(headers, body)


class Header:
    """Descriptor for accessing assertion headers conveniently."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return 'Header({!a})'.format(self.name)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.headers[self.name]


class ModelAssertion(Assertion):
    """Model assertion describes a class of devices sharing the model name.

    The assertion contains, among other things, the identifier of the store
    and of the three key snaps (core, kernel, gadget) that have to be
    installed.
    """
    type = Header('type')
    authority_id = Header('authority-id')
    series = Header('series')
    brand_id = Header('brand-id')
    os = Header('os')
    architecture = Header('architecture')
    kernel = Header('kernel')
    gadget = Header('gadget')
    required_snaps = Header('required-snaps')
