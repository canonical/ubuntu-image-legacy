"""
This module contains unstable APIs for things that will be delegated to other
tools later. While we will do our best not to break those APIs when the
implementation changes, this is not guaranteed.
"""

import os
import re
import enum
import gettext
import logging
import textwrap
import functools


_ = gettext.gettext

_logger = logging.getLogger("ubuntu-image")


def normalize_rfc822_value(value):
    # Remove the multi-line dot marker
    value = re.sub('^(\s*)\.$', '\\1', value, flags=re.M)
    # Remove consistent indentation
    value = textwrap.dedent(value)
    # Strip the remaining whitespace
    value = value.strip()
    return value


class OriginMode(enum.Enum):

    """Possible "modes" an :class:`Origin` can operate in."""

    whole_file = 'whole-file'
    single_line = 'single-line'
    line_range = 'line-range'


@functools.total_ordering
class Origin:

    """
    Simple class for tracking where something came from.

    This class supports "pinpointing" something in a block of text. The block
    is described by the source attribute. The actual range is described by
    line_start (inclusive) and line_end (exclusive).

    :attribute source:
        Something that describes where the text came from.

    :attribute line_start:
        The number of the line where the record begins. This can be None
        when the intent is to cover the whole file. This can also be equal
        to line_end (when not None) if the intent is to show a single line.

    :attribute line_end:
        The number of the line where the record ends
    """

    __slots__ = ['source', 'line_start', 'line_end']

    def __init__(self, source, line_start=None, line_end=None):
        self.source = source
        self.line_start = line_start
        self.line_end = line_end

    def mode(self):
        """
        Compute the "mode" of this origin instance.

        :returns:
            :attr:`OriginMode.whole_file`, :attr:`OriginMode.single_line`
            or :attr:`OriginMode.line_range`.

        The mode tells if this instance is describing the whole file,
        a range of lines or just a single line. It is mostly used internally
        by the implementation.
        """
        if self.line_start is None and self.line_end is None:
            return OriginMode.whole_file
        elif self.line_start == self.line_end:
            return OriginMode.single_line
        else:
            return OriginMode.line_range

    def __repr__(self):
        return "<{} source:{!r} line_start:{} line_end:{}>".format(
            self.__class__.__name__,
            self.source, self.line_start, self.line_end)

    def __str__(self):
        mode = self.mode()
        if mode is OriginMode.whole_file:
            return str(self.source)
        elif mode is OriginMode.single_line:
            return "{}:{}".format(self.source, self.line_start)
        elif mode is OriginMode.line_range:
            return "{}:{}-{}".format(
                self.source, self.line_start, self.line_end)
        else:
            raise NotImplementedError

    def relative_to(self, base_dir):
        """
        Create a Origin with source relative to the specified base directory.

        :param base_dir:
            A base directory name
        :returns:
            A new Origin with source replaced by the result of calling
            relative_to(base_dir) on the current source *iff* the current
            source has that method, self otherwise.

        This method is useful for obtaining user friendly Origin objects that
        have short, understandable filenames.
        """
        relative_source = self.source.relative_to(base_dir)
        if relative_source is not self.source:
            return Origin(relative_source, self.line_start, self.line_end)
        else:
            return self

    def with_offset(self, offset):
        """
        Create a new Origin by adding a offset of a specific number of lines.

        :param offset:
            Number of lines to add (or subtract)
        :returns:
            A new Origin object
        """
        mode = self.mode()
        if mode is OriginMode.whole_file:
            return self
        elif mode is OriginMode.single_line or mode is OriginMode.line_range:
            return Origin(
                self.source, self.line_start + offset, self.line_end + offset)
        else:
            raise NotImplementedError

    def just_line(self):
        """
        Create a new Origin that points to the start line.

        :returns:
            A new Origin with the end_line equal to start_line.
            This effectively makes the origin describe a single line.
        """
        return Origin(self.source, self.line_start, self.line_start)

    def just_file(self):
        """
        create a new Origin that points to the whole file.

        :returns:
            A new Origin with line_end and line_start both set to None.
        """
        return Origin(self.source)

    def __eq__(self, other):
        if isinstance(other, Origin):
            return ((self.source, self.line_start, self.line_end) ==
                    (other.source, other.line_start, other.line_end))
        else:
            return NotImplemented

    def __gt__(self, other):
        if isinstance(other, Origin):
            return ((self.source, self.line_start, self.line_end) >
                    (other.source, other.line_start, other.line_end))
        else:
            return NotImplemented


@functools.total_ordering
class UnknownTextSource():

    """
    Class indicating that the source of text is unknown.

    This instances of this class are constructed by gen_rfc822_records() when
    no explicit source is provided and the stream has no name.
    """

    def __str__(self):
        return _("???")

    def __repr__(self):
        return "{}()".format(self.__class__.__name__)

    def __eq__(self, other):
        if isinstance(other, UnknownTextSource):
            return True
        else:
            return False

    def __gt__(self, other):
        if isinstance(other, UnknownTextSource):
            return False
        else:
            return NotImplemented

    def relative_to(self, path):
        return self


@functools.total_ordering
class FileTextSource:

    """
    Class indicating that text came from a file.

    :attribute filename:
        name of the file something comes from
    """

    def __init__(self, filename):
        self.filename = filename

    def __str__(self):
        return self.filename

    def __repr__(self):
        return "{}({!r})".format(
            self.__class__.__name__, self.filename)

    def __eq__(self, other):
        if isinstance(other, FileTextSource):
            return self.filename == other.filename
        else:
            return False

    def __gt__(self, other):
        if isinstance(other, FileTextSource):
            return self.filename > other.filename
        else:
            return NotImplemented

    def relative_to(self, base_dir):
        """
        Compute a FileTextSource with the filename being a relative path from
        the specified base directory.

        :param base_dir:
            A base directory name
        :returns:
            A new FileTextSource with filename relative to that base_dir
        """
        return self.__class__(os.path.relpath(self.filename, base_dir))


class RFC822Record:

    """
    Class for tracking RFC822 records.

    This is a simple container for the dictionary of data. The data is
    represented by two copies, one original and one after value normalization.
    Value normalization strips out excess whitespace and processes the magic
    leading dot syntax that is essential for empty newlines.

    Comparison is performed on the normalized data only, raw data is stored for
    reference but does not differentiate records.

    Each instance also holds the origin of the data (location of the
    file/stream where it was parsed from).
    """

    def __init__(self, data, origin=None, raw_data=None,
                 field_offset_map=None):
        """
        Initialize a new record.

        :param data:
            A dictionary with normalized record data
        :param origin:
            A :class:`Origin` instance that describes where the data came from
        :param raw_data:
            An optional dictionary with raw record data. If omitted then it
            will default to normalized data (as the same object, without making
            a copy)
        :param field_offset_map:
            An optional dictionary with offsets (in line numbers) of each field
        """
        self._data = data
        if raw_data is None:
            raw_data = data
        self._raw_data = raw_data
        self._origin = origin
        self._field_offset_map = field_offset_map

    def __repr__(self):
        return "<{} data:{!r} origin:{!r}>".format(
            self.__class__.__name__, self._data, self._origin)

    def __eq__(self, other):
        if isinstance(other, RFC822Record):
            return (self._data, self._origin) == (other._data, other._origin)
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, RFC822Record):
            return (self._data, self._origin) != (other._data, other._origin)
        return NotImplemented

    @property
    def data(self):
        """
        The normalized version of the data set (dictionary)

        This property exposes the normalized version of the data encapsulated
        in this record. Normalization is performed with
        :func:`normalize_rfc822_value()`. Only values are normalized, keys are
        left intact.
        """
        return self._data

    @property
    def raw_data(self):
        """
        The raw version of data set (dictionary).

        This property exposes the raw (original) version of the data
        encapsulated by this record. This data is as it was originally parsed,
        including all the whitespace layout.

        In some records this may be 'normal' data object itself (same object).
        """
        return self._raw_data

    @property
    def origin(self):
        """The origin of the record."""
        return self._origin

    @property
    def field_offset_map(self):
        """
        The field-to-line-number-offset mapping.

        A dictionary mapping field name to offset (in lines) relative to the
        origin where that field definition commences.

        Note: the return value may be None
        """
        return self._field_offset_map

    def dump(self, stream):
        """Dump this record to a stream."""
        def _dump_part(stream, key, values):
            stream.write("{}:\n".format(key))
            for value in values:
                if not value:
                    stream.write(" .\n")
                elif value == ".":
                    stream.write(" ..\n")
                else:
                    stream.write(" {}\n".format(value))
        for key, value in self.data.items():
            if isinstance(value, (list, tuple)):
                _dump_part(stream, key, value)
            elif isinstance(value, str) and "\n" in value:
                values = value.split("\n")
                if not values[-1]:
                    values = values[:-1]
                _dump_part(stream, key, values)
            else:
                stream.write("{}: {}\n".format(key, value))
        stream.write("\n")


class RFC822SyntaxError(SyntaxError):

    """SyntaxError subclass for RFC822 parsing functions"""

    def __init__(self, filename, lineno, msg):
        self.filename = filename
        self.lineno = lineno
        self.msg = msg

    def __repr__(self):
        return "{}({!r}, {!r}, {!r})".format(
            self.__class__.__name__, self.filename, self.lineno, self.msg)

    def __eq__(self, other):
        if isinstance(other, RFC822SyntaxError):
            return ((self.filename, self.lineno, self.msg) == (
                other.filename, other.lineno, other.msg))
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, RFC822SyntaxError):
            return ((self.filename, self.lineno, self.msg) != (
                other.filename, other.lineno, other.msg))
        return NotImplemented

    def __hash__(self):
        return hash((self.filename, self.lineno, self.msg))


def load_rfc822_records(stream, data_cls=dict, source=None):
    """
    Load a sequence of rfc822-like records from a text stream.

    :param stream:
        A file-like object from which to load the rfc822 data
    :param data_cls:
        The class of the dictionary-like type to hold the results. This is
        mainly there so that callers may pass collections.OrderedDict.
    :param source:
        An object that describes where stream data is coming from.

        If None, it will be inferred from the stream (if possible). Specialized
        callers should provider a custom source object to allow developers to
        accurately keep track of where (possibly problematic) RFC822 data is
        coming from. If this is None and inferring fails then all of the loaded
        records will have a None origin.

    Each record consists of any number of key-value pairs. Subsequent records
    are separated by one blank line. A record key may have a multi-line value
    if the line starts with whitespace character.

    Returns a list of subsequent values as instances RFC822Record class.  If
    the optional data_cls argument is collections.OrderedDict then the values
    retain their original ordering.
    """
    return list(gen_rfc822_records(stream, data_cls, source))


def gen_rfc822_records(stream, data_cls=dict, source=None):
    """
    Load a sequence of rfc822-like records from a text stream.

    :param stream:
        A file-like object from which to load the rfc822 data
    :param data_cls:
        The class of the dictionary-like type to hold the results. This is
        mainly there so that callers may pass collections.OrderedDict.
    :param source:
        An object that describes where stream data is coming from.

        If None, it will be inferred from the stream (if possible). Specialized
        callers should provider a custom source object to allow developers to
        accurately keep track of where (possibly problematic) RFC822 data is
        coming from. If this is None and inferring fails then all of the loaded
        records will have a None origin.

    Each record consists of any number of key-value pairs. Subsequent records
    are separated by one blank line. A record key may have a multi-line value
    if the line starts with whitespace character.

    Returns a list of subsequent values as instances RFC822Record class. If
    the optional data_cls argument is collections.OrderedDict then the values
    retain their original ordering.
    """
    record = None
    key = None
    value_list = None
    origin = None
    field_offset_map = None
    # If the source was not provided then try constructing a FileTextSource
    # from the name of the stream. If that fails, keep using None.
    if source is None:
        try:
            source = FileTextSource(stream.name)
        except AttributeError:
            source = UnknownTextSource()

    def _syntax_error(msg):
        """Report a syntax error in the current line."""
        try:
            filename = stream.name
        except AttributeError:
            filename = None
        return RFC822SyntaxError(filename, lineno, msg)

    def _new_record():
        """Reset local state to track new record."""
        nonlocal key
        nonlocal value_list
        nonlocal record
        nonlocal origin
        nonlocal field_offset_map
        key = None
        value_list = None
        if source is not None:
            origin = Origin(source, None, None)
        field_offset_map = {}
        record = RFC822Record(data_cls(), origin, data_cls(), field_offset_map)

    def _commit_key_value_if_needed():
        """Finalize the most recently seen key: value pair."""
        nonlocal key
        if key is not None:
            raw_value = ''.join(value_list)
            normalized_value = normalize_rfc822_value(raw_value)
            record.raw_data[key] = raw_value
            record.data[key] = normalized_value
            _logger.debug(_("Committed key/value %r=%r"), key,
                          normalized_value)
            key = None

    def _set_start_lineno_if_needed():
        """Remember the line number of the record start unless already set."""
        if origin and record.origin.line_start is None:
            record.origin.line_start = lineno

    def _update_end_lineno():
        """Update the line number of the record tail."""
        if origin:
            record.origin.line_end = lineno

    # Start with an empty record
    _new_record()
    # Support simple text strings
    if isinstance(stream, str):
        # keepends=True (python3.2 has no keyword for this)
        stream = iter(stream.splitlines(True))
    # Iterate over subsequent lines of the stream
    for lineno, line in enumerate(stream, start=1):
        _logger.debug(_("Looking at line %d:%r"), lineno, line)
        # Treat # as comments
        if line.startswith("#"):
            pass
        # Treat empty lines as record separators
        elif line.strip() == "":
            # Commit the current record so that the multi-line value of the
            # last key, if any, is saved as a string
            _commit_key_value_if_needed()
            # If data is non-empty, yield the record, this allows us to safely
            # use newlines for formatting
            if record.data:
                _logger.debug(_("yielding record: %r"), record)
                yield record
            # Reset local state so that we can build a new record
            _new_record()
        # Treat lines staring with whitespace as multi-line continuation of the
        # most recently seen key-value
        elif line.startswith(" "):
            if key is None:
                # If we have not seen any keys yet then this is a syntax error
                raise _syntax_error(_("Unexpected multi-line value"))
            # Strip the initial space. This matches the behavior of xgettext
            # scanning our job definitions with multi-line values.
            line = line[1:]
            # Append the current line to the list of values of the most recent
            # key. This prevents quadratic complexity of string concatenation
            value_list.append(line)
            # Update the end line location of this record
            _update_end_lineno()
        # Treat lines with a colon as new key-value pairs
        elif ":" in line:
            # Since this is actual data let's try to remember where it came
            # from. This may be a no-operation if there were any preceding
            # key-value pairs.
            _set_start_lineno_if_needed()
            # Since we have a new, key-value pair we need to commit any
            # previous key that we may have (regardless of multi-line or
            # single-line values).
            _commit_key_value_if_needed()
            # Parse the line by splitting on the colon, getting rid of
            # all surrounding whitespace from the key and getting rid of the
            # leading whitespace from the value.
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.lstrip()
            # Check if the key already exist in this message
            if key in record.data:
                raise _syntax_error(_(
                    "Job has a duplicate key {!r} "
                    "with old value {!r} and new value {!r}"
                ).format(key, record.raw_data[key], value))
            if value.strip() != "":
                # Construct initial value list out of the (only) value that we
                # have so far. Additional multi-line values will just append to
                # value_list
                value_list = [value]
                # Store the offset of the filed in the offset map
                field_offset_map[key] = lineno - origin.line_start
            else:
                # The initial line may be empty, in that case the spaces and
                # newlines there are discarded
                value_list = []
                # Store the offset of the filed in the offset map
                # The +1 is for the fact that value is empty (or just
                # whitespace) and that is stripped away in the normalized data
                # part of the RFC822 record. To keep line tracking accurate
                # we just assume that the field actually starts on
                # the following line.
                field_offset_map[key] = lineno - origin.line_start + 1
            # Update the end-line location
            _update_end_lineno()
        # Treat all other lines as syntax errors
        else:
            raise _syntax_error(
                _("Unexpected non-empty line: {!r}").format(line))
    # Make sure to commit the last key from the record
    _commit_key_value_if_needed()
    # Once we've seen the whole file return the last record, if any
    if record.data:
        _logger.debug(_("yielding record: %r"), record)
        yield record
