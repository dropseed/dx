import datetime
from decimal import Decimal
from types import NoneType
from urllib.parse import quote

from plain.utils.functional import Promise


class PlainUnicodeDecodeError(UnicodeDecodeError):
    def __init__(self, obj, *args):
        self.obj = obj
        super().__init__(*args)

    def __str__(self):
        return f"{super().__str__()}. You passed in {self.obj!r} ({type(self.obj)})"


_PROTECTED_TYPES = (
    NoneType,
    int,
    float,
    Decimal,
    datetime.datetime,
    datetime.date,
    datetime.time,
)


def is_protected_type(obj):
    """Determine if the object instance is of a protected type.

    Objects of protected types are preserved as-is when passed to
    force_str(strings_only=True).
    """
    return isinstance(obj, _PROTECTED_TYPES)


def force_str(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_str(), except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if issubclass(type(s), str):
        return s
    if strings_only and is_protected_type(s):
        return s
    try:
        if isinstance(s, bytes):
            s = str(s, encoding, errors)
        else:
            s = str(s)
    except UnicodeDecodeError as e:
        raise PlainUnicodeDecodeError(s, *e.args)
    return s


def force_bytes(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_bytes, except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if isinstance(s, bytes):
        if encoding == "utf-8":
            return s
        else:
            return s.decode("utf-8", errors).encode(encoding, errors)
    if strings_only and is_protected_type(s):
        return s
    if isinstance(s, memoryview):
        return bytes(s)
    return str(s).encode(encoding, errors)


def iri_to_uri(iri):
    """
    Convert an Internationalized Resource Identifier (IRI) portion to a URI
    portion that is suitable for inclusion in a URL.

    This is the algorithm from RFC 3987 Section 3.1, slightly simplified since
    the input is assumed to be a string rather than an arbitrary byte stream.

    Take an IRI (string or UTF-8 bytes, e.g. '/I ♥ Plain/' or
    b'/I \xe2\x99\xa5 Plain/') and return a string containing the encoded
    result with ASCII chars only (e.g. '/I%20%E2%99%A5%20Plain/').
    """
    # The list of safe characters here is constructed from the "reserved" and
    # "unreserved" characters specified in RFC 3986 Sections 2.2 and 2.3:
    #     reserved    = gen-delims / sub-delims
    #     gen-delims  = ":" / "/" / "?" / "#" / "[" / "]" / "@"
    #     sub-delims  = "!" / "$" / "&" / "'" / "(" / ")"
    #                   / "*" / "+" / "," / ";" / "="
    #     unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
    # Of the unreserved characters, urllib.parse.quote() already considers all
    # but the ~ safe.
    # The % character is also added to the list of safe characters here, as the
    # end of RFC 3987 Section 3.1 specifically mentions that % must not be
    # converted.
    if iri is None:
        return iri
    elif isinstance(iri, Promise):
        iri = str(iri)
    return quote(iri, safe="/#%[]=:;$&()+,!?*@'~")


# List of byte values that uri_to_iri() decodes from percent encoding.
# First, the unreserved characters from RFC 3986:
_ascii_ranges = [[45, 46, 95, 126], range(65, 91), range(97, 123)]
_hextobyte = {
    (fmt % char).encode(): bytes((char,))
    for ascii_range in _ascii_ranges
    for char in ascii_range
    for fmt in ["%02x", "%02X"]
}
# And then everything above 128, because bytes ≥ 128 are part of multibyte
# Unicode characters.
_hexdig = "0123456789ABCDEFabcdef"
_hextobyte.update(
    {(a + b).encode(): bytes.fromhex(a + b) for a in _hexdig[8:] for b in _hexdig}
)


def punycode(domain):
    """Return the Punycode of the given domain if it's non-ASCII."""
    return domain.encode("idna").decode("ascii")
